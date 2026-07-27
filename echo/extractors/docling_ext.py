"""Optional Docling escalation for hard documents.

Not a base dependency — install it only if you hit PDFs the fast path mangles::

    pip install docling

Docling is asked for markdown rather than being read through its own document
model, so the same block parser handles its output as everything else and echo
does not couple itself to Docling's internal API.
"""

from __future__ import annotations

import logging
from pathlib import Path

from echo.document import BlockKind, Document
from echo.extractors.markdown import blocks_from_markdown

log = logging.getLogger(__name__)


def extract_with_docling(path: str | Path) -> Document:
    from docling.document_converter import DocumentConverter  # noqa: PLC0415

    path = Path(path)
    log.info(f"Running Docling on {path.name} (first run downloads layout models)")

    converter = DocumentConverter()
    result = converter.convert(str(path))
    markdown = result.document.export_to_markdown()

    blocks = blocks_from_markdown(markdown)
    title = next((b.text for b in blocks if b.kind == BlockKind.HEADING and b.level == 1), None)

    return Document(
        blocks=blocks,
        title=title,
        source_path=path,
        provenance={"backend": "docling"},
    )
