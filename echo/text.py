"""Splitting text into engine-sized utterances."""

from __future__ import annotations

import re

from echo import defaults

_EMPTY_LINES = re.compile(r"\n\s*\n")
_REDUNDANT_SPACES = re.compile(r" +")
_SENTENCES = re.compile(r"(?<=[.!?])\s+")


def split_text(text: str, max_chars: int = None) -> list[str]:
    """Split text into chunks of at most ``max_chars``.

    Prefers paragraph, then sentence, then word boundaries, so chunk seams land
    where speech naturally pauses. A single sentence longer than the limit is cut
    at word boundaries rather than passed through — Cloud TTS rejects an
    over-long request outright.
    """
    max_chars = max_chars or defaults.CHUNK_SIZE
    text = _EMPTY_LINES.sub("\n\n", text)
    text = _REDUNDANT_SPACES.sub(" ", text)

    chunks: list[str] = []
    current_chunk = ""

    for para in text.split("\n\n"):
        para = para.strip()
        if not para:
            continue

        if len(current_chunk) + len(para) + 2 > max_chars and current_chunk:
            chunks.append(current_chunk.strip())
            current_chunk = ""

        if len(para) > max_chars:
            for sentence in _SENTENCES.split(para):
                for piece in _fit(sentence, max_chars):
                    if len(current_chunk) + len(piece) + 1 > max_chars and current_chunk:
                        chunks.append(current_chunk.strip())
                        current_chunk = ""
                    current_chunk += piece + " "
        else:
            current_chunk += para + "\n\n"

    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    return chunks


def _fit(sentence: str, max_chars: int) -> list[str]:
    """Cut one over-long sentence at word boundaries (or mid-word, as a last resort)."""
    if len(sentence) <= max_chars:
        return [sentence]
    pieces: list[str] = []
    current = ""
    for word in sentence.split(" "):
        while len(word) > max_chars:
            if current:
                pieces.append(current)
                current = ""
            pieces.append(word[:max_chars])
            word = word[max_chars:]
        if current and len(current) + 1 + len(word) > max_chars:
            pieces.append(current)
            current = ""
        current = f"{current} {word}" if current else word
    if current:
        pieces.append(current)
    return pieces
