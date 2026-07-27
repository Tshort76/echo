"""Extraction against the real sample documents, plus dispatch and constants."""

import pytest

import echo.constants as ec
import echo.core as core
from echo.document import BlockKind
from echo.extractors import SUPPORTED_SUFFIXES, extract


class TestDispatch:
    def test_supported_suffixes_cover_the_documented_formats(self):
        assert {".pdf", ".txt", ".md", ".epub"} <= set(SUPPORTED_SUFFIXES)

    def test_a_missing_file_raises_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            extract(tmp_path / "absent.txt")

    def test_an_unsupported_suffix_lists_what_is_supported(self, tmp_path):
        path = tmp_path / "book.docx"
        path.write_text("x")
        with pytest.raises(NotImplementedError, match="Supported:"):
            extract(path)

    def test_an_empty_file_is_refused(self, tmp_path):
        path = tmp_path / "empty.txt"
        path.write_text("   \n\n  ")
        with pytest.raises(ValueError, match="No readable text"):
            extract(path)

    def test_the_title_falls_back_to_the_filename(self, tmp_path):
        path = tmp_path / "my_book.txt"
        path.write_text("Some prose to read aloud.")
        assert extract(path).title == "my_book"


class TestMarkdownFile:
    def test_headings_become_chapters_and_tables_are_skipped(self, tmp_path):
        path = tmp_path / "b.md"
        path.write_text(
            "# A Book\n\n## One\n\nProse one.\n\n| a | b |\n| - | - |\n\n## Two\n\nProse two.\n",
            encoding="utf-8",
        )
        doc = core.extract_document(path)
        assert doc.title == "A Book"
        script = core.build_script(doc)
        assert [c.title for c in script.chapters] == ["A Book", "One", "Two"]
        assert "| a | b |" not in script.as_text()

    def test_footnote_markers_are_removed_from_prose(self, tmp_path):
        path = tmp_path / "f.md"
        path.write_text("She declined to elaborate.1 She had other plans.\n", encoding="utf-8")
        text = core.extract_document(path).as_text()
        assert "elaborate.1" not in text
        assert "elaborate." in text


class TestPlainText:
    def test_gutenberg_boilerplate_is_stripped(self, demo_data):
        doc = core.extract_document(demo_data / "abridged_virgil_from_gutenberg.txt")
        assert doc.provenance.get("gutenberg_stripped") is True
        assert "Project Gutenberg" not in doc.as_text()

    def test_divisions_become_chapters(self, demo_data):
        doc = core.extract_document(demo_data / "abridged_virgil_from_gutenberg.txt")
        script = core.build_script(doc)
        assert len(script.chapters) > 1
        assert any("ECLOGUE" in c.title for c in script.chapters)


class TestEpub:
    def test_metadata_and_reading_order(self, demo_data):
        doc = core.extract_document(demo_data / "critique_pure_reason-kant.epub")
        assert doc.title == "The Critique of Pure Reason"
        assert doc.author == "Immanuel Kant"
        assert doc.char_count > 100_000
        assert any(b.kind == BlockKind.HEADING for b in doc.blocks)

    def test_gutenberg_front_and_back_matter_are_stripped(self, demo_data):
        doc = core.extract_document(demo_data / "critique_pure_reason-kant.epub")
        assert doc.provenance.get("gutenberg_stripped") is True
        text = doc.as_text()
        assert "Release date" not in text[:2000]
        assert "PROJECT GUTENBERG LICENSE" not in text

    def test_navigation_sections_are_not_narrated(self, demo_data):
        doc = core.extract_document(demo_data / "critique_pure_reason-kant.epub")
        script = core.build_script(doc)
        assert "Contents" not in [c.title for c in script.chapters]


class TestPdf:
    def test_a_text_pdf_extracts_structure(self, demo_data):
        doc = core.extract_document(demo_data / "america_against_america_sample.pdf")
        assert doc.char_count > 1000
        assert doc.provenance["backend"] in ("pymupdf4llm", "docling")
        assert all(b.page is not None for b in doc.blocks if b.kind != BlockKind.PAGE_ARTIFACT)

    def test_a_page_range_limits_extraction(self, demo_data):
        full = core.extract_document(demo_data / "america_against_america_sample.pdf")
        one = core.extract_document(
            demo_data / "america_against_america_sample.pdf",
            {"first_page": 1, "last_page": 1},
        )
        assert one.char_count <= full.char_count
        assert one.provenance["pages"] == 1

    def test_a_scanned_pdf_without_ocr_says_what_to_install(self, demo_data):
        """It must not fail with a bare Tesseract traceback."""
        path = demo_data / "ocr_3_pages.pdf"
        try:
            doc = core.extract_document(path)
        except ValueError as ex:
            assert "OCR" in str(ex) or "Tesseract" in str(ex)
        else:
            # Tesseract is installed here, so OCR should have produced text.
            assert doc.char_count > 0


class TestConstants:
    def test_speed_is_read_as_a_float(self, monkeypatch):
        """The old shared int-only reader silently discarded DEFAULT_SPEED="1.1"."""
        monkeypatch.setenv("DEFAULT_SPEED", "1.1")
        assert ec._get_env_float("DEFAULT_SPEED", 1.25) == pytest.approx(1.1)

    def test_a_non_numeric_value_falls_back(self, monkeypatch):
        monkeypatch.setenv("DEFAULT_SPEED", "quickly")
        assert ec._get_env_float("DEFAULT_SPEED", 1.25) == 1.25

    def test_ints_still_parse(self, monkeypatch):
        monkeypatch.setenv("DEFAULT_CHUNK_SIZE", " 4096 ")
        assert ec._get_env_int("DEFAULT_CHUNK_SIZE", 8000) == 4096

    @pytest.mark.parametrize("raw,expected", [("1", True), ("true", True), ("YES", True), ("0", False), ("no", False)])
    def test_bools_parse(self, monkeypatch, raw, expected):
        monkeypatch.setenv("WRITE_TRANSCRIPT", raw)
        assert ec._get_env_bool("WRITE_TRANSCRIPT", False) is expected

    def test_m4b_is_the_default_format(self):
        assert ec.DEFAULT_FORMAT == "m4b"
