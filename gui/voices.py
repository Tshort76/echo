"""Voice and engine lists for the GUI dropdowns.

Thin adapter over :mod:`echo.audio.engines`: the backend owns what a voice is and
which engines can run, and this module only adds display strings and filtering.
Listing is lazy and never touches the network — an engine that needs credentials
reports itself unavailable instead of failing when a conversion starts.
"""

from __future__ import annotations

from echo.audio.engines import VoiceInfo, available_engines, get_engine

__all__ = [
    "VoiceInfo",
    "EngineChoice",
    "engine_choices",
    "load_voices",
    "languages",
    "filter_voices",
    "display",
]


class EngineChoice:
    """One row in the engine dropdown."""

    __slots__ = ("name", "label", "available", "reason", "audio_suffix")

    def __init__(self, name: str, label: str, available: bool, reason: str, audio_suffix: str):
        self.name = name
        self.label = label
        self.available = available
        self.reason = reason
        self.audio_suffix = audio_suffix

    @property
    def display(self) -> str:
        return self.label if self.available else f"{self.label} — needs setup"


def engine_choices() -> list[EngineChoice]:
    """Every engine, ready ones first, each with why it isn't usable if it isn't."""
    choices = [
        EngineChoice(engine.name, engine.label, ok, reason, engine.audio_suffix)
        for engine, ok, reason in available_engines()
    ]
    choices.sort(key=lambda c: (not c.available, c.label))
    return choices


def load_voices(engine_name: str | None = None) -> list[VoiceInfo]:
    """Voices for one engine, sorted for display.

    Returns an empty list rather than raising if the engine cannot enumerate
    them, so the UI can fall back to free-text voice entry.
    """
    try:
        voices = get_engine(engine_name).voices()
    except Exception:
        return []
    return sorted(voices, key=lambda v: (v.language, v.locale, v.name.lower()))


def languages(voices: list[VoiceInfo]) -> list[str]:
    """Unique language codes present in ``voices``, sorted."""
    return sorted({v.language for v in voices if v.language})


def filter_voices(
    voices: list[VoiceInfo],
    language: str | None = None,
    gender: str | None = None,
) -> list[VoiceInfo]:
    """Subset of ``voices`` matching language and gender; empty criteria mean "any"."""
    result = voices
    if language:
        result = [v for v in result if v.language == language]
    if gender:
        result = [v for v in result if v.gender.lower() == gender.lower()]
    return result


def display(voice: VoiceInfo) -> str:
    """Label for the voice combo box."""
    parts = [voice.name or voice.id]
    if voice.locale:
        parts.append(f"({voice.locale})")
    if voice.gender:
        parts.append(f"— {voice.gender}")
    if voice.tags:
        parts.append(f"· {voice.tags}")
    return " ".join(parts)
