"""echo's public API.

    extract  ->  Document        what the file says
    normalize->  Script          what the narrator says, in chapters
    synthesize-> Segment[]       one audio file per utterance
    assemble ->  .m4b / .mp3     one file, with chapter marks
    tag      ->  metadata + cover art
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

import echo.audio.assemble as asm
import echo.audio.mp3_utils as mp3z
import echo.audio.tts as tts
import echo.constants as ec
import echo.normalize as norm
from echo.audio.engines import get_engine
from echo.document import Document, Script
from echo.extractors import extract

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Introspection helpers
# ─────────────────────────────────────────────────────────────────────────────


def print_voices(engine: str = None) -> None:
    for voice in get_engine(engine).voices():
        print(f"{voice.id}\t{voice.label}\t{voice.tags}")


def open_in_default_app(path: Path) -> None:
    """Open a file with the OS default application.

    ``os.startfile`` exists only on Windows, so the previous version of this
    raised AttributeError on macOS and Linux.
    """
    path = str(Path(path).resolve())
    if sys.platform == "darwin":
        subprocess.run(["open", path], check=False)
    elif os.name == "nt":
        os.startfile(path)  # noqa: S606 — Windows-only branch
    else:
        subprocess.run(["xdg-open", path], check=False)


def play_mp3_clip(voice: str, speed: float = 1, engine: str = None, output_dir: Path = None):
    """Synthesize a short sample with a voice and open it, to audition it."""
    output_dir = Path(output_dir) if output_dir else Path(ec.OUTPUT_FOLDER or ".")
    output_dir.mkdir(parents=True, exist_ok=True)
    resolved = get_engine(engine)
    sample_path = output_dir / f"sample{resolved.audio_suffix}"
    sample_path.unlink(missing_ok=True)

    text = (
        "This is a short sample of this voice. If you like how it sounds, "
        "it will read your whole book this way."
    )
    asyncio.run(resolved.synthesize(text, voice, speed, sample_path))
    open_in_default_app(sample_path)
    return sample_path


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline stages
# ─────────────────────────────────────────────────────────────────────────────


def extract_document(input_path: str | Path, configs: dict = None) -> Document:
    """Parse a file into a structured Document and apply the rules normalizer."""
    doc = extract(input_path, **(configs or {}))
    return norm.apply_rules(doc)


def convert_to_text(input_path: str | Path, configs: dict = None) -> str:
    """Extract a file's narratable text as a plain string.

    Retained for callers that only want text — the pipeline itself now passes a
    :class:`~echo.document.Document` so it can carry chapters and skip lists.
    """
    return extract_document(input_path, configs).as_text()


def build_script(
    doc: Document,
    engine_name: str = None,
    normalizer: str = None,
    chunk_size: int = None,
) -> Script:
    """Turn a Document into a chapter-aware Script sized for the engine."""
    engine = get_engine(engine_name)
    limit = min(chunk_size or ec.CHUNK_SIZE, engine.max_chars)
    resolved = norm.get_normalizer(normalizer)
    # Fail before any synthesis rather than falling back for every chunk: if LLM
    # normalization was asked for, silently not doing it is the wrong answer.
    resolved.check_available()
    return norm.build_script(doc, chunk_size=limit, normalizer=resolved)


# ─────────────────────────────────────────────────────────────────────────────
# The whole pipeline
# ─────────────────────────────────────────────────────────────────────────────


def file_to_audio(
    file_path: str | Path,
    output_path: str | Path = None,
    mp3_meta: dict = None,
    voice: str = None,
    speed: float = None,
    engine: str = None,
    fmt: str = None,
    normalizer: str = None,
    write_text_file: bool = False,
    write_transcript: bool = None,
    parser_configs: dict = None,
    resume: bool = True,
) -> Path:
    """Convert a text-bearing file into an audiobook.

    Args:
        file_path: source ``.pdf``, ``.epub``, ``.txt`` or ``.md``.
        output_path: destination; the suffix follows ``fmt`` when given.
        mp3_meta: ``title`` / ``author`` / ``image_path`` for tagging.
        voice: engine-specific voice id; the engine's default when omitted.
        speed: playback multiplier, applied by the engine or by ffmpeg.
        engine: ``edge`` (default), ``gemini``, ``google-cloud`` or ``mlx``.
        fmt: ``m4b`` (default, chaptered) or ``mp3``.
        normalizer: ``off`` (default), ``local`` or ``gemini``.
        write_text_file: also write the narrated text beside the audio.
        write_transcript: also write an ``.srt`` when the engine reports timings.
        parser_configs: extractor options (``first_page``, ``last_page``,
            ``force_ocr``, ``use_docling``).
        resume: reuse chunks left behind by an interrupted run.

    Returns:
        Path to the finished audio file.
    """
    started = time.perf_counter()
    file_path = Path(file_path)
    mp3_meta = dict(mp3_meta or {})
    fmt = (fmt or ec.DEFAULT_FORMAT).lower().lstrip(".")
    speed = ec.DEFAULT_SPEED if speed is None else speed
    write_transcript = ec.WRITE_TRANSCRIPT if write_transcript is None else write_transcript

    resolved_engine = get_engine(engine)
    resolved_engine.check_available()
    voice = voice or resolved_engine.default_voice()

    if output_path is None:
        base = Path(ec.OUTPUT_FOLDER) / file_path.name if ec.OUTPUT_FOLDER else file_path
        output_path = base.with_suffix(f".{fmt}")
    else:
        output_path = Path(output_path).with_suffix(f".{fmt}")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # 1. Extract + rules normalization
    doc = extract_document(file_path, parser_configs)

    # 2. Script: chapters and engine-sized utterances
    script = build_script(doc, engine_name=engine, normalizer=normalizer)

    if write_text_file:
        text_path = output_path.with_suffix(".txt")
        text_path.write_text(script.as_text(), encoding="utf-8")
        log.info(f"Wrote narrated text to {text_path}")

    # 3. Synthesis
    chunks_dir = tts.chunks_dir_for(output_path)
    segments = asyncio.run(
        tts.synthesize_script(
            script,
            engine=resolved_engine,
            voice=voice,
            speed=speed,
            chunks_dir=chunks_dir,
            resume=resume,
        )
    )
    if len(segments) != len(script.utterances()):
        raise asm.AssemblyError(
            f"Expected {len(script.utterances())} audio chunk(s) but got {len(segments)}; "
            f"refusing to build a file that is missing content. Chunks are in {chunks_dir}."
        )

    # 4. Chapter marks from the per-chapter durations
    durations_by_chapter: list[list[int]] = [[] for _ in script.chapters]
    for i, segment in enumerate(segments):
        durations_by_chapter[script.chapter_of(i)].append(segment.duration_ms)
    marks = asm.chapter_marks([c.title for c in script.chapters], durations_by_chapter)

    # 5. Assemble
    title = mp3_meta.get("title") or script.title
    author = mp3_meta.get("author") or script.author
    final_path = asm.assemble(
        [s.path for s in segments],
        output_path,
        fmt=fmt,
        chapters=marks,
        title=title,
        author=author,
        speed=None if resolved_engine.supports_speed else speed,
    )

    # 6. Transcript, while the segment timings are still around
    if write_transcript:
        if any(s.timings for s in segments):
            asm.write_srt(final_path, [(s.duration_ms, s.timings) for s in segments])
        else:
            log.info(f"{resolved_engine.label} does not report word timings; no transcript written")

    # 7. Tags and cover art
    mp3z.add_meta_fields(
        final_path,
        image_path=mp3_meta.get("image_path"),
        title=title,
        author=author,
    )

    asm.cleanup(chunks_dir)
    log.info(
        f"Done: {final_path} ({len(script.chapters)} chapter(s)) in "
        f"{(time.perf_counter() - started) / 60:.2f} minutes"
    )
    return final_path


def file_to_mp3(
    file_path: str | Path,
    mp3_path: str | Path = None,
    mp3_meta: dict = None,
    voice: str = None,
    speed: float = None,
    write_text_file: bool = False,
    parser_configs: dict = None,
    **kwargs,
) -> Path:
    """Backwards-compatible wrapper: same arguments as before, MP3 output."""
    return file_to_audio(
        file_path,
        output_path=mp3_path,
        mp3_meta=mp3_meta,
        voice=voice,
        speed=speed,
        fmt=kwargs.pop("fmt", "mp3"),
        write_text_file=write_text_file,
        parser_configs=parser_configs,
        **kwargs,
    )


def text_to_mp3(text: str, mp3_path: str | Path, voice: str = None, speed: float = None, engine: str = None):
    """Convert a string directly to audio."""
    return tts.text_to_mp3(text, str(mp3_path), voice=voice, speed=speed, engine=engine)
