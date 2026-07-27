"""Drive a :class:`~echo.document.Script` through a speech engine.

What changed here, beyond becoming engine-agnostic:

* **Retry.** Every engine fails transiently — edge-tts's unofficial endpoint
  returns websocket 403s, cloud engines rate-limit. Each utterance gets several
  attempts with backoff.
* **Resume.** Chunk files are keyed by index and kept until assembly succeeds, so
  a re-run skips everything already on disk instead of re-synthesizing a book.
* **No partial success.** ``asyncio.gather`` used to run without
  ``return_exceptions``, so one failure anywhere aborted the run; now every
  utterance is attempted and the summary names what failed, rather than a
  half-finished book being silently assembled.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

import echo.constants as ec
from echo.audio.engines import EngineUnavailable, SpeechEngine, get_engine
from echo.document import Script, Segment, Utterance
from echo.normalize import build_script

log = logging.getLogger(__name__)


class SynthesisError(RuntimeError):
    """Raised when utterances could not be synthesized after retries."""


def chunks_dir_for(output_path: Path) -> Path:
    output_path = Path(output_path)
    return output_path.parent / f"{output_path.stem}_chunks"


def _segment_path(chunks_dir: Path, index: int, suffix: str) -> Path:
    return chunks_dir / f"chunk_{index:05d}{suffix}"


def _usable(path: Path) -> int:
    """Duration of an existing chunk in ms, or 0 if it isn't usable."""
    from echo.audio.assemble import audio_duration_ms  # noqa: PLC0415 (avoids a cycle)

    try:
        if not path.exists() or path.stat().st_size == 0:
            return 0
        return audio_duration_ms(path)
    except Exception:
        return 0


async def _synthesize_one(
    engine: SpeechEngine,
    index: int,
    utterance: Utterance,
    voice: str,
    speed: float,
    path: Path,
    attempts: int,
    backoff: float,
) -> Segment:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            result = await engine.synthesize(utterance.text, utterance.voice or voice, speed, path)
            duration = result.duration_ms or _usable(path)
            if not duration:
                raise EngineUnavailable(f"chunk {index} was written but contains no audio")
            return Segment(index=index, path=path, duration_ms=duration, timings=result.timings)
        except Exception as ex:
            last_error = ex
            path.unlink(missing_ok=True)
            if attempt < attempts:
                delay = backoff * (2 ** (attempt - 1))
                log.warning(
                    f"Chunk {index} failed on attempt {attempt}/{attempts} "
                    f"({type(ex).__name__}: {str(ex)[:120]}); retrying in {delay:.1f}s"
                )
                await asyncio.sleep(delay)

    raise SynthesisError(f"chunk {index} failed after {attempts} attempts: {last_error}") from last_error


async def synthesize_script(
    script: Script,
    engine: SpeechEngine = None,
    voice: str = None,
    speed: float = None,
    chunks_dir: Path = None,
    resume: bool = True,
) -> list[Segment]:
    """Synthesize every utterance in ``script``, returning segments in order."""
    engine = engine or get_engine()
    engine.check_available()
    voice = voice or engine.default_voice()
    speed = ec.DEFAULT_SPEED if speed is None else speed
    engine_speed = speed if engine.supports_speed else 1.0

    chunks_dir = Path(chunks_dir)
    chunks_dir.mkdir(parents=True, exist_ok=True)

    utterances = script.utterances()
    total_chars = max(1, script.char_count)
    segments: list[Segment | None] = [None] * len(utterances)

    reused = 0
    todo: list[int] = []
    for i in range(len(utterances)):
        path = _segment_path(chunks_dir, i, engine.audio_suffix)
        duration = _usable(path) if resume else 0
        if duration:
            segments[i] = Segment(index=i, path=path, duration_ms=duration)
            reused += 1
        else:
            todo.append(i)

    if reused:
        log.info(f"Resuming: {reused} of {len(utterances)} chunk(s) already synthesized in {chunks_dir}")
    if not todo:
        log.info("Progress Report: 100%")
        return [s for s in segments if s is not None]

    log.info(
        f"Synthesizing {len(todo)} chunk(s) with {engine.label}, voice '{voice}', "
        f"speed {speed}x, up to {engine.max_concurrency} at a time"
    )
    if not engine.supports_speed and abs(speed - 1.0) > 0.001:
        log.info(f"{engine.label} has no rate control; {speed}x will be applied when the audio is joined")

    semaphore = asyncio.Semaphore(max(1, engine.max_concurrency))
    done_chars = sum(len(utterances[i]) for i in range(len(utterances)) if segments[i] is not None)
    progress_lock = asyncio.Lock()

    async def worker(index: int) -> Segment:
        nonlocal done_chars
        async with semaphore:
            segment = await _synthesize_one(
                engine,
                index,
                utterances[index],
                voice,
                engine_speed,
                _segment_path(chunks_dir, index, engine.audio_suffix),
                ec.MAX_RETRIES,
                ec.RETRY_BACKOFF_SECONDS,
            )
        async with progress_lock:
            done_chars += len(utterances[index])
            # The GUI parses this exact string into its progress bar.
            log.info(f"Progress Report: {done_chars / total_chars:.0%}")
        return segment

    results = await asyncio.gather(*(worker(i) for i in todo), return_exceptions=True)

    failures: list[str] = []
    for index, result in zip(todo, results, strict=True):
        if isinstance(result, BaseException):
            failures.append(f"chunk {index}: {result}")
        else:
            segments[result.index] = result

    if failures:
        raise SynthesisError(
            f"{len(failures)} of {len(utterances)} chunk(s) could not be synthesized. "
            f"Completed chunks are kept in {chunks_dir}, so re-running resumes from there.\n  "
            + "\n  ".join(failures[:10])
        )

    return [s for s in segments if s is not None]


def text_to_mp3(text: str, mp3_path: str, voice: str = None, speed: float = None, engine: str = None):
    """Convert a string straight to audio.

    Kept as the simple entry point for callers that have text in hand and don't
    need document structure (notebooks, the GUI's preview, small scripts).
    """
    from echo.audio import assemble as asm  # noqa: PLC0415

    started = time.perf_counter()
    output_path = Path(mp3_path)
    resolved = get_engine(engine)
    resolved.check_available()

    script = build_script(
        _document_from_text(text),
        chunk_size=min(ec.CHUNK_SIZE, resolved.max_chars),
    )
    chunks_dir = chunks_dir_for(output_path)

    segments = asyncio.run(
        synthesize_script(script, engine=resolved, voice=voice, speed=speed, chunks_dir=chunks_dir)
    )
    speed = ec.DEFAULT_SPEED if speed is None else speed
    asm.assemble(
        [s.path for s in segments],
        output_path,
        fmt=output_path.suffix.lstrip(".") or "mp3",
        speed=None if resolved.supports_speed else speed,
    )
    asm.cleanup(chunks_dir)
    log.info(f"{output_path} created in {(time.perf_counter() - started) / 60:.2f} minutes")
    return output_path


def _document_from_text(text: str):
    from echo.document import Document
    from echo.extractors.text import blocks_from_plain_text

    return Document(blocks=blocks_from_plain_text(text))


def available_voices(engine: str = None) -> list[str]:
    """Voice ids for one engine (or the default engine)."""
    return [v.id for v in get_engine(engine).voices()]
