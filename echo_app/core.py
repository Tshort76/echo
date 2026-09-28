"""The app's pipeline: a file on disk in, an audiobook out.

Everything about *speaking* is the ``echo`` library's; this module adds what
only the app needs — extraction, normalization, and the ``.env`` defaults,
which it passes to the library as arguments.

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
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import echo.audio.assemble as asm
import echo.audio.tts as tts
import echo_app.constants as ec
import echo_app.normalize as norm
from echo.audio.engines import SpeechEngine
from echo.audio.engines import get_engine as _library_get_engine
from echo.speech import speak_script
from echo_app.document import Document, Script
from echo_app.extractors import extract

log = logging.getLogger(__name__)


def get_engine(name: str = None) -> SpeechEngine:
    """The library's registry, defaulting to ``DEFAULT_ENGINE`` from ``.env``."""
    return _library_get_engine(name or ec.DEFAULT_ENGINE)


def default_voice(engine: SpeechEngine) -> str:
    """``DEFAULT_VOICE`` from ``.env`` names an edge voice; other engines keep their own."""
    return ec.DEFAULT_VOICE if engine.name == "edge" else engine.default_voice()


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


PREVIEW_TEXT = (
    "This is a short sample of this voice, at the speed you chose. "
    "If you like how it sounds, it will read your whole book this way."
)


def preview_path(voice: str, engine: str = None, output_dir: Path = None) -> Path:
    """Where a preview of ``voice`` is written.

    Deterministic, and stable across runs: the filename is a slug of the engine and
    voice. It used to be ``abs(hash(voice))``, but Python randomizes string hashing
    per process, so every launch wrote a new file and nothing was ever reused.

    Defaults to a temp directory rather than the output folder or the cwd — a preview
    is scratch, and the previous default dropped ``sample.mp3`` wherever you ran it.
    """
    resolved = get_engine(engine)
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", voice).strip("-") or "voice"
    directory = Path(output_dir) if output_dir else Path(tempfile.gettempdir()) / "echo-preview"
    return directory / f"{resolved.name}-{slug}{resolved.audio_suffix}"


def preview_voice(
    voice: str,
    speed: float = 1.0,
    engine: str = None,
    output_dir: Path = None,
    text: str = None,
    open_after: bool = True,
) -> Path:
    """Synthesize a short sample of ``voice`` and open it, to audition it.

    The one preview implementation. There were three — this, a copy in the GUI worker
    and a dead edge-only helper — each with different sample text and a different
    destination.

    ``speed`` is honoured even on engines that cannot vary their own rate: ffmpeg
    applies it, exactly as the assembler does for a real book. Otherwise a preview of
    a Gemini voice would play at 1.0x while claiming to be at the chosen speed.
    """
    resolved = get_engine(engine)
    resolved.check_available()  # fail with "set GEMINI_API_KEY", not a stack trace

    out = preview_path(voice, engine, output_dir)
    out.parent.mkdir(parents=True, exist_ok=True)
    # Always re-synthesized: a stable name keeps one file per voice rather than
    # skipping work, so a preview always reflects the current text and speed.
    out.unlink(missing_ok=True)

    needs_ffmpeg = not resolved.supports_speed and abs(speed - 1.0) > 0.001
    # Stage the engine's own output separately when ffmpeg has to re-encode it. For an
    # engine that already emits .mp3, the final path *is* out.with_suffix(".mp3"), so
    # passing `out` as both input and output had ffmpeg truncating the file it was
    # reading — which produced a preview about 30% too short rather than an error.
    raw = out.with_name(f"{out.stem}.raw{resolved.audio_suffix}") if needs_ffmpeg else out

    asyncio.run(resolved.synthesize(text or PREVIEW_TEXT, voice, speed if not needs_ffmpeg else 1.0, raw))

    if needs_ffmpeg:
        log.info(f"{resolved.label} cannot vary its rate; applying {speed}x with ffmpeg")
        out = asm.assemble([raw], out.with_suffix(".mp3"), fmt="mp3", speed=speed)
        raw.unlink(missing_ok=True)

    if open_after:
        open_in_default_app(out)
    return out


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
    :class:`~echo_app.document.Document` so it can carry chapters and skip lists.
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
    voice = voice or default_voice(resolved_engine)

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

    # 3–7. Synthesis, chapter marks, assembly, transcript and tags: the library's job.
    result = speak_script(
        script,
        output_path,
        engine=resolved_engine,
        voice=voice,
        speed=speed,
        fmt=fmt,
        title=mp3_meta.get("title") or script.title,
        author=mp3_meta.get("author") or script.author,
        cover=mp3_meta.get("image_path"),
        bitrate=ec.M4B_BITRATE,
        # The app resumes interrupted books from a folder beside the output.
        resume_dir=tts.chunks_dir_for(output_path) if resume else None,
        transcript=write_transcript,
        max_retries=ec.MAX_RETRIES,
        retry_backoff=ec.RETRY_BACKOFF_SECONDS,
    )
    log.info(
        f"Done: {result.path} ({len(result.chapters)} chapter(s)) in "
        f"{(time.perf_counter() - started) / 60:.2f} minutes"
    )
    return result.path


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


def text_to_mp3(text: str, mp3_path: str | Path, voice: str = None, speed: float = None, engine: str = None) -> Path:
    """Convert a string straight to audio, detecting plain-text headings as chapters."""
    from echo_app.extractors.text import blocks_from_plain_text  # noqa: PLC0415

    resolved = get_engine(engine)
    script = build_script(Document(blocks=blocks_from_plain_text(text)), engine_name=resolved.name)
    output_path = Path(mp3_path)
    return speak_script(
        script,
        output_path,
        engine=resolved,
        voice=voice or default_voice(resolved),
        speed=ec.DEFAULT_SPEED if speed is None else speed,
        fmt=output_path.suffix.lstrip(".") or "mp3",
        bitrate=ec.M4B_BITRATE,
        max_retries=ec.MAX_RETRIES,
        retry_backoff=ec.RETRY_BACKOFF_SECONDS,
    ).path
