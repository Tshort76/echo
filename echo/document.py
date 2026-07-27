"""The data model that flows between pipeline stages.

Before this module, ``convert_to_text()`` returned a bare ``str``, which cannot
carry chapter boundaries, heading levels, "don't read this table", or page
provenance. Everything downstream that needs structure -- M4B chapter marks,
chapter-aware chunking, skip lists, synced transcripts -- depends on these types.

Two stages, two shapes:

    Extractor  -> Document   what the file says, structurally
    Normalizer -> Script     what the narrator should say, in order

Both are plain dataclasses: cheap to build, trivial to compare in tests, and
free of any dependency on a parser or a TTS engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class BlockKind(str, Enum):
    """What a run of text *is*, as reported by the extractor.

    The point of naming these is that the pipeline no longer has to guess from
    line lengths, and callers can decide per-kind whether something is spoken.
    """

    HEADING = "heading"
    PARAGRAPH = "paragraph"
    QUOTE = "quote"
    LIST = "list"
    TABLE = "table"
    FIGURE = "figure"
    CODE = "code"
    FOOTNOTE = "footnote"
    PAGE_ARTIFACT = "page_artifact"  # running headers/footers, page numbers


#: Kinds that are read aloud by default. Everything else is carried through the
#: Document (so ``--save`` text output and future features can see it) but
#: skipped when the Script is built.
SPOKEN_KINDS: frozenset[BlockKind] = frozenset(
    {BlockKind.HEADING, BlockKind.PARAGRAPH, BlockKind.QUOTE, BlockKind.LIST}
)


@dataclass(slots=True)
class Block:
    """One structural unit of the source document."""

    kind: BlockKind
    text: str
    #: Heading depth (1 = top level). Zero for non-headings.
    level: int = 0
    #: 1-indexed source page, when the extractor knows it.
    page: int | None = None

    @property
    def is_spoken(self) -> bool:
        return self.kind in SPOKEN_KINDS and bool(self.text.strip())


@dataclass(slots=True)
class Document:
    """A parsed source file, structure intact and nothing thrown away yet."""

    blocks: list[Block] = field(default_factory=list)
    title: str | None = None
    author: str | None = None
    source_path: Path | None = None
    #: Free-form notes from the extractor (which backend ran, OCR pages, ...).
    provenance: dict = field(default_factory=dict)

    def spoken(self) -> list[Block]:
        return [b for b in self.blocks if b.is_spoken]

    def as_text(self) -> str:
        """Flatten to plain text -- what ``--save`` writes, and the fallback for
        any consumer that genuinely only wants a string."""
        parts: list[str] = []
        for b in self.blocks:
            if not b.is_spoken:
                continue
            parts.append(b.text.strip())
        return "\n\n".join(p for p in parts if p)

    @property
    def char_count(self) -> int:
        return sum(len(b.text) for b in self.blocks if b.is_spoken)


@dataclass(slots=True)
class Utterance:
    """One synthesis request: a chunk of text small enough for the engine."""

    text: str
    #: Overrides the run's default voice when set (per-chapter or per-speaker).
    voice: str | None = None

    def __len__(self) -> int:
        return len(self.text)


@dataclass(slots=True)
class Chapter:
    """A titled span of utterances, which becomes one M4B chapter mark."""

    title: str
    utterances: list[Utterance] = field(default_factory=list)

    @property
    def char_count(self) -> int:
        return sum(len(u) for u in self.utterances)


@dataclass(slots=True)
class Script:
    """The narration plan: ordered chapters of engine-sized utterances."""

    chapters: list[Chapter] = field(default_factory=list)
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
