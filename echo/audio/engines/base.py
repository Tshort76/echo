"""The ``SpeechEngine`` seam.

Before this, ``tts.py`` *was* edge-tts: its rate string format, its voice JSON
shape and its websocket failure modes all leaked into shared code. One narrow
protocol fixes that — list voices, synthesize one utterance to one file, report
what you know about timing — and each engine keeps its quirks to itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from echo.document import Timing


@dataclass(frozen=True, slots=True)
class VoiceInfo:
    """One selectable voice, in a shape the GUI dropdown can group and filter."""

    id: str
    engine: str
    #: Display name, e.g. "Sonia" or "Emma (British)".
    name: str
    #: ISO language code, e.g. "en".
    language: str = ""
    #: Region/locale hint, e.g. "GB".
    locale: str = ""
    #: "Female", "Male", or "" when the provider does not say.
    gender: str = ""
    #: Free-form descriptors ("Friendly, Positive", "Upbeat").
    tags: str = ""

    @property
    def label(self) -> str:
        bits = [self.name]
        if self.locale:
            bits.append(f"({self.locale})")
        if self.gender:
            bits.append(f"· {self.gender}")
        return " ".join(bits)


@dataclass(slots=True)
class SynthOutput:
    """What an engine produced for one utterance."""

    path: Path
    duration_ms: int = 0
    timings: list[Timing] = field(default_factory=list)


class EngineUnavailable(RuntimeError):
    """Raised when an engine's dependencies or credentials are missing.

    Carries an actionable message: what to install, or which variable to set.
    """


@runtime_checkable
class SpeechEngine(Protocol):
    #: Registry key, e.g. "edge".
    name: str
    #: Human-readable name for the UI.
    label: str
    #: Container the engine writes, e.g. ".mp3" or ".wav". All chunks in a run
    #: share it, so the assembler can concatenate without transcoding.
    audio_suffix: str
    #: How many utterances this engine can synthesize at once. Network engines
    #: parallelize happily; a local model on one GPU does not.
    max_concurrency: int
    #: Largest utterance the engine accepts. Cloud TTS caps requests at 5,000
    #: bytes, well under echo's default chunk size, so chunking has to ask.
    max_chars: int
    #: Whether the engine can apply a playback-rate multiplier itself. When it
    #: cannot, the assembler applies it with ffmpeg's atempo filter instead of
    #: the engine silently ignoring the setting.
    supports_speed: bool

    def check_available(self) -> None:
        """Raise :class:`EngineUnavailable` with a fix-it message, or return."""
        ...

    def voices(self) -> list[VoiceInfo]: ...

    def default_voice(self) -> str: ...

    async def synthesize(self, text: str, voice: str, speed: float, out_path: Path) -> SynthOutput: ...


class BaseEngine:
    """Shared defaults so each engine only implements what differs."""

    name = "base"
    label = "Base"
    audio_suffix = ".mp3"
    max_concurrency = 4
    max_chars = 8000
    supports_speed = True

    def check_available(self) -> None:
        return None

    def voices(self) -> list[VoiceInfo]:
        return []

    def default_voice(self) -> str:
        voices = self.voices()
        if not voices:
            raise EngineUnavailable(f"{self.label} reports no available voices")
        return voices[0].id

    def is_available(self) -> tuple[bool, str]:
        """Convenience for UIs: ``(ok, reason)`` instead of an exception."""
        try:
            self.check_available()
            return True, ""
        except Exception as ex:
            return False, str(ex)

    async def synthesize(self, text: str, voice: str, speed: float, out_path: Path) -> SynthOutput:
        raise NotImplementedError
