"""Offscreen tests for the desktop GUI.

Skipped entirely when PySide6 is absent, so a CLI-only install still runs the
suite. Qt is forced to its offscreen platform, so these need no display and are
safe in CI.

These cover the wiring most likely to break when the backend changes: the engine
dropdown is built from the backend registry, the voice list is per-engine, and
``gather()`` has to keep producing exactly the keyword arguments
``core.file_to_audio`` accepts.
"""

from __future__ import annotations

import inspect
import logging
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6", reason="GUI dependencies not installed")

from PySide6.QtWidgets import QApplication, QTabWidget  # noqa: E402

import echo.core as core  # noqa: E402
from gui.app import GutenbergDialog, MainWindow  # noqa: E402
from gui.workers import ConversionWorker  # noqa: E402


@pytest.fixture(scope="module")
def app():
    """One QApplication for the module; Qt allows only a single instance."""
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app):
    return MainWindow()


@pytest.fixture
def book(tmp_path):
    path = tmp_path / "a_book.md"
    path.write_text("# A Book\n\n## One\n\nSome prose to read aloud.\n", encoding="utf-8")
    return path


def engine_ids(tab) -> list[str]:
    return [tab.engine_combo.itemData(i) for i in range(tab.engine_combo.count())]


def select_engine(tab, name: str) -> None:
    tab.engine_combo.setCurrentIndex(engine_ids(tab).index(name))


class TestLayout:
    def test_the_window_is_a_single_convert_view(self, window):
        assert window.findChild(QTabWidget) is None

    def test_the_play_button_waits_for_a_result(self, window):
        assert window.play_btn.isEnabled() is False

    def test_gutenberg_search_is_reachable(self, window):
        assert window.convert_tab.gutenberg_btn.isEnabled()


class TestEngineDropdown:
    def test_it_lists_every_registered_engine(self, window):
        from echo.audio.engines import engine_names

        assert set(engine_ids(window.convert_tab)) == set(engine_names())

    def test_available_engines_are_offered_first(self, window):
        choices = window.convert_tab._engine_choices
        availability = [c.available for c in choices]
        assert availability == sorted(availability, reverse=True)

    def test_unavailable_engines_carry_their_reason(self, window):
        for choice in window.convert_tab._engine_choices:
            assert choice.available or choice.reason

    def test_switching_engine_repopulates_the_voices(self, window):
        tab = window.convert_tab
        select_engine(tab, "edge")
        edge_voices = {tab.voice_picker.voice_combo.itemData(i) for i in range(tab.voice_picker.voice_combo.count())}
        select_engine(tab, "gemini")
        gemini_voices = {
            tab.voice_picker.voice_combo.itemData(i) for i in range(tab.voice_picker.voice_combo.count())
        }
        assert edge_voices and gemini_voices
        assert edge_voices != gemini_voices
        assert "Kore" in gemini_voices  # a Gemini prebuilt voice


class TestFormat:
    def test_m4b_is_the_default(self, window):
        assert window.convert_tab.current_format() == "m4b"

    def test_the_output_suffix_follows_the_format(self, window, book):
        tab = window.convert_tab
        tab._autofill_output(str(book))
        assert tab.output_edit.text().endswith(".m4b")

        formats = [tab.format_combo.itemData(i) for i in range(tab.format_combo.count())]
        tab.format_combo.setCurrentIndex(formats.index("mp3"))
        assert tab.output_edit.text().endswith(".mp3")


class TestGather:
    def test_it_produces_arguments_file_to_audio_accepts(self, window, book):
        """The GUI and the backend signature drift apart silently otherwise."""
        tab = window.convert_tab
        select_engine(tab, "edge")
        tab.input_edit.setText(str(book))
        tab._autofill_output(str(book))

        params = tab.gather()
        accepted = set(inspect.signature(core.file_to_audio).parameters)
        # ConversionWorker renames two of them on the way through.
        translated = (set(params) - {"meta", "save_text", "log_level"}) | {"mp3_meta", "write_text_file"}
        assert translated <= accepted, translated - accepted

    def test_it_builds_a_worker(self, window, book):
        tab = window.convert_tab
        select_engine(tab, "edge")
        tab.input_edit.setText(str(book))
        tab._autofill_output(str(book))
        assert ConversionWorker(**tab.gather())._level == logging.INFO

    def test_the_verbosity_setting_reaches_the_worker(self, window, book):
        tab = window.convert_tab
        select_engine(tab, "edge")
        tab.input_edit.setText(str(book))
        tab._autofill_output(str(book))
        tab.settings.verbosity.setCurrentIndex(2)  # Debug
        assert ConversionWorker(**tab.gather())._level == logging.DEBUG

    def test_metadata_flows_from_the_settings_dialog(self, window, book):
        tab = window.convert_tab
        select_engine(tab, "edge")
        tab.input_edit.setText(str(book))
        tab._autofill_output(str(book))
        tab.settings.title_edit.setText("My Title")
        tab.settings.author_edit.setText("An Author")
        params = tab.gather()
        assert params["meta"] == {"title": "My Title", "author": "An Author"}

    def test_a_missing_input_is_refused(self, window):
        with pytest.raises(ValueError, match="input file"):
            window.convert_tab.gather()

    def test_a_nonexistent_input_is_refused(self, window):
        window.convert_tab.input_edit.setText("/no/such/book.epub")
        with pytest.raises(ValueError, match="does not exist"):
            window.convert_tab.gather()

    def test_a_missing_output_is_refused(self, window, book):
        tab = window.convert_tab
        tab.input_edit.setText(str(book))
        tab.output_edit.clear()
        with pytest.raises(ValueError, match="where to save"):
            tab.gather()

    def test_an_engine_that_needs_setup_is_refused_with_its_reason(self, window, book):
        """Better to say so before starting than to fail mid-conversion."""
        tab = window.convert_tab
        unavailable = next((c for c in tab._engine_choices if not c.available), None)
        if unavailable is None:
            pytest.skip("every engine is configured on this machine")
        select_engine(tab, unavailable.name)
        tab.input_edit.setText(str(book))
        tab._autofill_output(str(book))
        with pytest.raises(ValueError, match="needs setup"):
            tab.gather()

    def test_a_missing_cover_image_is_refused(self, window, book):
        tab = window.convert_tab
        select_engine(tab, "edge")
        tab.input_edit.setText(str(book))
        tab._autofill_output(str(book))
        tab.settings.cover_edit.setText("/no/such/cover.jpg")
        with pytest.raises(ValueError, match="Cover image does not exist"):
            tab.gather()


class TestGutenbergDialog:
    def test_it_starts_with_nothing_selected(self, app):
        dialog = GutenbergDialog()
        assert dialog.result_book is None
        assert dialog.download_btn.isEnabled() is False

    def test_an_empty_query_is_not_sent(self, app):
        dialog = GutenbergDialog()
        dialog._search()
        assert dialog._search_worker is None
        assert "title" in dialog.status.text().lower()

    def test_results_populate_the_list_and_enable_download(self, app):
        from echo.gutenberg import GutenbergBook

        dialog = GutenbergDialog()
        dialog._on_results(
            [
                GutenbergBook(id=2680, title="Meditations", authors=("Marcus Aurelius",), download_count=60197),
                GutenbergBook(id=1342, title="Pride and Prejudice", authors=("Jane Austen",)),
            ]
        )
        assert dialog.results_list.count() == 2
        assert dialog.download_btn.isEnabled()
        assert "Meditations" in dialog.results_list.item(0).text()

    def test_an_empty_result_set_says_so(self, app):
        dialog = GutenbergDialog()
        dialog._on_results([])
        assert dialog.results_list.count() == 0
        assert "nothing matched" in dialog.status.text().lower()

    def test_a_paragraph_length_title_is_trimmed(self, app):
        from echo.gutenberg import GutenbergBook

        dialog = GutenbergDialog()
        dialog._on_results([GutenbergBook(id=1, title="A military dictionary: " + "words " * 100)])
        item = dialog.results_list.item(0)
        assert len(item.text()) <= dialog._MAX_LABEL
        assert item.text().endswith("…")
