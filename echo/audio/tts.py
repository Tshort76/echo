"""Drive a :class:`~echo.script.Script` through a speech engine.

What changed here, beyond becoming engine-agnostic:

* **Retry.** Every engine fails transiently — edge-tts's unofficial endpoint
  returns websocket 403s, cloud engines rate-limit. Each utterance gets several
  attempts with backoff.
* **Resume.** Chunk files are named by position *and* by a digest of what they
  say (engine, voice, speed, text), and kept until assembly succeeds, so a
  re-run skips everything already on disk — and a chunk directory reused for
  different text can never splice the old audio into the new file.
* **No partial success.** ``asyncio.gather`` used to run without
  ``return_exceptions``, so one failure anywhere aborted the run; now every
  utterance is attempted and the summary names what failed, rather than a
  half-finished book being silently assembled.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from pathlib import Path
from typing import Callable

from echo import defaults
from echo.audio.engines import EngineUnavailable, SpeechEngine, get_engine
from echo.errors import SynthesisError
from echo.script import Script, Segment, Utterance

log = logging.getLogger(__name__)

#: ``on_progress(done, total)``, in utterances. Called from the event loop thread.
ProgressCallback = Callable[[int, int], None]


def chunks_dir_for(output_path: Path) -> Path:
    """The app's resume directory convention: ``<name>_chunks`` beside the output."""
    output_path = Path(output_path)
    return output_path.parent / f"{output_path.stem}_chunks"


def _segment_path(chunks_dir: Path, index: int, engine: SpeechEngine, voice: str, speed: float, text: str) -> Path:
    key = "\x1f".join((engine.name, voice, f"{speed:.4f}", text))
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]
    return chunks_dir / f"chunk_{digest}_{index:05d}{engine.audio_suffix}"


def _report(on_progress: ProgressCallback | None, done: int, total: int) -> None:
    """A broken progress callback must not fail the utterance it reports on."""
    if on_progress is None:
        return
    try:
        on_progress(done, total)
    except Exception:
        log.exception("on_progress callback raised; ignoring")


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
    max_retries: int = None,
    retry_backoff: float = None,
    on_progress: ProgressCallback = None,
) -> list[Segment]:
    """Synthesize every utterance in ``script``, returning segments in order.

    ``on_progress(done, total)`` is called once up front and after each utterance.
    """
    engine = engine or get_engine()
    engine.check_available()
    voice = voice or engine.default_voice()
    # Optional on the protocol, so a caller's own SpeechEngine need not define it.
    check_voice = getattr(engine, "check_voice", None)
    if check_voice:
        for v in {voice} | {u.voice for u in script.utterances() if u.voice}:
            check_voice(v)
    speed = defaults.SPEED if speed is None else speed
    engine_speed = speed if engine.supports_speed else 1.0
    max_retries = defaults.MAX_RETRIES if max_retries is None else max(1, max_retries)
    retry_backoff = defaults.RETRY_BACKOFF_SECONDS if retry_backoff is None else retry_backoff

    chunks_dir = Path(chunks_dir)
    chunks_dir.mkdir(parents=True, exist_ok=True)

    utterances = script.utterances()
    total_chars = max(1, script.char_count)
    segments: list[Segment | None] = [None] * len(utterances)
    paths = [
        _segment_path(chunks_dir, i, engine, u.voice or voice, engine_speed, u.text) for i, u in enumerate(utterances)
    ]

    reused = 0
    todo: list[int] = []
    for i in range(len(utterances)):
        path = paths[i]
        duration = _usable(path) if resume else 0
        if duration:
            segments[i] = Segment(index=i, path=path, duration_ms=duration)
            reused += 1
        else:
            todo.append(i)

    if reused:
        log.info(f"Resuming: {reused} of {len(utterances)} chunk(s) already synthesized in {chunks_dir}")
    done = reused
    _report(on_progress, done, len(utterances))
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
        nonlocal done_chars, done
        async with semaphore:
            segment = await _synthesize_one(
                engine,
                index,
                utterances[index],
                voice,
                engine_speed,
                paths[index],
                max_retries,
                retry_backoff,
            )
        async with progress_lock:
            done_chars += len(utterances[index])
            done += 1
            # The GUI parses this exact string into its progress bar.
            log.info(f"Progress Report: {done_chars / total_chars:.0%}")
            _report(on_progress, done, len(utterances))
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
            + (f"Completed chunks are kept in {chunks_dir}, so re-running resumes from there." if resume else "")
            + "\n  "
            + "\n  ".join(failures[:10])
        )

    return [s for s in segments if s is not None]
