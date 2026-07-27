"""What the user chose to narrate, and how to describe it.

The pipeline reads a file, but a file path is a poor description of *where the text
came from*: "pg2680_meditations.epub" and a temp-directory research report tell the
user nothing. So the input field shows a human description while the real path
travels separately.

This also fixes a naming problem. Everything downstream — the audio filename, the
metadata title — used to be derived from the input filename. Deep Research has no
filename, and a Gutenberg download's is an artefact of the cache. Hence an explicit
:attr:`SourceSelection.name`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

FILE = "file"
GUTENBERG = "gutenberg"
RESEARCH = "research"


@dataclass(slots=True)
class SourceSelection:
    """One chosen input, ready for both the pipeline and the UI."""

    kind: str
    #: The file the pipeline actually reads.
    path: Path
    #: Drives the output filename and the default metadata title.
    name: str
    #: What the read-only input field shows.
    display: str
    #: title / author / image_path, merged *under* anything typed in settings.
    meta: dict = field(default_factory=dict)

    @classmethod
    def from_file(cls, path: str | Path) -> SourceSelection:
        path = Path(path)
        return cls(kind=FILE, path=path, name=path.stem, display=str(path))

    @classmethod
    def from_gutenberg(cls, downloaded, name: str = None, language: str = "") -> SourceSelection:
        """Describe a Project Gutenberg download."""
        book = downloaded.book
        bits = [f'Gutenberg #{book.id} · "{book.title}"']
        if book.author and book.author != "Unknown":
            bits.append(f"by {book.author}")
        detail = ", ".join(p for p in (language, (downloaded.fmt or "").upper()) if p)
        display = " ".join(bits) + (f" · {detail}" if detail else "")
        return cls(
            kind=GUTENBERG,
            path=Path(downloaded.path),
            name=(name or "").strip() or slugify(book.title),
            display=display,
            meta=downloaded.as_meta(),
        )

    @classmethod
    def from_research(cls, result) -> SourceSelection:
        """Describe a Deep Research run by the question that was asked."""
        topic = " ".join((result.topic or "").split())
        if len(topic) > 160:
            topic = topic[:159].rstrip() + "…"
        return cls(
            kind=RESEARCH,
            path=Path(result.path),
            name=result.name,
            display=f"Deep Research ({result.agent}) · {topic}",
            meta=result.as_meta(),
        )


_NON_WORD = re.compile(r"[^a-z0-9]+")
_STOPWORDS = {
    "the", "a", "an", "of", "and", "or", "on", "in", "to", "for", "is", "are",
    "its", "it", "as", "at", "by", "from", "that", "this", "with", "was", "were",
}


def slugify(text: str, words: int = 5, limit: int = 60) -> str:
    """A filename-safe name from free text — used to pre-fill the name field.

    Keeps the first few meaningful words so a topic like "the history of the marine
    chronometer" suggests ``history_marine_chronometer`` rather than a truncation.
    """
    tokens = [t for t in _NON_WORD.split((text or "").lower()) if t]
    meaningful = [t for t in tokens if t not in _STOPWORDS] or tokens
    slug = "_".join(meaningful[:words])[:limit].strip("_")
    return slug or "research"
