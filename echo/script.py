"""The narration plan and what synthesis produces from it.

    Script    ordered chapters of engine-sized utterances  -> what gets spoken
    Segment   one synthesized utterance on disk            -> what came back

Plain dataclasses with no dependency on a parser or an engine. The app's
extraction model (``echo_app.document``) builds a Script; the library only
ever sees the Script.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class Utterance:
    """One synthesis request: a chunk of text small enough for the engine."""

    text: str
    #: Overrides the run's default voice when set (per-chapter or per-speaker).
    voice: str | None = None

    def __len__(self) -> int:
        return len(self.text)


@dataclass(slots=True)
class ScriptChapter:
    """A titled span of utterances, which becomes one M4B chapter mark."""

    title: str
    utterances: list[Utterance] = field(default_factory=list)

    @property
    def char_count(self) -> int:
        return sum(len(u) for u in self.utterances)


@dataclass(slots=True)
class Script:
    """The narration plan: ordered chapters of engine-sized utterances."""

    chapters: list[ScriptChapter] = field(default_factory=list)
    title: str | None = None
    author: str | None = None

    def utterances(self) -> list[Utterance]:
        """Every utterance in reading order -- the unit of synthesis."""
        return [u for ch in self.chapters for u in ch.utterances]

    def chapter_of(self, utterance_index: int) -> int:
        """Index of the chapter containing the nth utterance."""
        seen = 0
        for i, ch in enumerate(self.chapters):
            seen += len(ch.utterances)
            if utterance_index < seen:
                return i
        raise IndexError(f"utterance {utterance_index} is past the end of the script")

    @property
    def char_count(self) -> int:
        return sum(ch.char_count for ch in self.chapters)

    def as_text(self) -> str:
        return "\n\n".join(u.text for u in self.utterances())


@dataclass(slots=True)
class Timing:
    """A word or sentence boundary reported by an engine, in milliseconds
    relative to the start of its own audio segment."""

    start_ms: int
    end_ms: int
    text: str


@dataclass(slots=True)
class Segment:
    """One synthesized utterance on disk, plus whatever timings came with it."""

    index: int
    path: Path
    duration_ms: int
    timings: list[Timing] = field(default_factory=list)
