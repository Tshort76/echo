"""Extractors: file on disk -> :class:`~echo.document.Document`.

One dispatch point, one protocol. Adding a format means adding a function and a
suffix to :data:`_BY_SUFFIX`, not touching the pipeline.

A Docling escalation is available for PDFs whose text layer comes back sparse or
badly ordered; it is optional and lazily imported, so the CLI stays light for the
common case.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Protocol

from echo.document import Document

log = logging.getLogger(__name__)


class Extractor(Protocol):
    """Anything that turns a path into a Document."""

    def __call__(self, path: Path, **configs) -> Document: ...


def _extract_pdf(path: Path, **configs) -> Document:
    from echo.extractors.pdfs import extract_pdf

    doc = extract_pdf(
        path,
        first_page=configs.get("first_page"),
        last_page=configs.get("last_page"),
        force_ocr=configs.get("force_ocr", False),
    )

    if configs.get("use_docling") or _looks_sparse(doc):
        better = _try_docling(path, **configs)
        if better is not None:
            return better
    return doc


def _looks_sparse(doc: Document) -> bool:
    """Heuristic escalation trigger: very little text per page suggests the fast
    path mis-read the layout."""
    pages = doc.provenance.get("pages") or 0
    if not pages:
        return False
    per_page = doc.char_count / pages
    if per_page < 200:
        log.info(f"Only {per_page:.0f} characters per page extracted; trying Docling if available")
        return True
    return False


def _try_docling(path: Path, **configs) -> Document | None:
    try:
        from echo.extractors.docling_ext import extract_with_docling
    except ImportError:
        log.info("Docling is not installed (`pip install docling`); keeping the pymupdf4llm result")
        return None
    try:
        return extract_with_docling(path)
    except Exception as ex:
        log.warning(f"Docling extraction failed ({ex}); keeping the pymupdf4llm result")
        return None


def _extract_txt(path: Path, **_configs) -> Document:
    from echo.extractors.text import extract_txt

    return extract_txt(path)


def _extract_md(path: Path, **_configs) -> Document:
    from echo.extractors.text import extract_markdown

    return extract_markdown(path)


def _extract_epub(path: Path, **_configs) -> Document:
    from echo.extractors.misc import extract_epub

    return extract_epub(path)


_BY_SUFFIX: dict[str, Callable[..., Document]] = {
    ".pdf": _extract_pdf,
    ".txt": _extract_txt,
    ".text": _extract_txt,
    ".md": _extract_md,
    ".markdown": _extract_md,
    ".epub": _extract_epub,
}

SUPPORTED_SUFFIXES = tuple(sorted(_BY_SUFFIX))


def extract(path: str | Path, **configs) -> Document:
    """Parse ``path`` into a structured Document, dispatching on its suffix."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"No such file: {path}")

    extractor = _BY_SUFFIX.get(path.suffix.lower())
    if extractor is None:
        raise NotImplementedError(
            f"echo does not support {path.suffix or 'extension-less'} files. "
            f"Supported: {', '.join(SUPPORTED_SUFFIXES)}"
        )

    doc = extractor(path, **configs)
    if not doc.spoken():
        reason = doc.provenance.get("ocr_error")
        raise ValueError(
            f"No readable text was extracted from {path}." + (f"\n{reason}" if reason else "")
        )

    doc.title = doc.title or path.stem
    log.info(
        f"Extracted {len(doc.blocks)} block(s), {doc.char_count:,} spoken characters "
        f"from {path.name} via {doc.provenance.get('backend', '?')}"
    )
    return doc
