"""Chunking and plain-text block extraction."""

import pytest

import echo.constants as ec
from echo.document import BlockKind
from echo.extractors.text import (
    blocks_from_plain_text,
    strip_gutenberg_blocks,
    to_chunks,
    unwrap_paragraph,
)
from echo.document import Block


class TestToChunks:
    def test_whitespace_is_actually_normalized(self):
        """re.sub returns a new string; the original code discarded the result, so
        this normalization silently never ran."""
        chunks = to_chunks("one    two\n\n\n\n\nthree     four", max_chars=8000)
        joined = "\n\n".join(chunks)
        assert "  " not in joined
        assert "\n\n\n" not in joined

    def test_chunks_respect_the_limit(self):
        text = "\n\n".join(f"Paragraph number {i} with some words in it." for i in range(200))
        chunks = to_chunks(text, max_chars=300)
        assert len(chunks) > 5
        assert all(len(c) <= 300 for c in chunks)

    def test_a_single_oversized_paragraph_splits_on_sentences(self):
        para = " ".join(f"This is sentence {i}." for i in range(200))
        chunks = to_chunks(para, max_chars=300)
        assert all(len(c) <= 300 for c in chunks)
        assert all(c.strip() for c in chunks)

    def test_no_content_is_lost(self):
        text = "\n\n".join(f"Paragraph {i}." for i in range(50))
        rejoined = " ".join(to_chunks(text, max_chars=200))
        for i in range(50):
            assert f"Paragraph {i}." in rejoined

    def test_default_limit_comes_from_constants(self):
        assert to_chunks("short text") == ["short text"]
        assert ec.CHUNK_SIZE > 0


class TestUnwrapParagraph:
    def test_hard_wrapped_lines_join(self):
        assert unwrap_paragraph("The tortoise set\nout at dawn.") == "The tortoise set out at dawn."

    def test_empty_input(self):
        assert unwrap_paragraph("   \n  ") == ""


class TestPlainTextBlocks:
    def test_paragraphs_split_on_blank_lines(self):
        blocks = blocks_from_plain_text("One para.\n\nTwo para.", detect_headings=False)
        assert [b.text for b in blocks] == ["One para.", "Two para."]

    def test_shouted_short_lines_become_headings(self):
        blocks = blocks_from_plain_text("ECLOGUE I\n\nSome prose follows here.")
        assert blocks[0].kind == BlockKind.HEADING
        assert blocks[0].text == "ECLOGUE I"
        assert blocks[1].kind == BlockKind.PARAGRAPH

    def test_division_words_become_headings(self):
        blocks = blocks_from_plain_text("Chapter Four\n\nProse.")
        assert blocks[0].kind == BlockKind.HEADING

    def test_ordinary_prose_is_never_mistaken_for_a_heading(self):
        for prose in (
            "He nodded.",
            "It was, she conceded, a good line",  # long enough to fail the length test
            "the race is not always to the swift",
        ):
            blocks = blocks_from_plain_text(prose)
            assert blocks[0].kind == BlockKind.PARAGRAPH, prose

    def test_heading_detection_can_be_switched_off(self):
        blocks = blocks_from_plain_text("ECLOGUE I", detect_headings=False)
        assert blocks[0].kind == BlockKind.PARAGRAPH


class TestGutenbergStripping:
    def test_asterisk_markers(self):
        blocks = [
            Block(BlockKind.PARAGRAPH, "legal preamble"),
            Block(BlockKind.PARAGRAPH, "*** START OF THIS PROJECT GUTENBERG EBOOK ***"),
            Block(BlockKind.PARAGRAPH, "real content"),
            Block(BlockKind.PARAGRAPH, "*** END OF THIS PROJECT GUTENBERG EBOOK ***"),
            Block(BlockKind.PARAGRAPH, "licence text"),
        ]
        kept, stripped = strip_gutenberg_blocks(blocks)
        assert stripped is True
        assert [b.text for b in kept] == ["real content"]

    def test_epub_style_banner_and_licence_heading(self):
        blocks = [
            Block(BlockKind.HEADING, "The Project Gutenberg eBook of Some Book"),
            Block(BlockKind.PARAGRAPH, "Title : Some Book"),
            Block(BlockKind.PARAGRAPH, "Author : Someone"),
            Block(BlockKind.PARAGRAPH, "Release date : July 1, 2003"),
            Block(BlockKind.PARAGRAPH, "real content"),
            Block(BlockKind.HEADING, "THE FULL PROJECT GUTENBERG LICENSE"),
            Block(BlockKind.PARAGRAPH, "licence text"),
        ]
        kept, stripped = strip_gutenberg_blocks(blocks)
        assert stripped is True
        assert [b.text for b in kept] == ["real content"]

    def test_a_normal_document_is_untouched(self):
        blocks = [Block(BlockKind.PARAGRAPH, "just a book")]
        kept, stripped = strip_gutenberg_blocks(blocks)
        assert stripped is False
        assert kept is blocks

    @pytest.mark.parametrize(
        "heading",
        [
            "THE FULL PROJECT GUTENBERG LICENSE",
            "THE FULL PROJECT GUTENBERG™ LICENSE",  # the trademark sign is real
            "THE FULL PROJECT GUTENBERG™ LICENCE",
            "END OF THE PROJECT GUTENBERG EBOOK",
            "START: FULL LICENSE",
        ],
    )
    def test_licence_heading_variants_are_all_recognized(self, heading):
        blocks = [
            Block(BlockKind.PARAGRAPH, "real content"),
            Block(BlockKind.HEADING, heading),
            Block(BlockKind.PARAGRAPH, "licence text"),
        ]
        kept, stripped = strip_gutenberg_blocks(blocks)
        assert stripped is True
        assert [b.text for b in kept] == ["real content"]
