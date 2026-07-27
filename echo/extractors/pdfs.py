"""PDF extraction.

Two changes from the original: structure comes from ``pymupdf4llm`` (which emits
markdown with real headings and tables) instead of being inferred from line
lengths, and OCR runs through PyMuPDF's own Tesseract integration instead of
``pdf2image`` + Poppler + OpenCV. That removes three dependencies and a
``POPPLER_PATH`` environment variable from the install story.
"""

import logging
import re
from pathlib import Path
from typing import Optional

import pymupdf as pp

from echo.document import Block, Document
from echo.extractors.markdown import blocks_from_markdown
from echo.extractors.text import blocks_from_plain_text

log = logging.getLogger(__name__)

UNPRINTABLES = re.compile(r"[^\x20-\x7E\n]")
MAX_PAGE = 999999

_OCR_HELP = (
    "This PDF has pages with no extractable text, so OCR is required — but "
    "Tesseract is not available to PyMuPDF. Install Tesseract (on macOS: "
    "`brew install tesseract`) and make sure TESSDATA_PREFIX points at its "
    "tessdata directory, or use a text-based PDF."
)


def name_for_file(pdf_path: str, ext: str = "mp3") -> str:
    p = Path(pdf_path)
    return p.name.replace(p.suffix, "." + ext)


def _clean_up_text(text: Optional[str]) -> Optional[str]:
    if text is None:
        return None
    text = text.replace("—", " ").replace("–", " ")
    text = text.replace("\xad\n", "")
    text = text.replace("-\n", "")  # fails for three-year across lines ...
    text = text.replace("\xa0", " ")
    text = UNPRINTABLES.sub("", text)
    return text


def ocr_page(page: pp.Page, dpi: int = 200) -> str:
    """OCR a single page using PyMuPDF's built-in Tesseract bridge."""
    try:
        textpage = page.get_textpage_ocr(dpi=dpi, full=True)
        return page.get_text("text", textpage=textpage) or ""
    except Exception as ex:  # RuntimeError when the tesseract library is missing
        raise RuntimeError(_OCR_HELP) from ex


def layout_markdown(document: pp.Document, pages: list[int]) -> list[dict] | None:
    """Per-page markdown from ``pymupdf4llm``, or ``None`` if it isn't installed.

    Kept optional because pymupdf4llm pulls ``pymupdf-layout`` → ``onnxruntime``,
    roughly 180 MB of ONNX inference machinery. That is a poor deal for someone who
    only wants cloud voices, so the lite install leaves it out and PDFs fall back to
    PyMuPDF's own text extraction — see :func:`extract_pdf`.
    """
    try:
        import pymupdf4llm  # noqa: PLC0415
    except ImportError:
        log.info(
            "pymupdf4llm is not installed, so PDF headings won't be detected and "
            "chapters will be coarser. Install it with "
            "`pip install -r requirements-pdf-layout.txt` for structured extraction."
        )
        return None

    return pymupdf4llm.to_markdown(
        document,
        pages=pages,
        page_chunks=True,
        ignore_images=True,
        ignore_graphics=True,
        show_progress=False,
    )


def _page_range(document: pp.Document, first_page: int | None, last_page: int | None) -> list[int]:
    """Resolve a 1-indexed inclusive page range to 0-indexed page numbers."""
    first = max(1, first_page or 1)
    last = min(len(document), last_page or MAX_PAGE)
    return list(range(first - 1, last))


def extract_pdf(
    pdf_path: str | Path,
    first_page: int | None = None,
    last_page: int | None = None,
    force_ocr: bool = False,
) -> Document:
    """Extract a PDF into a structured :class:`Document`."""
    pdf_path = Path(pdf_path)
    ocr_pages: list[int] = []

    with pp.open(pdf_path) as document:
        pages = _page_range(document, first_page, last_page)
        if not pages:
            raise ValueError(f"{pdf_path} has no pages in the requested range")
        log.info(f"Extracting {len(pages)} page(s) of content from {pdf_path}")

        blocks: list[Block] = []
        chunks: list[dict] | None = None
        if not force_ocr:
            chunks = layout_markdown(document, pages)
        has_layout = bool(chunks)

        ocr_error: str | None = None
        for offset, page_no in enumerate(pages):
            md = ""
            if chunks:
                md = (chunks[offset].get("text") or "") if offset < len(chunks) else ""

            if md.strip():
                blocks.extend(blocks_from_markdown(md, page=page_no + 1))
                continue

            # No layout backend: read the page's own text layer. Headings are then
            # inferred by blocks_from_plain_text's conservative heuristic rather
            # than detected, so chapters are coarser but the book still converts.
            if chunks is None and not force_ocr:
                plain = _clean_up_text(document[page_no].get_text("text")) or ""
                if plain.strip():
                    for block in blocks_from_plain_text(plain):
                        block.page = page_no + 1
                        blocks.append(block)
                    continue

            # No text layer on this page: fall back to OCR. A missing Tesseract
            # is reported once and does not abort the document — a PDF with a few
            # scanned plates should still produce audio for its text pages.
            if ocr_error:
                continue
            try:
                raw = ocr_page(document[page_no])
            except RuntimeError as ex:
                ocr_error = str(ex)
                log.warning(ocr_error)
                continue

            cleaned = _clean_up_text(raw) or ""
            if cleaned.strip():
                ocr_pages.append(page_no + 1)
                for block in blocks_from_plain_text(cleaned):
                    block.page = page_no + 1
                    blocks.append(block)
            else:
                log.warning(f"Page {page_no + 1} of {pdf_path} produced no text, even with OCR")

        meta = document.metadata or {}

    if ocr_pages:
        log.info(f"Used OCR for {len(ocr_pages)} page(s): {ocr_pages[:20]}")

    return Document(
        blocks=blocks,
        title=(meta.get("title") or "").strip() or None,
        author=(meta.get("author") or "").strip() or None,
        source_path=pdf_path,
        provenance={
            "backend": "ocr" if force_ocr else ("pymupdf4llm" if has_layout else "pymupdf"),
            "pages": len(pages),
            "ocr_pages": ocr_pages,
            "ocr_error": ocr_error,
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# Annotation extraction — unrelated to the audio pipeline, but a useful feature
# of this module for pulling highlights out of a marked-up PDF.
# ─────────────────────────────────────────────────────────────────────────────


def _get_highlighted_content(page: pp.Page, ann: pp.Annot) -> dict:
    _text = []
    # annotation.vertices contains vertices of a polygon.  For highlights, the shapes are
    # rectangular, with one rectangle corresponding to one line of highlights.  Vertices
    # does not assume a rectangle, so we are given 4 vertices per rectangle but only need
    # 2 (adjacent corners).
    for i in range(0, len(ann.vertices), 4):
        rect = pp.Rect(ann.vertices[i], ann.vertices[i + 3])
        _text.append(page.get_text("text", clip=rect).strip())
    return {"text": " ".join(_text), "color": ann.colors, "note": ann.info.get("content")}


def _contents_by_type(page: pp.Page, ann: pp.Annot) -> dict:
    # https://pymupdf.readthedocs.io/en/latest/vars.html#annotationtypes
    _type = ann.type  # tuple of form (id, desc1, desc2)
    match _type[0]:
        case 8 | 9:  # HIGHLIGHT or UNDERLINE
            content = _get_highlighted_content(page, ann)
        case _:
            content = {"note": ann.info.get("content")}
    return {"type": _type[-1], **content}


def extract_annotations(
    pdf_path: str | Path,
    first_page: int | None = None,
    last_page: int | None = None,
) -> list[dict]:
    """Collect highlights, underlines and notes from a PDF."""
    with pp.open(pdf_path) as document:
        out = []
        for page_no in _page_range(document, first_page, last_page):
            page = document[page_no]
            out.extend({**_contents_by_type(page, a), "page": page_no + 1} for a in page.annots())
    return out
