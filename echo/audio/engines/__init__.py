"""Engine registry.

Adding an engine is a module plus one line in :data:`_ENGINES` — no changes to
the pipeline, the CLI or the GUI. Engines are constructed lazily so that
importing this package never pulls in a heavy optional dependency (mlx, the
Google SDKs) or touches the network.
"""

from __future__ import annotations

import logging
from typing import Callable

import echo.constants as ec
from echo.audio.engines.base import (
    BaseEngine,
    EngineUnavailable,
    SpeechEngine,
    SynthOutput,
    VoiceInfo,
)

log = logging.getLogger(__name__)

__all__ = [
    "BaseEngine",
    "EngineUnavailable",
    "SpeechEngine",
    "SynthOutput",
    "VoiceInfo",
    "get_engine",
    "engine_names",
    "available_engines",
    "all_voices",
]


def _edge() -> SpeechEngine:
    from echo.audio.engines.edge import EdgeEngine

    return EdgeEngine()


def _gemini() -> SpeechEngine:
    from echo.audio.engines.google import GeminiEngine

    return GeminiEngine()


def _google_cloud() -> SpeechEngine:
    from echo.audio.engines.google import GoogleCloudEngine

    return GoogleCloudEngine()


def _mlx() -> SpeechEngine:
    from echo.audio.engines.mlx import MlxEngine

    return MlxEngine()


_ENGINES: dict[str, Callable[[], SpeechEngine]] = {
    "edge": _edge,
    "gemini": _gemini,
    "google-cloud": _google_cloud,
    "mlx": _mlx,
}

#: Friendly aliases, so `--engine google` and `--engine kokoro` do the obvious thing.
_ALIASES = {
    "google": "google-cloud",
    "cloud": "google-cloud",
    "gcp": "google-cloud",
    "local": "mlx",
    "kokoro": "mlx",
    "mlx-audio": "mlx",
    "edge-tts": "edge",
}

_cache: dict[str, SpeechEngine] = {}


def engine_names() -> list[str]:
    return list(_ENGINES)


def get_engine(name: str = None) -> SpeechEngine:
    """Resolve an engine by name (or alias), constructing it once per process."""
    key = (name or ec.DEFAULT_ENGINE or "edge").strip().lower()
    key = _ALIASES.get(key, key)
    if key not in _ENGINES:
        raise ValueError(f"Unknown engine '{name}'. Choose from: {', '.join(_ENGINES)}")
    if key not in _cache:
        _cache[key] = _ENGINES[key]()
    return _cache[key]


def available_engines() -> list[tuple[SpeechEngine, bool, str]]:
    """Every engine with whether it can run right now, and why not if it can't.

    Used by the GUI to grey out engines that need setup instead of failing at
    conversion time.
    """
    out = []
    for name in _ENGINES:
        try:
            engine = get_engine(name)
        except Exception as ex:  # a broken optional import shouldn't hide the rest
            log.debug(f"Engine {name} could not be constructed: {ex}")
            continue
        ok, reason = engine.is_available()
        out.append((engine, ok, reason))
    return out


def all_voices(only_available: bool = True) -> list[VoiceInfo]:
    """Voices across every engine, for a grouped picker."""
    out: list[VoiceInfo] = []
    for engine, ok, _reason in available_engines():
        if only_available and not ok:
            continue
        try:
            out.extend(engine.voices())
        except Exception as ex:
            log.debug(f"Could not list voices for {engine.name}: {ex}")
    return out
