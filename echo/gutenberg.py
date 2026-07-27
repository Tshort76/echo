"""Project Gutenberg as a source of books.

Search comes from `Gutendex <https://gutendex.com>`_, a free JSON API over
Project Gutenberg's catalogue — no account, no key. Files come from
gutenberg.org itself.

Two choices worth knowing about:

* **EPUB is preferred over plain text.** Gutenberg's EPUB editions carry heading
  markup, so :mod:`echo.extractors.misc` can find real chapter boundaries.
  The plain-text edition is one long stream, which yields far coarser chapters.
* **Downloads are cached by book id**, so re-running a conversion (or trying a
  second voice) does not fetch the same book twice.

Only the standard library is used for HTTP, keeping the base install light.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

GUTENDEX_URL = "https://gutendex.com/books/"
USER_AGENT = "echo-audiobook/0.2 (+https://github.com/Tshort76/echo)"
_TIMEOUT = 60
_RETRIES = 3

#: Where downloaded books live. Outside the repo so it also works from a frozen
#: app, where the bundle directory is read-only.
CACHE_DIR = Path(os.environ.get("GUTENBERG_DIR") or (Path.home() / ".cache" / "echo" / "gutenberg"))

#: Preference order per logical format. Gutendex keys are MIME types, sometimes
#: with a charset suffix, so these are matched as prefixes.
_FORMAT_KEYS: dict[str, tuple[str, ...]] = {
    "epub": ("application/epub+zip",),
    "text": ("text/plain; charset=utf-8", "text/plain; charset=us-ascii", "text/plain"),
    "html": ("text/html",),
    "cover": ("image/jpeg", "image/png"),
}
_SUFFIXES = {"epub": ".epub", "text": ".txt", "html": ".html"}

#: Words that mean a post-comma fragment is a title or epithet, not a given name
#: ("Marcus Aurelius, Emperor of Rome" must not become "Emperor of Rome Marcus").
_NOT_A_GIVEN_NAME = {
    "of", "the", "and", "emperor", "empress", "king", "queen", "prince", "princess",
    "saint", "st", "sir", "dame", "lord", "lady", "pope", "bishop", "captain",
    "president", "dr", "mrs", "mr", "ms", "baron", "count", "countess", "duke",
    "pseud", "jr", "sr", "active", "approximately",
}


#: Ignored when judging how well a title matches the query.
_STOPWORDS = {"the", "a", "an", "of", "and", "or", "on", "in", "to", "for"}


class GutenbergError(RuntimeError):
    """Raised when the catalogue or a download cannot be reached."""


def _tokens(text: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9]+", (text or "").lower()) if t and t not in _STOPWORDS]


def _title_relevance(book: "GutenbergBook", query: str) -> int:
    """How well a book's *title* matches the query: 2 (all terms), 1 (some), 0.

    Gutendex searches titles and authors together, so a query like "art of war"
    also matches a book published by the "War Office". Requiring the query's terms
    in the *title* keeps the obvious answer on top.

    Deliberately does not reward an exact title match above a partial one: on
    Gutenberg the canonical edition usually carries a subtitle ("Frankenstein; Or,
    The Modern Prometheus"), so an exact-match tier would promote an obscure
    reprint over the edition everyone actually reads. Popularity decides instead.
    """
    wanted = _tokens(query)
    if not wanted:
        return 0
    title_tokens = set(_tokens(book.title))
    present = sum(1 for token in wanted if token in title_tokens)
    if present == len(wanted):
        return 2
    return 1 if present else 0


def normalize_author(name: str) -> str:
    """Turn Gutenberg's "Surname, Given" into "Given Surname" when that is safe.

    ``"Austen, Jane"`` -> ``"Jane Austen"``, but
    ``"Marcus Aurelius, Emperor of Rome"`` is left alone.
    """
    name = (name or "").strip()
    if name.count(",") != 1:
        return name
    surname, _, tail = name.partition(",")
    tail = tail.strip()
    tokens = tail.split()
    if not tokens or len(tokens) > 2:
        return name
    if any(t.strip(".").lower() in _NOT_A_GIVEN_NAME for t in tokens):
        return name
    return f"{tail} {surname.strip()}".strip()


@dataclass(frozen=True, slots=True)
class GutenbergBook:
    """One catalogue record."""

    id: int
    title: str
    authors: tuple[str, ...] = ()
    languages: tuple[str, ...] = ()
    download_count: int = 0
    copyrighted: bool | None = False
    formats: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_api(cls, payload: dict) -> GutenbergBook:
        return cls(
            id=int(payload["id"]),
            title=(payload.get("title") or "").strip(),
            authors=tuple(normalize_author(a.get("name", "")) for a in payload.get("authors") or ()),
            languages=tuple(payload.get("languages") or ()),
            download_count=int(payload.get("download_count") or 0),
            copyrighted=payload.get("copyright"),
            formats=dict(payload.get("formats") or {}),
        )

    @property
    def author(self) -> str:
        return ", ".join(self.authors) if self.authors else "Unknown"

    @property
    def label(self) -> str:
        return f"{self.title} — {self.author}  (#{self.id}, {self.download_count:,} downloads)"

    def url_for(self, kind: str) -> str | None:
        """URL for a logical format (``epub``, ``text``, ``html``, ``cover``)."""
        for wanted in _FORMAT_KEYS.get(kind, ()):
            for mime, url in self.formats.items():
                if mime.startswith(wanted) and not url.endswith(".zip"):
                    return url
        return None

    def available_formats(self) -> list[str]:
        return [kind for kind in ("epub", "text", "html") if self.url_for(kind)]


@dataclass(slots=True)
class DownloadedBook:
    """A book on disk, ready for the pipeline."""

    book: GutenbergBook
    path: Path
    cover_path: Path | None = None
    fmt: str = "epub"

    def as_meta(self) -> dict:
        """Metadata for :func:`echo.core.file_to_audio`."""
        meta = {"title": self.book.title, "author": self.book.author}
        if self.cover_path:
            meta["image_path"] = str(self.cover_path)
        return meta


# ─────────────────────────────────────────────────────────────────────────────
# HTTP
# ─────────────────────────────────────────────────────────────────────────────


def _get(url: str, *, binary: bool = False) -> bytes | str:
    """Fetch a URL with a real User-Agent and a couple of polite retries."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    last: Exception | None = None
    for attempt in range(1, _RETRIES + 1):
        try:
            with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
                payload = response.read()
            return payload if binary else payload.decode("utf-8", errors="replace")
        except (urllib.error.URLError, TimeoutError, OSError) as ex:
            last = ex
            if attempt < _RETRIES:
                delay = 2.0 * attempt
                log.warning(f"{url} failed ({ex}); retrying in {delay:.0f}s")
                time.sleep(delay)
    raise GutenbergError(f"Could not reach {url}: {last}") from last


# ─────────────────────────────────────────────────────────────────────────────
# Catalogue
# ─────────────────────────────────────────────────────────────────────────────


def _query(**params) -> dict:
    url = GUTENDEX_URL + "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v})
    try:
        return json.loads(_get(url))
    except json.JSONDecodeError as ex:
        raise GutenbergError(f"Gutendex returned something that isn't JSON: {ex}") from ex


def search(
    title: str,
    author: str = None,
    language: str = "en",
    limit: int = 10,
) -> list[GutenbergBook]:
    """Search Project Gutenberg by title, optionally narrowed by author.

    Gutendex searches titles and authors together, so both terms go into one
    query; when an author is given, results are then filtered to those whose
    author actually matches, since the API would happily return a title-only hit.
    """
    terms = " ".join(part for part in (title, author) if part and part.strip())
    if not terms.strip():
        raise ValueError("Please provide something to search for.")

    payload = _query(search=terms, languages=language)
    books = [GutenbergBook.from_api(item) for item in payload.get("results") or ()]

    if author:
        needles = [t for t in re.split(r"[\s,]+", author.lower()) if len(t) > 1]
        books = [b for b in books if all(n in b.author.lower() for n in needles)] or books

    books = [b for b in books if b.available_formats()]
    # Title relevance, then EPUB availability (it is the edition with chapter
    # structure), then popularity.
    books.sort(
        key=lambda b: (
            -_title_relevance(b, title or ""),
            0 if b.url_for("epub") else 1,
            -b.download_count,
        )
    )
    log.info(f"Found {len(books)} match(es) for {terms!r} on Project Gutenberg")
    return books[:limit]


def get(book_id: int) -> GutenbergBook:
    """Look up one book by its Project Gutenberg id."""
    payload = _query(ids=str(int(book_id)))
    results = payload.get("results") or ()
    if not results:
        raise GutenbergError(f"Project Gutenberg has no book with id {book_id}")
    return GutenbergBook.from_api(results[0])


# ─────────────────────────────────────────────────────────────────────────────
# Download
# ─────────────────────────────────────────────────────────────────────────────


def download(
    book: GutenbergBook,
    dest_dir: str | Path = None,
    prefer: str = "epub",
    with_cover: bool = True,
    refresh: bool = False,
) -> DownloadedBook:
    """Download a book (and its cover), returning where it landed.

    Args:
        prefer: ``epub`` (default, keeps chapter structure) or ``text``.
        with_cover: also fetch the cover image, to embed as album art.
        refresh: re-download even if a cached copy exists.
    """
    if book.copyrighted:
        log.warning(
            f"'{book.title}' is marked as still under copyright in the catalogue. "
            "Project Gutenberg hosts it with permission; check the terms on its "
            "page before redistributing anything you make from it."
        )

    order = [prefer] + [f for f in ("epub", "text", "html") if f != prefer]
    chosen = next((f for f in order if book.url_for(f)), None)
    if chosen is None:
        raise GutenbergError(f"'{book.title}' has no downloadable text format (only {sorted(book.formats)})")
    if chosen != prefer:
        log.info(f"{prefer} is not available for '{book.title}'; using {chosen} instead")

    dest_dir = Path(dest_dir) if dest_dir else CACHE_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)
    path = dest_dir / f"pg{book.id}_{_slug(book.title)}{_SUFFIXES[chosen]}"

    if path.exists() and path.stat().st_size > 0 and not refresh:
        log.info(f"Using the cached download at {path}")
    else:
        url = book.url_for(chosen)
        log.info(f"Downloading '{book.title}' ({chosen}) from {url}")
        payload = _get(url, binary=True)
        if not payload:
            raise GutenbergError(f"Download of '{book.title}' returned no data")
        path.write_bytes(payload)
        log.info(f"Saved {len(payload):,} bytes to {path}")

    cover_path = None
    if with_cover and (cover_url := book.url_for("cover")):
        cover_path = dest_dir / f"pg{book.id}_cover{Path(urllib.parse.urlparse(cover_url).path).suffix or '.jpg'}"
        if not (cover_path.exists() and cover_path.stat().st_size > 0) or refresh:
            try:
                cover_path.write_bytes(_get(cover_url, binary=True))
                log.info(f"Saved cover art to {cover_path}")
            except GutenbergError as ex:
                # Cover art is decoration; never fail a book over it.
                log.warning(f"Could not fetch cover art: {ex}")
                cover_path = None

    return DownloadedBook(book=book, path=path, cover_path=cover_path, fmt=chosen)


def fetch(
    title: str = None,
    author: str = None,
    book_id: int = None,
    language: str = "en",
    prefer: str = "epub",
    dest_dir: str | Path = None,
    with_cover: bool = True,
) -> DownloadedBook:
    """Search for a book and download the best match in one step.

    Pass ``book_id`` to skip searching. Otherwise the most-downloaded match wins,
    and the choice is logged so it is never a silent guess.
    """
    if book_id:
        book = get(book_id)
    else:
        matches = search(title, author, language=language)
        if not matches:
            hint = f" by {author}" if author else ""
            raise GutenbergError(
                f"Nothing on Project Gutenberg matched '{title}'{hint}. "
                "Try fewer words, or drop the author."
            )
        book = matches[0]
        if len(matches) > 1:
            log.info(f"Chose the most-downloaded match: {book.label}")
            for other in matches[1:5]:
                log.info(f"  other match: {other.label}")

    return download(book, dest_dir=dest_dir, prefer=prefer, with_cover=with_cover)


def _slug(text: str, limit: int = 60) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", (text or "book").lower()).strip("_")
    return (slug[:limit].rstrip("_")) or "book"
