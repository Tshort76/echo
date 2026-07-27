"""EPUB extraction.

EPUB is XHTML underneath, so the tag names already tell us the structure —
there is nothing to infer. Reading order follows the spine rather than
``get_items()`` order, which is arbitrary.
"""

import logging
from pathlib import Path

from bs4 import BeautifulSoup
from ebooklib import ITEM_DOCUMENT, epub

from echo.document import Block, BlockKind, Document
from echo.extractors.text import strip_gutenberg_blocks

log = logging.getLogger(__name__)

_TAG_KINDS = {
    "h1": (BlockKind.HEADING, 1),
    "h2": (BlockKind.HEADING, 2),
    "h3": (BlockKind.HEADING, 3),
    "h4": (BlockKind.HEADING, 4),
    "h5": (BlockKind.HEADING, 5),
    "h6": (BlockKind.HEADING, 6),
    "p": (BlockKind.PARAGRAPH, 0),
    "blockquote": (BlockKind.QUOTE, 0),
    "li": (BlockKind.LIST, 0),
    "table": (BlockKind.TABLE, 0),
    "pre": (BlockKind.CODE, 0),
    "figcaption": (BlockKind.FIGURE, 0),
}


def _spine_documents(book: epub.EpubBook) -> list:
    """Content documents in spine (reading) order, falling back to file order."""
    ordered = []
    for item_id, _linear in book.spine:
        item = book.get_item_with_id(item_id)
        if item is not None and item.get_type() == ITEM_DOCUMENT:
            ordered.append(item)
    if ordered:
        return ordered
    return [i for i in book.get_items() if i.get_type() == ITEM_DOCUMENT]


def _blocks_from_html(html: bytes) -> list[Block]:
    soup = BeautifulSoup(html, "html.parser")
    for junk in soup(["script", "style", "nav"]):
        junk.decompose()

    blocks: list[Block] = []
    body = soup.body or soup
    for el in body.find_all(list(_TAG_KINDS), recursive=True):
        # Skip a <p> nested inside a <blockquote> etc.; the outer tag already
        # captured its text.
        if el.find_parent(["blockquote", "table", "pre", "li"]) is not None:
            continue
        kind, level = _TAG_KINDS[el.name]
        text = " ".join(el.get_text(" ", strip=True).split())
        if text:
            blocks.append(Block(kind=kind, text=text, level=level))

    if not blocks:
        # Some EPUBs use bare divs; fall back to the whole document as prose.
        text = " ".join(body.get_text(" ", strip=True).split())
        if text:
            blocks.append(Block(kind=BlockKind.PARAGRAPH, text=text))
    return blocks


def extract_epub(epub_path: str | Path) -> Document:
    """Extract an EPUB into a structured :class:`Document`."""
    epub_path = Path(epub_path)
    book = epub.read_epub(str(epub_path))

    blocks: list[Block] = []
    for item in _spine_documents(book):
        blocks.extend(_blocks_from_html(item.content))

    def _meta(name: str) -> str | None:
        values = book.get_metadata("DC", name)
        return values[0][0] if values else None

    # Project Gutenberg EPUBs carry the same licence boilerplate as their .txt
    # editions, as their own paragraphs.
    blocks, stripped = strip_gutenberg_blocks(blocks)

    return Document(
        blocks=blocks,
        title=_meta("title"),
        author=_meta("creator"),
        source_path=epub_path,
        provenance={
            "backend": "ebooklib",
            "documents": len(_spine_documents(book)),
            "gutenberg_stripped": stripped,
        },
    )


def extract_epub_text(epub_path: str | Path) -> str:
    """Backwards-compatible helper returning the EPUB's text as one string."""
    return extract_epub(epub_path).as_text()
