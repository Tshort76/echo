"""Load and filter the cached edge-tts voice list for the GUI dropdowns.

Reads ``resources/voices.csv`` (the same cache the backend maintains) so the UI
does not need a network round-trip to populate its voice picker.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

# Repo root is the parent of this package; the voice cache lives alongside the
# other bundled resources. Resolved this way so the GUI works regardless of the
# current working directory it happens to be launched from.
_REPO_ROOT = Path(__file__).resolve().parent.parent
VOICES_CSV = _REPO_ROOT / "resources" / "voices.csv"


@dataclass(frozen=True)
class Voice:
    """A single edge-tts voice parsed from the cache file."""

    short_name: str  # e.g. "en-GB-SoniaNeural" — the value edge-tts expects
    language: str  # e.g. "en"
    locale: str  # e.g. "GB"
    gender: str  # "Male" | "Female"
    tags: str  # comma-joined personality tags, e.g. "Friendly, Positive"

    @property
    def display(self) -> str:
        """Human-friendly label for the combo box."""
        label = f"{self.short_name}  —  {self.gender}"
        if self.tags:
            label += f" ({self.tags})"
        return label


def load_voices(csv_path: Path | None = None) -> list[Voice]:
    """Parse the voice cache into ``Voice`` records, sorted by short name.

    Returns an empty list (rather than raising) if the cache is missing, so the
    UI can degrade gracefully to a free-text voice entry.
    """
    path = Path(csv_path) if csv_path else VOICES_CSV
    if not path.exists():
        return []

    voices: list[Voice] = []
    with open(path, "r", encoding="utf-8", newline="") as fp:
        for row in csv.reader(fp):
            if len(row) < 4:
                continue
            short_name, language, locale, gender = (c.strip() for c in row[:4])
            # The tags column is a quoted, comma-separated list; csv already
            # split it into the remaining fields, so re-join and tidy spacing.
            tags = ", ".join(t.strip() for t in row[4:] if t.strip())
            voices.append(Voice(short_name, language, locale, gender, tags))

    voices.sort(key=lambda v: v.short_name.lower())
    return voices


def languages(voices: list[Voice]) -> list[str]:
    """Unique language codes present in ``voices``, sorted alphabetically."""
    return sorted({v.language for v in voices if v.language})


def filter_voices(
    voices: list[Voice],
    language: str | None = None,
    gender: str | None = None,
) -> list[Voice]:
    """Return the subset of ``voices`` matching the given language and gender.

    ``None`` (or empty string) for a criterion means "no filter".
    """
    result = voices
    if language:
        result = [v for v in result if v.language == language]
    if gender:
        result = [v for v in result if v.gender.lower() == gender.lower()]
    return result
