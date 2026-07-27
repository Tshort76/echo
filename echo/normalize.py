"""Document -> Script: decide what the narrator actually says.

Three jobs live here:

1. **Rules normalization** — the cheap, deterministic text fixes that always run
   (footnote references, dashes, page artifacts).
2. **Chapter-aware chunking** — grouping blocks into chapters at heading
   boundaries, then splitting each chapter into engine-sized utterances. This is
   what makes M4B chapter marks possible.
3. **Optional LLM normalization** — expanding abbreviations, numbers, units and
   symbols into what a narrator would say. Off by default, and heavily
   guarded: an unconstrained model rewriting 500,000 characters is a book with
   quietly invented sentences in it.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from typing import Protocol

import echo.constants as ec
from echo.document import Block, BlockKind, Chapter, Document, Script, Utterance
from echo.extractors.text import to_chunks

log = logging.getLogger(__name__)

#: A digit or two immediately after sentence punctuation is a footnote marker,
#: not part of the sentence. Deliberately narrow so "4.56" survives.
FOOTNOTE_REF = re.compile(r"([^\d][;,.?!)])\d{1,2}(\s)")
_PAGE_NUMBER_ONLY = re.compile(r"^[\s\divxlcIVXLC.\-—–]+$")
_MULTI_SPACE = re.compile(r"[ \t]{2,}")
_ELLIPSIS = re.compile(r"\.{3,}|(?:\.\s){2,}\.")
_DASH_RUN = re.compile(r"\s*(?:—|–|--+)\s*")


# ─────────────────────────────────────────────────────────────────────────────
# Rules normalization
# ─────────────────────────────────────────────────────────────────────────────


def strip_footnote_refs(text: str) -> str:
    return FOOTNOTE_REF.sub(lambda m: m.group(1) + m.group(2), text)


def normalize_for_speech(text: str) -> str:
    """Deterministic fixes that make text read better aloud."""
    text = strip_footnote_refs(text)
    text = _ELLIPSIS.sub("…", text)
    # A dash run is a spoken pause; a comma gives engines the prosody for it.
    text = _DASH_RUN.sub(", ", text)
    text = text.replace("­", "").replace("\xa0", " ")
    text = text.replace("“", '"').replace("”", '"').replace("’", "'").replace("‘", "'")
    text = _MULTI_SPACE.sub(" ", text)
    return text.strip()


def mark_page_artifacts(doc: Document) -> int:
    """Flag running headers/footers and page numbers as unspoken.

    Positional, not frequency-based: a candidate must be short, must appear at
    the very start or very end of its page's blocks, and must recur across
    several pages. The old approach took the most common lines anywhere in the
    text and ``str.replace``d them everywhere, which happily deleted a recurring
    line of dialogue from an entire novel.
    """
    by_page: dict[int, list[Block]] = defaultdict(list)
    for b in doc.blocks:
        if b.page is not None:
            by_page[b.page].append(b)
    if len(by_page) < 4:
        return 0

    edge_positions: Counter[tuple[str, str]] = Counter()
    for blocks in by_page.values():
        if not blocks:
            continue
        for where, block in (("head", blocks[0]), ("foot", blocks[-1])):
            key = block.text.strip()[:120]
            if key and len(key) < 120:
                edge_positions[(where, key)] += 1

    threshold = max(3, len(by_page) // 4)
    recurring = {key for (_where, key), count in edge_positions.items() if count >= threshold}

    marked = 0
    for blocks in by_page.values():
        if not blocks:
            continue
        for block in {id(blocks[0]): blocks[0], id(blocks[-1]): blocks[-1]}.values():
            stripped = block.text.strip()
            if block.kind == BlockKind.PAGE_ARTIFACT:
                continue
            if stripped[:120] in recurring or _PAGE_NUMBER_ONLY.match(stripped):
                block.kind = BlockKind.PAGE_ARTIFACT
                marked += 1

    if marked:
        log.info(f"Marked {marked} running header/footer block(s) as unspoken")
    return marked


def apply_rules(doc: Document) -> Document:
    """Run the deterministic pass over a Document, in place."""
    mark_page_artifacts(doc)
    for block in doc.blocks:
        if block.is_spoken:
            block.text = normalize_for_speech(block.text)
    doc.blocks = [b for b in doc.blocks if b.kind != BlockKind.PAGE_ARTIFACT or b.text.strip()]
    return doc


# ─────────────────────────────────────────────────────────────────────────────
# Optional LLM normalization
# ─────────────────────────────────────────────────────────────────────────────

_PROMPT = """You prepare text for an audiobook narrator. Rewrite the passage so it \
reads correctly ALOUD, changing as little as possible.

Do:
- Expand abbreviations, acronyms, symbols and units into spoken words \
(e.g. "Dr." -> "Doctor", "§4.2" -> "section four point two", "12kg" -> "twelve kilograms").
- Write numbers, dates and times the way a narrator would say them.
- Remove artifacts that cannot be spoken: citation markers, stray page numbers, \
"see Figure 3" cross-references, URLs.

Do NOT:
- Summarize, shorten, expand, explain, translate or improve the prose.
- Add or remove sentences. Keep every sentence of the original, in order.
- Add commentary, notes, or a preamble.

Return ONLY the rewritten passage."""

_REFUSAL_HINTS = (
    "i cannot",
    "i can't",
    "as an ai",
    "here is the rewritten",
    "here's the rewritten",
    "sure,",
)


class Normalizer(Protocol):
    """Turns a chunk of already rules-normalized text into narration-ready text."""

    def normalize(self, text: str) -> str: ...


class RulesNormalizer:
    """The default: deterministic, no network, no surprises."""

    name = "off"

    def normalize(self, text: str) -> str:
        return text


class _GuardedNormalizer:
    """Shared guardrails for any model-backed normalizer.

    Rejects and falls back to the original whenever the result looks like
    anything other than the same passage, said aloud.
    """

    name = "guarded"

    def __init__(self, tolerance: float = None):
        self.tolerance = ec.NORMALIZER_LENGTH_TOLERANCE if tolerance is None else tolerance
        self.rejected = 0
        self.accepted = 0

    def _call_model(self, text: str) -> str:  # pragma: no cover - overridden
        raise NotImplementedError

    def _reject(self, reason: str, text: str) -> str:
        self.rejected += 1
        log.warning(f"LLM normalization rejected ({reason}); using the original text")
        return text

    def normalize(self, text: str) -> str:
        if not text.strip():
            return text
        try:
            out = (self._call_model(text) or "").strip()
        except Exception as ex:
            return self._reject(f"{type(ex).__name__}: {str(ex)[:120]}", text)

        if not out:
            return self._reject("empty response", text)

        low = out[:80].lower()
        if any(low.startswith(hint) for hint in _REFUSAL_HINTS):
            return self._reject("model added a preamble or refused", text)

        drift = abs(len(out) - len(text)) / max(1, len(text))
        if drift > self.tolerance:
            return self._reject(f"length drifted {drift:.0%} (limit {self.tolerance:.0%})", text)

        self.accepted += 1
        return out


class LocalLLMNormalizer(_GuardedNormalizer):
    """Talks to any OpenAI-compatible endpoint — LM Studio, Ollama, vLLM.

    Uses ``urllib`` rather than an SDK so the optional feature adds no
    dependency to the base install.
    """

    name = "local"

    def __init__(self, base_url: str = None, model: str = None, api_key: str = None, tolerance: float = None):
        super().__init__(tolerance)
        self.base_url = (base_url or ec.LOCAL_LLM_BASE_URL).rstrip("/")
        self.model = model or ec.LOCAL_LLM_MODEL
        self.api_key = api_key or ec.LOCAL_LLM_API_KEY

    def _call_model(self, text: str) -> str:
        payload = json.dumps(
            {
                "model": self.model,
                "temperature": 0,
                "messages": [
                    {"role": "system", "content": _PROMPT},
                    {"role": "user", "content": text},
                ],
            }
        ).encode()
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"},
        )
        with urllib.request.urlopen(request, timeout=300) as response:
            body = json.loads(response.read())
        return body["choices"][0]["message"]["content"]


class GeminiNormalizer(_GuardedNormalizer):
    """Uses the Gemini API via the current ``google-genai`` SDK."""

    name = "gemini"

    def __init__(self, model: str = None, api_key: str = None, tolerance: float = None):
        super().__init__(tolerance)
        self.model = model or ec.GEMINI_TEXT_MODEL
        self._api_key = api_key or ec.GEMINI_API_KEY
        if not self._api_key:
            raise ValueError("GEMINI_API_KEY is not set, so the gemini normalizer cannot run")
        self._client = None

    def _client_or_load(self):
        if self._client is None:
            try:
                from google import genai  # noqa: PLC0415
            except ImportError as ex:
                raise ImportError("The gemini normalizer needs `pip install google-genai`") from ex
            self._client = genai.Client(api_key=self._api_key)
        return self._client

    def _call_model(self, text: str) -> str:
        from google.genai import types  # noqa: PLC0415

        response = self._client_or_load().models.generate_content(
            model=self.model,
            contents=text,
            config=types.GenerateContentConfig(system_instruction=_PROMPT, temperature=0),
        )
        return response.text


def get_normalizer(name: str = None) -> Normalizer:
    """Resolve a normalizer by name: ``off`` (default), ``local`` or ``gemini``."""
    name = (name or ec.NORMALIZER or "off").strip().lower()
    match name:
        case "off" | "none" | "rules" | "":
            return RulesNormalizer()
        case "local":
            return LocalLLMNormalizer()
        case "gemini":
            return GeminiNormalizer()
        case other:
            raise ValueError(f"Unknown normalizer '{other}'. Choose from: off, local, gemini")


# ─────────────────────────────────────────────────────────────────────────────
# Script assembly
# ─────────────────────────────────────────────────────────────────────────────


#: Headings that introduce navigation rather than prose. When such a section has
#: no spoken body (its content was a table of contents, say), announcing the
#: title alone is just noise in the audio.
_NAVIGATION_HEADINGS = re.compile(
    r"^\s*(table of )?(contents|index|colophon|bibliography|illustrations|"
    r"list of (figures|tables|illustrations))\s*$",
    re.IGNORECASE,
)


def _chapter_title(index: int, heading: str | None, fallback: str | None) -> str:
    if heading:
        return heading
    if index == 0 and fallback:
        return fallback
    return f"Chapter {index + 1}"


def build_script(
    doc: Document,
    chunk_size: int = None,
    chapter_level: int = None,
    normalizer: Normalizer = None,
) -> Script:
    """Group a Document into chapters, then into engine-sized utterances."""
    chunk_size = chunk_size or ec.CHUNK_SIZE
    chapter_level = chapter_level or ec.CHAPTER_HEADING_LEVEL
    normalizer = normalizer or RulesNormalizer()

    # (heading, [text runs]) pairs, split at qualifying headings.
    sections: list[tuple[str | None, list[str]]] = []
    heading: str | None = None
    body: list[str] = []

    for block in doc.spoken():
        starts_chapter = (
            block.kind == BlockKind.HEADING and 0 < block.level <= chapter_level and (body or heading)
        )
        if starts_chapter:
            sections.append((heading, body))
            heading, body = block.text, []
            continue
        if block.kind == BlockKind.HEADING and not body and heading is None:
            heading = block.text
            continue
        body.append(block.text)

    sections.append((heading, body))

    chapters: list[Chapter] = []
    for i, (title, runs) in enumerate(sections):
        text = "\n\n".join(r for r in runs if r.strip())
        if not text.strip() and title and _NAVIGATION_HEADINGS.match(title):
            log.debug(f"Skipping navigation section '{title}' — no spoken content")
            continue
        if title:
            # Speak the chapter title, then pause before the body.
            text = f"{title}.\n\n{text}" if text else f"{title}."
        if not text.strip():
            continue
        pieces = [normalizer.normalize(c) for c in to_chunks(text, chunk_size)]
        utterances = [Utterance(text=p) for p in pieces if p.strip()]
        if utterances:
            chapters.append(Chapter(title=_chapter_title(i, title, doc.title), utterances=utterances))

    if not chapters:
        raise ValueError("Nothing to narrate: the document produced no spoken text")

    script = Script(chapters=chapters, title=doc.title, author=doc.author)
    log.info(
        f"Script: {len(script.chapters)} chapter(s), {len(script.utterances())} utterance(s), "
        f"{script.char_count:,} characters"
    )
    return script
