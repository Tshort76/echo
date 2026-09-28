"""The library's entry point: titled chapters of text in, one chaptered audio file out.

    speak_chapters([Chapter("Opening", text), ...], out_path, engine="edge")

The caller decides what is said and where the chapters fall; echo decides how it
is spoken and how the file is built. Each chapter is split to the engine's size
limit on its own, so no chunk straddles two chapters and every chapter mark lands
exactly on its boundary.

``speak_script`` is the same pipeline for a caller that has already built a
:class:`~echo.script.Script` — the app does, because it normalizes text chunk by
chunk before synthesis.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from echo import defaults
from echo.audio import assemble as asm
from echo.audio.assemble import FORMATS, ChapterMark
from echo.audio.engines import SpeechEngine, get_engine
from echo.audio.mp3_utils import add_meta_fields
from echo.audio.tts import ProgressCallback, synthesize_script
from echo.errors import AssemblyError
from echo.script import Script, ScriptChapter, Segment, Utterance
from echo.text import split_text

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Chapter:
    """One titled span of plain text. Becomes one chapter mark in the output."""

    title: str
    text: str


@dataclass(slots=True)
class SpeechResult:
    """What a finished call produced."""

    path: Path
    #: One per chapter, in the output file's timeline (speed already applied).
    #: Each unpacks as ``(title, start_ms, end_ms)``.
    chapters: list[ChapterMark]
    duration_ms: int
    #: Path of the ``.srt`` transcript, when one was asked for and the engine
    #: reported timings.
    transcript: Path | None = None
    engine: str = ""
    voice: str = ""
    segments: int = 0


def script_from_chapters(chapters: list[Chapter], max_chars: int, title: str = None, author: str = None) -> Script:
    """Split each chapter's text into utterances no longer than ``max_chars``."""
    out: list[ScriptChapter] = []
    for chapter in chapters:
        pieces = split_text(chapter.text, max_chars)
        if not pieces:
            raise ValueError(f"Chapter '{chapter.title}' has no text to speak")
        out.append(ScriptChapter(title=chapter.title, utterances=[Utterance(p) for p in pieces]))
    if not out:
        raise ValueError("No chapters to speak")
    return Script(chapters=out, title=title, author=author)


def _resolve_engine(engine: str | SpeechEngine | None) -> SpeechEngine:
    return engine if isinstance(engine, SpeechEngine) else get_engine(engine)


def _resolve_format(out_path: Path, fmt: str | None) -> str:
    fmt = (fmt or out_path.suffix).lower().lstrip(".")
    if fmt not in FORMATS:
        raise ValueError(f"Cannot tell the output format from '{out_path.name}'. Use a .mp3 or .m4b path, or pass fmt.")
    return fmt


async def aspeak_script(
    script: Script,
    out_path: str | Path,
    *,
    engine: str | SpeechEngine = None,
    voice: str = None,
    speed: float = None,
    fmt: str = None,
    title: str = None,
    author: str = None,
    cover: str | Path = None,
    bitrate: str = None,
    work_dir: str | Path = None,
    resume_dir: str | Path = None,
    transcript: bool = False,
    max_retries: int = None,
    retry_backoff: float = None,
    on_progress: ProgressCallback = None,
) -> SpeechResult:
    """Synthesize a prepared Script into one chaptered file. See :func:`speak_chapters`."""
    resolved = _resolve_engine(engine)
    resolved.check_available()
    voice = voice or resolved.default_voice()
    speed = defaults.SPEED if speed is None else speed
    out_path = Path(out_path).expanduser()
    fmt = _resolve_format(out_path, fmt)
    out_path = out_path.with_suffix(f".{fmt}")
    title = title or script.title
    author = author or script.author

    # Scratch always goes in a private directory that is removed when the call ends.
    # Chunks go there too, unless the caller opted into resuming across calls.
    if work_dir is not None:
        Path(work_dir).mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix="echo-", dir=work_dir))
    chunks_dir = Path(resume_dir).expanduser() if resume_dir is not None else scratch / "chunks"
    try:
        segments = await synthesize_script(
            script,
            engine=resolved,
            voice=voice,
            speed=speed,
            chunks_dir=chunks_dir,
            resume=resume_dir is not None,
            max_retries=max_retries,
            retry_backoff=retry_backoff,
            on_progress=on_progress,
        )
        expected = len(script.utterances())
        if len(segments) != expected:
            raise AssemblyError(
                f"Expected {expected} audio chunk(s) but got {len(segments)}; "
                "refusing to build a file that is missing content."
            )

        tempo = None if resolved.supports_speed else speed
        # Segment durations are measured before any atempo, so scale them into the
        # output's timeline. Without this a 1.5x Gemini book had chapter marks that
        # drifted 50% late.
        factor = 1.0 / tempo if tempo else 1.0
        marks = [m.scaled(factor) for m in _chapter_marks(script, segments)]

        await asyncio.to_thread(
            asm.assemble,
            [s.path for s in segments],
            out_path,
            fmt=fmt,
            chapters=marks,
            title=title,
            author=author,
            speed=tempo,
            bitrate=bitrate,
            scratch_dir=scratch,
        )

        srt = None
        if transcript:
            if any(s.timings for s in segments):
                srt = await asyncio.to_thread(asm.write_srt, out_path, _timings(segments, factor))
            else:
                log.info(f"{resolved.label} does not report word timings; no transcript written")

        await asyncio.to_thread(add_meta_fields, out_path, image_path=cover, title=title, author=author)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)

    # Only after success: resume chunks surviving a failure is the point of them.
    if resume_dir is not None:
        asm.cleanup(chunks_dir)
    return SpeechResult(
        path=out_path,
        chapters=marks,
        duration_ms=marks[-1].end_ms if marks else 0,
        transcript=srt,
        engine=resolved.name,
        voice=voice,
        segments=len(segments),
    )


def _chapter_marks(script: Script, segments: list[Segment]) -> list[ChapterMark]:
    durations: list[list[int]] = [[] for _ in script.chapters]
    for i, segment in enumerate(segments):
        durations[script.chapter_of(i)].append(segment.duration_ms)
    return asm.chapter_marks([c.title for c in script.chapters], durations)


def _timings(segments: list[Segment], factor: float) -> list[tuple[int, list]]:
    if factor == 1.0:
        return [(s.duration_ms, s.timings) for s in segments]
    from echo.script import Timing  # noqa: PLC0415

    return [
        (
            round(s.duration_ms * factor),
            [Timing(round(t.start_ms * factor), round(t.end_ms * factor), t.text) for t in s.timings],
        )
        for s in segments
    ]


async def aspeak_chapters(
    chapters: list[Chapter],
    out_path: str | Path,
    *,
    engine: str | SpeechEngine = None,
    chunk_size: int = None,
    title: str = None,
    **options,
) -> SpeechResult:
    """Async form of :func:`speak_chapters`, for callers already in an event loop."""
    resolved = _resolve_engine(engine)
    limit = min(chunk_size or defaults.CHUNK_SIZE, resolved.max_chars)
    script = script_from_chapters(chapters, limit, title=title, author=options.get("author"))
    return await aspeak_script(script, out_path, engine=resolved, title=title, **options)


def speak_chapters(
    chapters: list[Chapter],
    out_path: str | Path,
    *,
    engine: str | SpeechEngine = None,
    voice: str = None,
    speed: float = None,
    fmt: str = None,
    title: str = None,
    author: str = None,
    cover: str | Path = None,
    bitrate: str = None,
    chunk_size: int = None,
    work_dir: str | Path = None,
    resume_dir: str | Path = None,
    transcript: bool = False,
    max_retries: int = None,
    retry_backoff: float = None,
    on_progress: ProgressCallback = None,
) -> SpeechResult:
    """Speak titled chapters of plain text into one chaptered audio file.

    Args:
        chapters: ``Chapter(title, text)`` in reading order. Each becomes one
            chapter mark; its text is split to the engine's limit on its own.
        out_path: destination. The format comes from its suffix (``.mp3`` or
            ``.m4b``) unless ``fmt`` is given. MP3 carries ID3 CHAP/CTOC chapter
            frames; M4B carries native chapters.
        engine: a registry name (``edge``, ``gemini``, ``google-cloud``, ``mlx``)
            or a :class:`~echo.audio.engines.SpeechEngine` instance.
        voice: engine-specific voice id; the engine's default when omitted.
        speed: rate multiplier. Applied by the engine when it can, else by ffmpeg.
        title, author, cover: written as tags (and cover art).
        bitrate: used whenever audio is re-encoded (default ``64k``).
        chunk_size: upper bound on utterance length, before the engine's own limit.
        work_dir: parent for scratch files; a private subdirectory is made inside
            it and removed when the call returns or raises. System temp by default.
        resume_dir: opt-in. Chunks are kept here, reused by a later call with the
            same text, voice, engine and speed, and removed after success.
        transcript: also write an ``.srt`` beside the output, when the engine
            reports timings.
        max_retries, retry_backoff: per-utterance retry policy.
        on_progress: ``on_progress(done, total)`` in utterances.

    Returns:
        :class:`SpeechResult` with the path and each chapter's start and end.

    Raises:
        EngineUnavailable: before any synthesis, with what to install or set.
        SynthesisError: an utterance still failed after its retries.
        AssemblyError: ffmpeg could not build the file.

    Blocking; from inside an event loop, await :func:`aspeak_chapters` instead.
    """
    return asyncio.run(
        aspeak_chapters(
            chapters,
            out_path,
            engine=engine,
            voice=voice,
            speed=speed,
            fmt=fmt,
            title=title,
            author=author,
            cover=cover,
            bitrate=bitrate,
            chunk_size=chunk_size,
            work_dir=work_dir,
            resume_dir=resume_dir,
            transcript=transcript,
            max_retries=max_retries,
            retry_backoff=retry_backoff,
            on_progress=on_progress,
        )
    )


def speak_script(script: Script, out_path: str | Path, **options) -> SpeechResult:
    """Blocking form of :func:`aspeak_script`."""
    return asyncio.run(aspeak_script(script, out_path, **options))
