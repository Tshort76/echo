"""Microsoft Edge's online neural voices, via the unofficial ``edge-tts`` client.

Still the default: nothing else needs zero setup, zero credentials and zero
model downloads. It is an unofficial endpoint though, so transient websocket 403
handshake failures happen — which is why the orchestrator retries, and why this
is now one engine among several rather than the only one.
"""

from __future__ import annotations

import logging
from pathlib import Path

import edge_tts

import echo.constants as ec
from echo.audio.engines.base import BaseEngine, EngineUnavailable, SynthOutput, VoiceInfo
from echo.document import Timing

log = logging.getLogger(__name__)


def speed_as_rate(speed: float) -> str:
    """Convert a multiplier such as 1.5 to edge-tts's '(+|-)XX%' format.

    Engine-specific, so it lives with the engine instead of in shared code.
    """
    if not 0.25 <= speed < 5:
        raise ValueError(f"Speed {speed} is out of range; edge-tts accepts 0.25x up to 5x")
    if speed < 1:
        return f"-{round((1 - speed) * 100)}%"
    return f"+{round((speed - 1) * 100)}%"


class EdgeEngine(BaseEngine):
    name = "edge"
    label = "Edge (Microsoft, free)"
    audio_suffix = ".mp3"
    max_concurrency = ec.MAX_THREADS

    def check_available(self) -> None:
        return None  # no credentials, no local model

    def voices(self) -> list[VoiceInfo]:
        """Read the cached voice catalogue shipped as ``resources/voices.csv``.

        Refresh it with ``echo.audio.voices.update_voice_cache_file()``.
        """
        path = Path(ec.VOICE_CACHE_FILE)
        if not path.exists():
            log.warning(f"Voice cache {path} is missing; falling back to the default voice only")
            return [VoiceInfo(id=ec.DEFAULT_VOICE, engine=self.name, name=ec.DEFAULT_VOICE)]

        out: list[VoiceInfo] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            # name,language,locale,gender,"tag,tag"
            if not line.strip():
                continue
            parts = line.split(",", 4)
            if len(parts) < 4:
                continue
            short_name, language, locale, gender = (p.strip() for p in parts[:4])
            tags = parts[4].strip().strip('"') if len(parts) > 4 else ""
            display = short_name.split("-")[-1].removesuffix("Neural")
            out.append(
                VoiceInfo(
                    id=short_name,
                    engine=self.name,
                    name=display or short_name,
                    language=language,
                    locale=locale,
                    gender=gender,
                    tags=tags,
                )
            )
        return out

    def default_voice(self) -> str:
        return ec.DEFAULT_VOICE

    async def synthesize(self, text: str, voice: str, speed: float, out_path: Path) -> SynthOutput:
        rate = speed_as_rate(speed)
        communicate = edge_tts.Communicate(text, voice, rate=rate)

        timings: list[Timing] = []
        wrote_audio = False
        with open(out_path, "wb") as fp:
            async for chunk in communicate.stream():
                match chunk["type"]:
                    case "audio":
                        fp.write(chunk["data"])
                        wrote_audio = True
                    case "WordBoundary" | "SentenceBoundary":
                        # edge-tts reports 100-nanosecond ticks.
                        start = int(chunk["offset"] / 10_000)
                        timings.append(
                            Timing(
                                start_ms=start,
                                end_ms=start + int(chunk["duration"] / 10_000),
                                text=chunk.get("text", ""),
                            )
                        )

        if not wrote_audio:
            raise EngineUnavailable(
                "edge-tts returned no audio. The unofficial endpoint sometimes rejects "
                "requests (websocket 403); retrying usually clears it."
            )
        return SynthOutput(path=out_path, timings=timings)


async def list_live_voices() -> list[dict]:
    """Query the service for its current voice list (used to refresh the cache)."""
    return await edge_tts.list_voices()


