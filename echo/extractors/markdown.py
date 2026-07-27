"""Markdown -> ``Block`` list.

This is the shared workhorse of the extraction layer: ``.md`` files arrive as
markdown, and ``pymupdf4llm`` renders PDFs as markdown, so one parser labels the
structure for both. That labelling is what replaced the old approach of guessing
whether a line was a heading by comparing its length to the previous line's.
"""

from __future__ import annotations

import re

from echo.document import Block, BlockKind

ATX_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
SETEXT_H1 = re.compile(r"^=+\s*$")
SETEXT_H2 = re.compile(r"^-{2,}\s*$")
FENCE = re.compile(r"^\s*(```|~~~)")
TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
TABLE_DIVIDER = re.compile(r"^\s*\|[\s:|-]+\|\s*$")
BLOCKQUOTE = re.compile(r"^\s*>\s?")
LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d{1,3}[.)])\s+")
HORIZONTAL_RULE = re.compile(r"^\s*(?:[-*_]\s*){3,}$")
IMAGE_ONLY = re.compile(r"^\s*!\[[^\]]*\]\([^)]*\)\s*$")

# Inline markup, removed so the narrator doesn't read punctuation aloud.
_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_FOOTNOTE_REF = re.compile(r"\[\^[^\]]+\]")
_BOLD_ITALIC = re.compile(r"(\*{1,3}|_{1,3})(\S(?:.*?\S)?)\1")
_INLINE_CODE = re.compile(r"`([^`]+)`")
_HTML_TAG = re.compile(r"</?[a-zA-Z][^>]*>")


def strip_inline_markdown(text: str) -> str:
    """Remove inline markup, keeping the words a narrator should say."""
    text = _IMAGE.sub("", text)
    text = _LINK.sub(r"\1", text)
    text = _FOOTNOTE_REF.sub("", text)
    text = _INLINE_CODE.sub(r"\1", text)
    text = _BOLD_ITALIC.sub(r"\2", text)
    text = _HTML_TAG.sub("", text)
    return text.strip()


def _flush(buf: list[str], kind: BlockKind, page: int | None, out: list[Block]) -> None:
    if not buf:
        return
    raw = "\n".join(buf).strip()
    buf.clear()
    if not raw:
        return
    if kind in (BlockKind.TABLE, BlockKind.CODE, BlockKind.FIGURE):
        # Kept verbatim: these are not spoken, but --save output and future
        # features should still be able to see them.
        out.append(Block(kind=kind, text=raw, page=page))
        return
    if kind == BlockKind.QUOTE:
        raw = "\n".join(BLOCKQUOTE.sub("", ln) for ln in raw.splitlines())
    if kind == BlockKind.LIST:
        raw = "\n".join(LIST_ITEM.sub("", ln) for ln in raw.splitlines())
    # Soft-wrapped lines inside one paragraph become a single spoken run.
    text = strip_inline_markdown(" ".join(ln.strip() for ln in raw.splitlines()))
    if text:
        out.append(Block(kind=kind, text=text, page=page))


def blocks_from_markdown(md: str, page: int | None = None) -> list[Block]:
    """Parse markdown into labelled blocks.

    Deliberately a small hand-rolled parser rather than a full CommonMark
    implementation: we only need to tell prose from headings, tables, code and
    figures, and a dependency-free parser keeps the CLI light.
    """
    out: list[Block] = []
    buf: list[str] = []
    current = BlockKind.PARAGRAPH
    in_fence = False

    lines = md.splitlines()
    for i, line in enumerate(lines):
        if FENCE.match(line):
            if in_fence:
                _flush(buf, BlockKind.CODE, page, out)
                in_fence = False
            else:
                _flush(buf, current, page, out)
                in_fence = True
                current = BlockKind.CODE
            continue
        if in_fence:
            buf.append(line)
            continue

        if not line.strip():
            _flush(buf, current, page, out)
            current = BlockKind.PARAGRAPH
            continue

        if HORIZONTAL_RULE.match(line) and not buf:
            continue

        if m := ATX_HEADING.match(line):
            _flush(buf, current, page, out)
            title = strip_inline_markdown(m.group(2))
            if title:
                out.append(Block(kind=BlockKind.HEADING, text=title, level=len(m.group(1)), page=page))
            current = BlockKind.PARAGRAPH
            continue

        # Setext headings: the underline follows the text, so peek back at buf.
        if buf and current == BlockKind.PARAGRAPH and (SETEXT_H1.match(line) or SETEXT_H2.match(line)):
            title = strip_inline_markdown(" ".join(b.strip() for b in buf))
            buf.clear()
            if title:
                out.append(
                    Block(
                        kind=BlockKind.HEADING,
                        text=title,
                        level=1 if SETEXT_H1.match(line) else 2,
                        page=page,
                    )
                )
            continue

        if IMAGE_ONLY.match(line):
            _flush(buf, current, page, out)
            out.append(Block(kind=BlockKind.FIGURE, text=line.strip(), page=page))
            current = BlockKind.PARAGRAPH
            continue

        if TABLE_ROW.match(line) or TABLE_DIVIDER.match(line):
            if current != BlockKind.TABLE:
                _flush(buf, current, page, out)
                current = BlockKind.TABLE
            buf.append(line)
            continue

        if BLOCKQUOTE.match(line):
            if current != BlockKind.QUOTE:
                _flush(buf, current, page, out)
                current = BlockKind.QUOTE
            buf.append(line)
            continue

        if LIST_ITEM.match(line):
            if current != BlockKind.LIST:
                _flush(buf, current, page, out)
                current = BlockKind.LIST
            buf.append(line)
            continue

        if current in (BlockKind.TABLE, BlockKind.CODE, BlockKind.FIGURE):
            _flush(buf, current, page, out)
            current = BlockKind.PARAGRAPH

        buf.append(line)

    _flush(buf, BlockKind.CODE if in_fence else current, page, out)
    return out
