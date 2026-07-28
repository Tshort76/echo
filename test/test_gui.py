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
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6", reason="GUI dependencies not installed")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QTabWidget,
)

import echo.core as core  # noqa: E402
import gui.style as style  # noqa: E402
from gui.app import GutenbergDialog, MainWindow, ResearchDialog  # noqa: E402
from gui.style import apply_theme  # noqa: E402
from gui.sources import SourceSelection, slugify  # noqa: E402
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


def select_file(tab, path) -> None:
    """Choose a plain file as the source, as the Browse action would."""
    tab._set_source(SourceSelection.from_file(path))


class TestLayout:
    def test_the_window_is_a_single_convert_view(self, window):
        assert window.findChild(QTabWidget) is None

    def test_the_play_button_waits_for_a_result(self, window):
        assert window.play_btn.isEnabled() is False

    def test_the_input_field_is_read_only(self, window):
        """It describes the source rather than being typed into."""
        assert window.convert_tab.input_edit.isReadOnly()


class TestSourceSplitButton:
    def test_it_offers_all_three_sources(self, window):
        actions = window.convert_tab.source_btn.menu().actions()
        assert [a.text() for a in actions] == ["Browse…", "Project Gutenberg…", "Deep Research…"]

    def test_browse_is_the_default_action(self, window):
        tab = window.convert_tab
        assert tab.source_btn.defaultAction() is tab.browse_action
        assert tab.source_btn.defaultAction().text() == "Browse…"

    def test_it_is_a_split_button(self, window):
        from PySide6.QtWidgets import QToolButton

        assert window.convert_tab.source_btn.popupMode() == QToolButton.ToolButtonPopupMode.MenuButtonPopup


class TestSourceSelection:
    """The display strings are the whole point of the read-only field."""

    def test_a_file_shows_its_path(self, tmp_path):
        source = SourceSelection.from_file(tmp_path / "my_book.epub")
        assert source.kind == "file"
        assert source.name == "my_book"
        assert source.display == str(tmp_path / "my_book.epub")

    def test_gutenberg_shows_the_book_and_search_details(self, tmp_path):
        from echo.gutenberg import DownloadedBook, GutenbergBook

        book = GutenbergBook(id=2680, title="Meditations", authors=("Marcus Aurelius",))
        downloaded = DownloadedBook(book=book, path=tmp_path / "pg2680_meditations.epub", fmt="epub")
        source = SourceSelection.from_gutenberg(downloaded, name="meditations", language="English")
        assert source.kind == "gutenberg"
        assert source.name == "meditations"
        for fragment in ("Gutenberg #2680", "Meditations", "Marcus Aurelius", "English", "EPUB"):
            assert fragment in source.display, fragment

    def test_gutenberg_falls_back_to_a_slug_when_no_name_given(self, tmp_path):
        from echo.gutenberg import DownloadedBook, GutenbergBook

        book = GutenbergBook(id=1, title="Pride and Prejudice", authors=("Jane Austen",))
        downloaded = DownloadedBook(book=book, path=tmp_path / "x.epub", fmt="epub")
        assert SourceSelection.from_gutenberg(downloaded, name="").name == "pride_prejudice"

    def test_research_shows_the_topic_that_was_sent(self, tmp_path):
        from echo.research import ResearchResult

        result = ResearchResult(
            name="chronometer",
            topic="the history of the marine chronometer",
            agent="deep-research-preview-04-2026",
            text="body",
            path=tmp_path / "chronometer.md",
        )
        source = SourceSelection.from_research(result)
        assert source.kind == "research"
        assert source.name == "chronometer"
        assert "history of the marine chronometer" in source.display
        assert "deep-research-preview-04-2026" in source.display

    def test_a_very_long_topic_is_trimmed_for_display(self, tmp_path):
        from echo.research import ResearchResult

        result = ResearchResult(
            name="x", topic="word " * 200, agent="a", text="b", path=tmp_path / "x.md"
        )
        assert len(SourceSelection.from_research(result).display) < 220

    def test_the_output_filename_follows_the_source_name(self, window, tmp_path):
        """A Gutenberg cache file is named pg2680_…; the audio should not be."""
        from echo.gutenberg import DownloadedBook, GutenbergBook

        cached = tmp_path / "pg2680_meditations.epub"
        cached.write_bytes(b"x")
        book = GutenbergBook(id=2680, title="Meditations", authors=("Marcus Aurelius",))
        downloaded = DownloadedBook(book=book, path=cached, fmt="epub")
        window.convert_tab._set_source(
            SourceSelection.from_gutenberg(downloaded, name="meditations")
        )
        assert Path(window.convert_tab.output_edit.text()).name == "meditations.m4b"

    def test_source_metadata_prefills_but_does_not_override(self, window, tmp_path):
        from echo.research import ResearchResult

        tab = window.convert_tab
        tab.settings.title_edit.setText("My Own Title")
        report = tmp_path / "r.md"
        report.write_text("# R\n\nProse.\n", encoding="utf-8")
        tab._set_source(
            SourceSelection.from_research(
                ResearchResult(name="r", topic="t", agent="a", text="b", path=report)
            )
        )
        assert tab.settings.title_edit.text() == "My Own Title"
        assert tab.settings.author_edit.text() == "Gemini Deep Research"


class TestSlugify:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("the history of the marine chronometer", "history_marine_chronometer"),
            ("Pride and Prejudice", "pride_prejudice"),
            ("", "research"),
            ("!!! ???", "research"),
        ],
    )
    def test_it_keeps_the_meaningful_words(self, text, expected):
        assert slugify(text) == expected


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
        select_file(tab, book)
        assert tab.output_edit.text().endswith(".m4b")

        formats = [tab.format_combo.itemData(i) for i in range(tab.format_combo.count())]
        tab.format_combo.setCurrentIndex(formats.index("mp3"))
        assert tab.output_edit.text().endswith(".mp3")


class TestGather:
    def test_it_produces_arguments_file_to_audio_accepts(self, window, book):
        """The GUI and the backend signature drift apart silently otherwise."""
        tab = window.convert_tab
        select_engine(tab, "edge")
        select_file(tab, book)

        params = tab.gather()
        accepted = set(inspect.signature(core.file_to_audio).parameters)
        # ConversionWorker renames two of them on the way through.
        translated = (set(params) - {"meta", "save_text", "log_level"}) | {"mp3_meta", "write_text_file"}
        assert translated <= accepted, translated - accepted

    def test_it_builds_a_worker(self, window, book):
        tab = window.convert_tab
        select_engine(tab, "edge")
        select_file(tab, book)
        assert ConversionWorker(**tab.gather())._level == logging.INFO

    def test_the_verbosity_setting_reaches_the_worker(self, window, book):
        tab = window.convert_tab
        select_engine(tab, "edge")
        select_file(tab, book)
        tab.settings.verbosity.setCurrentIndex(2)  # Debug
        assert ConversionWorker(**tab.gather())._level == logging.DEBUG

    def test_metadata_flows_from_the_settings_dialog(self, window, book):
        tab = window.convert_tab
        select_engine(tab, "edge")
        select_file(tab, book)
        tab.settings.title_edit.setText("My Title")
        tab.settings.author_edit.setText("An Author")
        params = tab.gather()
        assert params["meta"] == {"title": "My Title", "author": "An Author"}

    def test_no_source_chosen_is_refused(self, window):
        with pytest.raises(ValueError, match="choose a source"):
            window.convert_tab.gather()

    def test_a_source_that_vanished_is_refused(self, window):
        select_file(window.convert_tab, "/no/such/book.epub")
        with pytest.raises(ValueError, match="no longer on disk"):
            window.convert_tab.gather()

    def test_a_missing_output_is_refused(self, window, book):
        tab = window.convert_tab
        select_file(tab, book)
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
        select_file(tab, book)
        with pytest.raises(ValueError, match="needs setup"):
            tab.gather()

    def test_a_missing_cover_image_is_refused(self, window, book):
        tab = window.convert_tab
        select_engine(tab, "edge")
        select_file(tab, book)
        tab.settings.cover_edit.setText("/no/such/cover.jpg")
        with pytest.raises(ValueError, match="Cover image does not exist"):
            tab.gather()


class TestLabelsFit:
    """Guards a class of bug hit twice while building this dialog: a label either
    clipped by a few pixels, or squeezed to zero width by a field whose
    minimumSizeHint (a combo box's longest item) consumed the whole row."""

    @staticmethod
    def _shown(dialog):
        dialog.adjustSize()
        dialog.show()
        QApplication.processEvents()
        return dialog

    def test_no_settings_label_is_clipped_or_hidden(self, window):
        dialog = self._shown(window.convert_tab.settings)

        squeezed = []
        for form in dialog.findChildren(QFormLayout):
            for row in range(form.rowCount()):
                item = form.itemAt(row, QFormLayout.LabelRole)
                label = item.widget() if item else None
                if label is not None and label.text() and label.width() == 0:
                    squeezed.append(label.text())
        assert squeezed == [], f"label column collapsed for: {squeezed}"

        clipped = [
            w.text()
            for w in dialog.findChildren(QLabel) + dialog.findChildren(QCheckBox)
            if w.text() and w.width() < w.sizeHint().width()
        ]
        assert clipped == [], f"text does not fit: {clipped}"

    def test_no_gutenberg_label_is_clipped_or_hidden(self, app):
        dialog = self._shown(GutenbergDialog())
        clipped = [
            w.text()
            for w in dialog.findChildren(QLabel)
            if w.text() and w.width() < w.sizeHint().width()
        ]
        assert clipped == [], f"text does not fit: {clipped}"


class TestDropdownsLookLikeDropdowns:
    """A QComboBox styled by this theme must show a visible drop-down indicator.

    This is checked in *pixels* rather than by reading the stylesheet, because the
    original bug was silent: styling ``QComboBox::drop-down`` stops Qt drawing its
    own arrow, and with no image supplied the arrow simply disappeared — leaving a
    control identical to a QLineEdit. A stylesheet assertion would have passed.
    """

    WELL = 26  # right-hand strip to inspect, a little wider than the styled well

    @staticmethod
    def _render(widget, width=240, height=34):
        widget.setStyleSheet("")  # inherit the application theme, as in the real app
        widget.resize(width, height)
        widget.show()
        QApplication.processEvents()
        return widget.grab().toImage()

    @classmethod
    def _ink(cls, image, x_from, x_to):
        """Count pixels that differ from the pale field background."""
        scale = image.width() / 240  # devicePixelRatio of the grab
        inset = int(4 * scale)
        count = 0
        for x in range(int(x_from * scale), int(x_to * scale)):
            for y in range(inset, image.height() - inset):
                colour = QColor(image.pixel(x, y))
                if 765 - (colour.red() + colour.green() + colour.blue()) > 40:
                    count += 1
        return count

    @pytest.fixture
    def themed(self, app):
        apply_theme(app)
        yield
        app.setStyleSheet("")

    def test_a_combo_box_draws_an_indicator(self, themed):
        combo = QComboBox()
        combo.addItems(["en-GB-SoniaNeural", "en-US-AriaNeural"])
        image = self._render(combo)
        assert self._ink(image, 240 - self.WELL, 237) > 10, "no drop-down indicator drawn"

    def test_a_line_edit_does_not(self, themed):
        """Proves the check above is measuring the indicator, not the text or border."""
        image = self._render(QLineEdit("en-GB-SoniaNeural"))
        assert self._ink(image, 240 - self.WELL, 237) == 0

    def test_the_indicator_is_not_painted_over_the_text(self, themed):
        """Qt places a *state-dependent* arrow image by the widget rect rather than
        the drop-down rect, which painted a second chevron in the middle of the
        field. Hence one image and no :hover/:disabled variants."""
        combo = QComboBox()
        combo.addItems(["Off"])  # short text, so the middle of the field is empty
        image = self._render(combo)
        assert self._ink(image, 70, 200) == 0, "something is drawn over the field's text area"

    def test_long_text_is_not_drawn_under_the_indicator(self, themed):
        combo = QComboBox()
        combo.addItems(["M4B — audiobook with chapter marks, and then some more words"])
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        image = self._render(combo)
        # The chevron sits alone in the well: its ink is far less than glyphs would add.
        assert self._ink(image, 240 - self.WELL + 2, 237) < 120

    def test_a_missing_asset_falls_back_to_qt_s_own_arrow(self):
        """Half-styling is worse than none: without an image, ``::drop-down`` rules
        would remove the indicator altogether. So they are omitted entirely."""
        assert style._combo_rules(None) == ""

    def test_the_chevron_is_cached_rather_than_rewritten(self):
        first = style.chevron_asset()
        assert first is not None and first.exists()
        assert style.chevron_asset() == first


class TestExtractionControls:
    """Options that used to be CLI-only: --force-ocr, --docling, --no-resume."""

    def test_they_default_to_the_cli_defaults(self, window):
        s = window.convert_tab.settings
        assert s.force_ocr.isChecked() is False
        assert s.use_docling.isChecked() is False
        assert s.resume.isChecked() is True  # --no-resume is opt-in

    def test_docling_is_disabled_when_it_is_not_installed(self, window):
        from importlib.util import find_spec

        s = window.convert_tab.settings
        assert s.use_docling.isEnabled() is (find_spec("docling") is not None)
        if not s.use_docling.isEnabled():
            assert "pip install docling" in s.use_docling.toolTip()

    def test_they_reach_the_backend_through_gather(self, window, book):
        tab = window.convert_tab
        select_engine(tab, "edge")
        select_file(tab, book)
        tab.settings.force_ocr.setChecked(True)
        tab.settings.resume.setChecked(False)

        params = tab.gather()
        assert params["parser_configs"]["force_ocr"] is True
        assert params["parser_configs"]["use_docling"] is False
        assert params["resume"] is False
        # The worker must accept them too.
        ConversionWorker(**params)

    def test_the_pdf_page_range_still_flows_through(self, window, book):
        tab = window.convert_tab
        select_engine(tab, "edge")
        select_file(tab, book)
        tab.settings.first_page.setValue(30)
        tab.settings.last_page.setValue(120)
        configs = tab.gather()["parser_configs"]
        assert (configs["first_page"], configs["last_page"]) == (30, 120)


class TestNormalizerControl:
    def test_it_offers_every_backend_normalizer(self, window):
        from echo.normalize import NORMALIZER_NAMES

        combo = window.convert_tab.settings.normalizer
        assert [combo.itemData(i) for i in range(combo.count())] == list(NORMALIZER_NAMES)

    def test_it_defaults_to_something_that_can_actually_run(self, window):
        s = window.convert_tab.settings
        assert not s._normalizer_reasons.get(s.normalizer.currentData())

    def test_unavailable_choices_are_disabled_with_their_reason(self, window):
        s = window.convert_tab.settings
        model = s.normalizer.model()
        for i in range(s.normalizer.count()):
            name = s.normalizer.itemData(i)
            reason = s._normalizer_reasons.get(name)
            assert model.item(i).isEnabled() is (not reason)
            if reason:
                assert s.normalizer.itemData(i, Qt.ToolTipRole) == reason

    def test_choosing_an_unavailable_normalizer_is_refused(self, window, book):
        """Rather than converting a whole book and quietly not normalizing it."""
        tab = window.convert_tab
        s = tab.settings
        broken = next((n for n, r in s._normalizer_reasons.items() if r), None)
        if broken is None:
            pytest.skip("every normalizer is configured on this machine")
        select_engine(tab, "edge")
        select_file(tab, book)
        s.normalizer.setCurrentIndex(s.normalizer.findData(broken))
        with pytest.raises(ValueError, match="normalization is not available"):
            tab.gather()


class TestResearchDialog:
    def test_it_starts_with_no_result(self, app):
        dialog = ResearchDialog()
        assert dialog.result_research is None

    def test_a_topic_is_required(self, app):
        dialog = ResearchDialog()
        dialog.name_edit.setText("something")
        dialog._start()
        assert dialog._worker is None
        assert "research" in dialog.status.text().lower()

    def test_a_name_is_required(self, app):
        """Deep Research has no filename to fall back on."""
        dialog = ResearchDialog()
        dialog.topic_edit.setPlainText("the history of the marine chronometer")
        dialog.name_edit.clear()
        dialog._name_is_auto = False  # simulate the user clearing it deliberately
        dialog._start()
        assert dialog._worker is None
        assert "name" in dialog.status.text().lower()

    def test_the_name_is_suggested_from_the_topic(self, app):
        dialog = ResearchDialog()
        dialog.topic_edit.setPlainText("the history of the marine chronometer")
        assert dialog.name_edit.text() == "history_marine_chronometer"

    def test_a_typed_name_is_not_overwritten(self, app):
        dialog = ResearchDialog()
        dialog.name_edit.setText("mine")
        dialog.name_edit.textEdited.emit("mine")  # as typing would
        dialog.topic_edit.setPlainText("something else entirely")
        assert dialog.name_edit.text() == "mine"

    def test_it_offers_the_agent_depths(self, app):
        dialog = ResearchDialog()
        codes = [dialog.agent_combo.itemData(i) for i in range(dialog.agent_combo.count())]
        assert codes == ["standard", "max", "pro"]

    def test_it_refuses_to_start_without_credentials(self, app, monkeypatch):
        """The key check happens before a 15-minute job, not during it."""
        import echo.research as research

        monkeypatch.setattr(research.ec, "GEMINI_API_KEY", "")
        monkeypatch.setattr("PySide6.QtWidgets.QMessageBox.warning", lambda *a, **k: None)
        dialog = ResearchDialog()
        dialog.topic_edit.setPlainText("a topic")
        dialog.name_edit.setText("a_name")
        dialog._start()
        assert dialog._worker is None
        assert "GEMINI_API_KEY" in dialog.status.text()


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

    def test_the_catalogue_language_can_be_chosen(self, app):
        dialog = GutenbergDialog()
        codes = [dialog.language_combo.itemData(i) for i in range(dialog.language_combo.count())]
        assert codes[0] == ""  # "Any language"
        assert {"en", "fr", "de", "la"} <= set(codes)
        assert dialog.language_combo.currentData() == "en"

    def test_the_chosen_language_is_passed_to_the_search(self, app, monkeypatch):
        import gui.app as app_module

        captured = {}

        class FakeWorker:
            def __init__(self, title, author, language):
                captured.update(title=title, author=author, language=language)
                self.results = self.failed = _Signal()

            def start(self):
                pass

        class _Signal:
            def connect(self, _fn):
                pass

        monkeypatch.setattr(app_module, "GutenbergSearchWorker", FakeWorker)
        dialog = GutenbergDialog()
        dialog.title_edit.setText("faust")
        dialog.language_combo.setCurrentIndex(dialog.language_combo.findData("de"))
        dialog._search()
        assert captured == {"title": "faust", "author": "", "language": "de"}
