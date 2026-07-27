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
from statistics import median
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
#: A section must also be under this fraction of the document's typical section
#: length to count as a stub rather than a genuinely short chapter.
_STUB_FRACTION = 0.2
#: Seconds to wait when probing a local model server for liveness. Short, because
#: this runs while a UI is waiting for the dropdown to populate.
_PROBE_TIMEOUT = 2.0
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


class NormalizerUnavailable(RuntimeError):
    """Raised when a normalizer's model or credentials are missing.

    Mirrors :class:`~echo.audio.engines.base.EngineUnavailable`: if you explicitly
    asked for LLM normalization, a silent fall back to the rules pass is the wrong
    answer. The guardrails still degrade gracefully *mid-run*; this is about
    catching an unusable choice before a conversion starts.
    """


class Normalizer(Protocol):
    """Turns a chunk of already rules-normalized text into narration-ready text."""

    #: Registry key: "off", "local" or "gemini".
    name: str
    #: Human-readable name for a UI.
    label: str

    def check_available(self) -> None:
        """Raise :class:`NormalizerUnavailable` with a fix-it message, or return."""
        ...

    def normalize(self, text: str) -> str: ...


class _BaseNormalizer:
    """Shared availability plumbing."""

    name = "off"
    label = "Off"

    def check_available(self) -> None:
        return None

    def is_available(self) -> tuple[bool, str]:
        """Convenience for UIs: ``(ok, reason)`` instead of an exception."""
        try:
            self.check_available()
            return True, ""
        except Exception as ex:
            return False, str(ex)


class RulesNormalizer(_BaseNormalizer):
    """The default: deterministic, no network, no surprises."""

    name = "off"
    label = "Off — deterministic rules only"

    def normalize(self, text: str) -> str:
        return text


class _GuardedNormalizer(_BaseNormalizer):
    """Shared guardrails for any model-backed normalizer.

    Rejects and falls back to the original whenever the result looks like
    anything other than the same passage, said aloud.
    """

    name = "guarded"
    label = "Guarded"

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
    label = "Local model (LM Studio / Ollama)"

    def __init__(self, base_url: str = None, model: str = None, api_key: str = None, tolerance: float = None):
        super().__init__(tolerance)
        self.base_url = (base_url or ec.LOCAL_LLM_BASE_URL).rstrip("/")
        self.model = model or ec.LOCAL_LLM_MODEL
        self.api_key = api_key or ec.LOCAL_LLM_API_KEY

    def check_available(self) -> None:
        """Probe the endpoint for liveness.

        Any HTTP response counts as reachable — a 404 on ``/models`` still means a
        server is listening, and some OpenAI-compatible servers only implement
        ``/chat/completions``. Only a failure to connect means "nothing there".
        """
        request = urllib.request.Request(
            f"{self.base_url}/models", headers={"Authorization": f"Bearer {self.api_key}"}
        )
        try:
            urllib.request.urlopen(request, timeout=_PROBE_TIMEOUT).close()
        except urllib.error.HTTPError:
            return  # something answered; good enough
        except (urllib.error.URLError, TimeoutError, OSError) as ex:
            raise NormalizerUnavailable(
                f"No local model server answered at {self.base_url}. Start LM Studio "
                f"or Ollama (and check LOCAL_LLM_BASE_URL). Details: {ex}"
            ) from ex

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
    label = "Gemini (needs GEMINI_API_KEY)"

    def __init__(self, model: str = None, api_key: str = None, tolerance: float = None):
        super().__init__(tolerance)
        self.model = model or ec.GEMINI_TEXT_MODEL
        # `is not None`, not `or`: an explicit "" means "no key", and `or` would
        # silently fall back to the environment.
        self._api_key = api_key if api_key is not None else ec.GEMINI_API_KEY
        self._client = None

    def check_available(self) -> None:
        if not self._api_key:
            raise NormalizerUnavailable(
                "Gemini normalization needs an API key. Set GEMINI_API_KEY in your "
                ".env (create one at https://aistudio.google.com/apikey)."
            )
        try:
            import google.genai  # noqa: F401, PLC0415
        except ImportError as ex:
            raise NormalizerUnavailable(
                "Gemini normalization needs `pip install google-genai`"
            ) from ex

    def _client_or_load(self):
        if self._client is None:
            self.check_available()
            from google import genai  # noqa: PLC0415

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


NORMALIZER_NAMES = ("off", "local", "gemini")


def get_normalizer(name: str = None) -> Normalizer:
    """Resolve a normalizer by name: ``off`` (default), ``local`` or ``gemini``.

    Construction never touches the network; call ``check_available()`` on the
    result to find out whether it can actually run.
    """
    name = (name or ec.NORMALIZER or "off").strip().lower()
    match name:
        case "off" | "none" | "rules" | "":
            return RulesNormalizer()
        case "local":
            return LocalLLMNormalizer()
        case "gemini":
            return GeminiNormalizer()
        case other:
            raise ValueError(f"Unknown normalizer '{other}'. Choose from: {', '.join(NORMALIZER_NAMES)}")


def available_normalizers() -> list[tuple[Normalizer, bool, str]]:
    """Every normalizer with whether it can run now, and why not if it can't.

    Used by the GUI to disable a choice that would otherwise appear to work and
    then quietly fall back to the rules pass for every chunk.
    """
    out = []
    for name in NORMALIZER_NAMES:
        try:
            normalizer = get_normalizer(name)
        except Exception as ex:  # pragma: no cover - defensive
            log.debug(f"Normalizer {name} could not be constructed: {ex}")
            continue
        ok, reason = normalizer.is_available()
        out.append((normalizer, ok, reason))
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Script assembly
# ─────────────────────────────────────────────────────────────────────────────


#: A title-page byline is marked up as a heading, but it names nobody's chapter.
#: Left alone it becomes the title of whatever follows — a single-story text ends
#: up with its whole body under "By Charlotte Perkins Gilman".
_BYLINE = re.compile(r"^\s*(by|translated by|edited by|illustrated by|adapted by)\s+\S", re.IGNORECASE)

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


def _coalesce_small_sections(
    sections: list[tuple[str | None, list[str]]],
    minimum: int,
) -> list[tuple[str | None, list[str], list[str]]]:
    """Fold sections with too little text into their neighbour.

    Real books open with a half-title, a title page and an author line, each of
    which is a heading with a handful of words under it. Left alone they become a
    run of two-second chapters before the book starts. Nothing is discarded — the
    text (and its heading) moves into the next section, or the previous one for a
    trailing fragment.

    A section has to be small in *two* senses to count as a stub: under
    ``minimum`` characters, and a small fraction of the typical section in this
    document. Judging on the absolute figure alone would flatten a genuinely short
    document — a ten-page essay with real chapters of 300 words each — into one
    chapter.
    """
    def size(runs: list[str]) -> int:
        return sum(len(r) for r in runs)

    if minimum <= 0 or len(sections) < 2:
        return [(title, [], runs) for title, runs in sections]

    typical = median([size(runs) for _title, runs in sections]) or 0
    ceiling = min(minimum, max(1.0, typical * _STUB_FRACTION))

    # A folded fragment becomes the *prelude* of the section it joins, so it is
    # spoken before that chapter's own heading — "A Book. By Someone. Chapter One."
    # rather than "Chapter One. A Book. By Someone."
    merged: list[tuple[str | None, list[str], list[str]]] = []
    carried: list[str] = []
    for title, runs in sections:
        if size(runs) + size(carried) < ceiling:
            # Keep the heading as spoken text so no words are lost.
            carried = carried + ([f"{title}."] if title else []) + runs
            continue
        merged.append((title, carried, runs))
        carried = []

    if carried:
        if merged:
            last_title, last_prelude, last_runs = merged[-1]
            merged[-1] = (last_title, last_prelude, last_runs + carried)
        else:
            merged.append((sections[0][0], [], carried))

    if len(merged) != len(sections):
        log.info(f"Folded {len(sections) - len(merged)} short section(s) into neighbouring chapters")
    return merged


def build_script(
    doc: Document,
    chunk_size: int = None,
    chapter_level: int = None,
    normalizer: Normalizer = None,
    min_chapter_chars: int = None,
) -> Script:
    """Group a Document into chapters, then into engine-sized utterances."""
    chunk_size = chunk_size or ec.CHUNK_SIZE
    chapter_level = chapter_level or ec.CHAPTER_HEADING_LEVEL
    normalizer = normalizer or RulesNormalizer()
    min_chapter_chars = ec.MIN_CHAPTER_CHARS if min_chapter_chars is None else min_chapter_chars

    # (heading, [text runs]) pairs, split at qualifying headings.
    sections: list[tuple[str | None, list[str]]] = []
    heading: str | None = None
    body: list[str] = []

    for block in doc.spoken():
        starts_chapter = (
            block.kind == BlockKind.HEADING
            and 0 < block.level <= chapter_level
            and (body or heading)
            # A byline is front matter, not a division: keep it as spoken content
            # of the section it sits in rather than letting it name a chapter.
            and not _BYLINE.match(block.text)
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
    sections = _coalesce_small_sections(sections, min_chapter_chars)

    chapters: list[Chapter] = []
    for i, (title, prelude, runs) in enumerate(sections):
        body = "\n\n".join(r for r in runs if r.strip())
        if not body.strip() and not prelude and title and _NAVIGATION_HEADINGS.match(title):
            log.debug(f"Skipping navigation section '{title}' — no spoken content")
            continue
        # Prelude (any folded front matter), then the chapter's own heading, then
        # its body, each separated by a paragraph break the engine reads as a pause.
        parts = list(prelude)
        if title:
            parts.append(f"{title}.")
        if body:
            parts.append(body)
        text = "\n\n".join(p for p in parts if p.strip())
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
