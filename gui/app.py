"""echo desktop GUI — a PySide6 front end for the document→audiobook pipeline.

Run via ``python echo_gui.py`` from the repo root. This module imports the
``echo`` backend but the backend never imports it: the CLI keeps working with no
knowledge that a GUI exists.

The engine dropdown is driven by the backend registry, so engines that need
setup (an API key, a model download) appear greyed with the reason attached
rather than failing once a conversion has started.
"""

from __future__ import annotations

import logging
import sys
from importlib.util import find_spec
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction, QFont, QFontMetrics
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

import echo.constants as ec
from echo.audio.assemble import FORMATS
from echo.normalize import available_normalizers
from gui import sources as gs
from gui import voices as gv
from gui.jobs import ConversionJob, ConversionQueue
from gui.style import apply_theme
from gui.workers import (
    ConversionWorker,
    GutenbergDownloadWorker,
    GutenbergSearchWorker,
    PreviewWorker,
    ResearchWorker,
    open_in_default_app,
)

SUPPORTED_INPUTS = "Supported files (*.txt *.md *.pdf *.epub);;All files (*)"
FORMAT_BLURBS = {
    "m4b": "M4B — audiobook with chapter marks",
    "mp3": "MP3 — plays everywhere, no chapters",
}

#: The better-represented languages in Project Gutenberg's catalogue. Not
#: exhaustive — "Any language" covers the rest.
CATALOGUE_LANGUAGES: tuple[tuple[str, str], ...] = (
    ("English", "en"),
    ("French", "fr"),
    ("German", "de"),
    ("Spanish", "es"),
    ("Italian", "it"),
    ("Portuguese", "pt"),
    ("Dutch", "nl"),
    ("Latin", "la"),
    ("Greek", "el"),
    ("Russian", "ru"),
    ("Swedish", "sv"),
    ("Finnish", "fi"),
    ("Danish", "da"),
    ("Hungarian", "hu"),
    ("Polish", "pl"),
    ("Chinese", "zh"),
    ("Japanese", "ja"),
    ("Esperanto", "eo"),
)


# --------------------------------------------------------------------------- #
# Reusable widgets
# --------------------------------------------------------------------------- #
class SpeedControl(QWidget):
    """A slider + label for the playback-speed multiplier (0.5×–3.0×, step 0.05)."""

    _MIN, _MAX, _STEP = 0.5, 3.0, 0.05

    def __init__(self, initial: float = 1.0, parent=None):
        super().__init__(parent)
        self._slider = QSlider(Qt.Horizontal)
        # Slider works in integer "hundredths" so 0.05 steps map cleanly.
        self._slider.setRange(int(self._MIN * 100), int(self._MAX * 100))
        self._slider.setSingleStep(int(self._STEP * 100))
        self._slider.setPageStep(25)
        self._label = QLabel()
        self._label.setMinimumWidth(48)
        self._slider.valueChanged.connect(self._sync_label)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._slider, 1)
        layout.addWidget(self._label)
        self.set_value(initial)

    def _sync_label(self) -> None:
        self._label.setText(f"{self.value():.2f}×")

    def value(self) -> float:
        # Round to the nearest step so we never hand the backend 1.2699999.
        return round(self._slider.value() / 100 / self._STEP) * self._STEP

    def set_value(self, v: float) -> None:
        v = max(self._MIN, min(self._MAX, v))
        self._slider.setValue(int(round(v * 100)))
        self._sync_label()


class VoicePicker(QFrame):
    """A bordered 'voice' component: a filter row (language/gender) above the
    actual voice selector, whose leading audio button previews the voice."""

    def __init__(self, default_voice: str, engine: str = None, parent=None):
        super().__init__(parent)
        self.setObjectName("voicebox")
        self._engine = engine or ec.DEFAULT_ENGINE
        self._all_voices = gv.load_voices(self._engine)
        self._default_voice = default_voice

        self.lang_combo = QComboBox()
        self.gender_combo = QComboBox()
        self.voice_combo = QComboBox()
        # Don't let long voice names dictate the window width — cap the minimum
        # and elide; the full text is still shown in the dropdown popup.
        self.voice_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.voice_combo.setMinimumContentsLength(12)
        # Audio-icon button: previews the selected voice and anchors the row.
        self.preview_btn = QToolButton()
        self.preview_btn.setObjectName("iconbtn")
        self.preview_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaVolume))
        self.preview_btn.setFixedSize(44, 32)
        self.preview_btn.setCursor(Qt.PointingHandCursor)
        self.preview_btn.setToolTip("Preview — play a short sample of this voice")

        self.gender_combo.addItems(["All", "Female", "Male"])
        self._reload_filters()

        self.lang_combo.currentIndexChanged.connect(self._repopulate)
        self.gender_combo.currentIndexChanged.connect(self._repopulate)
        self._repopulate()

        # Selection row: voice selector, with the preview button on its right.
        pick_row = QHBoxLayout()
        pick_row.setContentsMargins(0, 0, 0, 0)
        pick_row.addWidget(self.voice_combo, 1)
        pick_row.addWidget(self.preview_btn)

        grid = QGridLayout(self)
        grid.setContentsMargins(10, 8, 10, 8)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        # Row 0 — filters
        grid.addWidget(QLabel("Language:"), 0, 0)
        grid.addWidget(self.lang_combo, 0, 1)
        grid.addWidget(QLabel("Gender:"), 0, 2)
        grid.addWidget(self.gender_combo, 0, 3)
        grid.setColumnStretch(4, 1)
        # Row 1 — the voice selector (with preview on the right)
        grid.addLayout(pick_row, 1, 0, 1, 5)

    def _reload_filters(self) -> None:
        """Rebuild the language list for the current engine's voices."""
        editable = not self._all_voices
        self.voice_combo.setEditable(editable)
        if editable:
            # The engine can't enumerate voices — let the user type one.
            self.voice_combo.setEditText(self._default_voice)

        self.lang_combo.blockSignals(True)
        self.lang_combo.clear()
        self.lang_combo.addItem("All", None)
        for lang in gv.languages(self._all_voices):
            self.lang_combo.addItem(lang, lang)

        # Preselect the default voice's language, if we can find it.
        default = next((v for v in self._all_voices if v.id == self._default_voice), None)
        if default:
            idx = self.lang_combo.findData(default.language)
            if idx >= 0:
                self.lang_combo.setCurrentIndex(idx)
        self.lang_combo.blockSignals(False)

        has_filters = bool(self._all_voices)
        self.lang_combo.setEnabled(has_filters)
        self.gender_combo.setEnabled(has_filters and any(v.gender for v in self._all_voices))

    def set_engine(self, engine_name: str, default_voice: str = None) -> None:
        """Switch to another engine's voice catalogue."""
        self._engine = engine_name
        self._all_voices = gv.load_voices(engine_name)
        if default_voice:
            self._default_voice = default_voice
        elif self._all_voices:
            self._default_voice = self._all_voices[0].id
        self._reload_filters()
        self._repopulate()

    def _repopulate(self) -> None:
        if not self._all_voices:
            return
        lang = self.lang_combo.currentData()
        gender = self.gender_combo.currentText()
        gender = None if gender == "All" else gender
        matches = gv.filter_voices(self._all_voices, lang, gender)

        previous = self.current_voice()
        self.voice_combo.blockSignals(True)
        self.voice_combo.clear()
        for v in matches:
            self.voice_combo.addItem(gv.display(v), v.id)
        # Try to keep the prior selection; otherwise prefer the default voice.
        for target in (previous, self._default_voice):
            idx = self.voice_combo.findData(target)
            if idx >= 0:
                self.voice_combo.setCurrentIndex(idx)
                break
        self.voice_combo.blockSignals(False)

    def current_voice(self) -> str:
        data = self.voice_combo.currentData()
        if data:
            return data
        # Editable fallback path.
        return self.voice_combo.currentText().strip() or self._default_voice


class SettingsDialog(QDialog):
    """Modal configuration dialog: metadata + output/visibility options.

    Owns the settings widgets; the ConvertTab reads their values in gather().
    A single persistent instance is reused, so values are retained between opens.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Conversion settings")
        self.setModal(True)
        self.setMinimumWidth(480)

        # --- Metadata ---
        self.title_edit = QLineEdit()
        self.author_edit = QLineEdit()
        self.cover_edit = QLineEdit()
        cover_browse = QPushButton("Browse…")
        cover_browse.clicked.connect(self._pick_cover)
        cover_row = QHBoxLayout()
        cover_row.setContentsMargins(0, 0, 0, 0)
        cover_row.addWidget(self.cover_edit, 1)
        cover_row.addWidget(cover_browse)

        meta_form = QFormLayout()
        meta_form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        meta_form.setVerticalSpacing(10)
        meta_form.addRow("Title:", self.title_edit)
        meta_form.addRow("Author:", self.author_edit)
        meta_form.addRow("Cover image:", cover_row)

        # --- Extraction (PDF-oriented; page range belongs here, not with metadata) ---
        self.first_page = QSpinBox()
        self.first_page.setRange(0, 99999)
        self.last_page = QSpinBox()
        self.last_page.setRange(0, 99999)
        self.last_page.setValue(9999)
        page_row = QHBoxLayout()
        page_row.setContentsMargins(0, 0, 0, 0)
        page_row.addWidget(QLabel("First:"))
        page_row.addWidget(self.first_page)
        page_row.addWidget(QLabel("Last:"))
        page_row.addWidget(self.last_page)
        page_row.addStretch(1)

        self.force_ocr = QCheckBox("Always OCR pages")
        self.force_ocr.setToolTip(
            "Ignore the PDF's own text layer and read the pages as images. For "
            "scanned books, or ones whose text layer is garbled. Needs Tesseract "
            "installed (brew install tesseract)."
        )
        self.use_docling = QCheckBox("Use Docling to extract (slower, better layout)")
        docling_installed = find_spec("docling") is not None
        self.use_docling.setEnabled(docling_installed)
        self.use_docling.setToolTip(
            "For documents the fast path mangles."
            if docling_installed
            else "Not installed — run: pip install docling"
        )

        extract_form = QFormLayout()
        extract_form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        extract_form.setVerticalSpacing(10)
        extract_form.addRow("PDF page range:", page_row)
        extract_form.addRow("", self.force_ocr)
        extract_form.addRow("", self.use_docling)

        # --- Narration ---
        # Built from the backend so a normalizer that cannot run is disabled here
        # rather than silently falling back to the rules pass for every chunk.
        self.normalizer = QComboBox()
        self._normalizer_reasons: dict[str, str] = {}
        for normalizer, ok, reason in available_normalizers():
            self.normalizer.addItem(normalizer.label if ok else f"{normalizer.label} — unavailable", normalizer.name)
            row = self.normalizer.count() - 1
            self.normalizer.setItemData(row, reason or normalizer.label, Qt.ToolTipRole)
            self._normalizer_reasons[normalizer.name] = reason
            if not ok:
                self.normalizer.model().item(row).setEnabled(False)
        idx = self.normalizer.findData(ec.NORMALIZER)
        if idx >= 0 and not self._normalizer_reasons.get(ec.NORMALIZER):
            self.normalizer.setCurrentIndex(idx)
        else:
            self.normalizer.setCurrentIndex(max(0, self.normalizer.findData("off")))
        self.normalizer.setToolTip(
            "Optional: have a language model expand abbreviations, numbers and "
            "symbols into spoken words. Guarded so it cannot rewrite your prose."
        )
        # A QComboBox's minimumSizeHint follows its longest item, and "Gemini (needs
        # GEMINI_API_KEY) — unavailable" is long enough to starve QFormLayout's label
        # column to zero width — silently hiding this row's label. Capping the
        # contents length keeps the label visible; the full text still shows in the
        # popup. (Same fix as the voice combo, for the same reason.)
        self.normalizer.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.normalizer.setMinimumContentsLength(24)
        norm_row = QHBoxLayout()
        norm_row.setContentsMargins(0, 0, 0, 0)
        norm_row.addWidget(self.normalizer, 1)

        # --- Output & visibility ---
        self.save_text = QCheckBox("Save the narrated text (.txt)")
        # Kept short so the label fits the dialog's width; the caveat is a tooltip.
        self.write_transcript = QCheckBox("Save a timed transcript (.srt)")
        self.write_transcript.setToolTip(
            "Only the Edge engine reports word timings, so this has no effect on the others."
        )
        self.resume = QCheckBox("Reuse chunks from an interrupted run")
        self.resume.setChecked(True)
        self.resume.setToolTip(
            "On by default: a re-run skips passages already synthesized. Untick to "
            "start the whole book again."
        )
        self.verbosity = QComboBox()
        self.verbosity.addItem("Info", logging.INFO)
        self.verbosity.addItem("Errors only", logging.ERROR)
        self.verbosity.addItem("Debug", logging.DEBUG)
        verb_row = QHBoxLayout()
        verb_row.setContentsMargins(0, 0, 0, 0)
        verb_row.addWidget(self.verbosity)
        verb_row.addStretch(1)

        vis_form = QFormLayout()
        vis_form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        vis_form.setVerticalSpacing(10)
        vis_form.addRow("", self.save_text)
        vis_form.addRow("", self.write_transcript)
        vis_form.addRow("", self.resume)
        vis_form.addRow("Output verbosity:", verb_row)

        norm_form = QFormLayout()
        norm_form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        norm_form.setVerticalSpacing(10)
        norm_form.addRow("Text normalization:", norm_row)

        def heading(text: str) -> QLabel:
            label = QLabel(text)
            label.setObjectName("sectionHeading")
            return label

        meta_heading = heading("Metadata")
        extract_heading = heading("Extraction")
        norm_heading = heading("Narration")
        vis_heading = heading("Output & visibility")

        done = QPushButton("Done")
        done.setObjectName("primary")
        done.setDefault(True)
        done.clicked.connect(self.accept)
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_row.addWidget(done)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)
        layout.addWidget(meta_heading)
        layout.addLayout(meta_form)
        layout.addSpacing(6)
        layout.addWidget(extract_heading)
        layout.addLayout(extract_form)
        layout.addSpacing(6)
        layout.addWidget(norm_heading)
        layout.addLayout(norm_form)
        layout.addSpacing(6)
        layout.addWidget(vis_heading)
        layout.addLayout(vis_form)
        layout.addSpacing(6)
        layout.addLayout(btn_row)

    def _pick_cover(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select cover image", "", "Images (*.jpg *.jpeg *.png);;All files (*)"
        )
        if path:
            self.cover_edit.setText(path)


class GutenbergDialog(QDialog):
    """Search Project Gutenberg and download a book to convert.

    Search and download both run on worker threads — the catalogue is a network
    call, and a book is a few hundred kilobytes — so the dialog never blocks.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Find a book on Project Gutenberg")
        self.setModal(True)
        self.setMinimumSize(620, 460)

        self.result_book = None  # set to a DownloadedBook on success
        self._books: list = []
        self._search_worker = None
        self._download_worker = None

        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("Title, e.g. Meditations")
        self.title_edit.returnPressed.connect(self._search)
        self.author_edit = QLineEdit()
        self.author_edit.setPlaceholderText("Author (optional)")
        self.author_edit.returnPressed.connect(self._search)

        self.search_btn = QPushButton("Search")
        self.search_btn.clicked.connect(self._search)

        self.prefer_combo = QComboBox()
        self.prefer_combo.addItem("EPUB — keeps chapter structure", "epub")
        self.prefer_combo.addItem("Plain text", "text")

        # Gutenberg's catalogue is mostly English, but far from only.
        self.language_combo = QComboBox()
        self.language_combo.addItem("Any language", "")
        for label, code in CATALOGUE_LANGUAGES:
            self.language_combo.addItem(label, code)
        english = self.language_combo.findData("en")
        if english >= 0:
            self.language_combo.setCurrentIndex(english)

        edition_row = QHBoxLayout()
        edition_row.setContentsMargins(0, 0, 0, 0)
        edition_row.addWidget(self.prefer_combo, 1)
        edition_row.addWidget(self.language_combo)

        # The audio filename comes from this, not from the cache filename
        # (which looks like pg2680_meditations.epub).
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Filled in from the book you pick — edit if you like")
        self.name_edit.textEdited.connect(lambda: setattr(self, "_name_is_auto", False))
        self._name_is_auto = True

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        form.setVerticalSpacing(10)
        form.addRow("Title:", self._row(self.title_edit, self.search_btn))
        form.addRow("Author:", self.author_edit)
        form.addRow("Edition:", edition_row)
        form.addRow("Name:", self.name_edit)

        self.results_list = QListWidget()
        self.results_list.setAlternatingRowColors(True)
        # Gutenberg titles run long; wrap them instead of scrolling sideways.
        self.results_list.setWordWrap(True)
        self.results_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.results_list.itemSelectionChanged.connect(self._sync_buttons)
        self.results_list.itemDoubleClicked.connect(self._download)

        self.status = QLabel("Public-domain books, free to download.")
        self.status.setWordWrap(True)

        # No ampersand: QPushButton would read it as a mnemonic accelerator.
        self.download_btn = QPushButton("Download and use")
        self.download_btn.setObjectName("primary")
        self.download_btn.setEnabled(False)
        self.download_btn.clicked.connect(self._download)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(self.download_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)
        layout.addLayout(form)
        results_heading = QLabel("Matches")
        results_heading.setObjectName("sectionHeading")
        layout.addWidget(results_heading)
        layout.addWidget(self.results_list, 1)
        layout.addWidget(self.status)
        layout.addLayout(buttons)

    @staticmethod
    def _row(field, button) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(field, 1)
        row.addWidget(button)
        return row

    def _busy(self, busy: bool, message: str = "") -> None:
        self.search_btn.setEnabled(not busy)
        self.results_list.setEnabled(not busy)
        self.download_btn.setEnabled(not busy and self.results_list.currentRow() >= 0)
        if message:
            self.status.setText(message)

    def _sync_buttons(self) -> None:
        row = self.results_list.currentRow()
        self.download_btn.setEnabled(row >= 0)
        # Suggest a name from the highlighted book until the user types their own.
        if self._name_is_auto and 0 <= row < len(self._books):
            self.name_edit.setText(gs.slugify(self._books[row].title))

    # -- search ------------------------------------------------------------- #
    def _search(self) -> None:
        title = self.title_edit.text().strip()
        author = self.author_edit.text().strip()
        if not title and not author:
            self.status.setText("Type a title (or an author) to search for.")
            return

        self.results_list.clear()
        self._books = []
        self._busy(True, "Searching Project Gutenberg…")

        self._search_worker = GutenbergSearchWorker(title, author, self.language_combo.currentData())
        self._search_worker.results.connect(self._on_results)
        self._search_worker.failed.connect(self._on_failed)
        self._search_worker.start()

    _MAX_LABEL = 110

    def _on_results(self, books: list) -> None:
        self._books = books
        for book in books:
            # A few catalogue titles are paragraph-length; keep one row from
            # filling the pane, with the whole thing in the tooltip.
            label = book.label
            if len(label) > self._MAX_LABEL:
                label = label[: self._MAX_LABEL - 1].rstrip() + "…"
            item = QListWidgetItem(label)
            item.setToolTip(
                f"{book.title}\n{book.author}\n\n"
                f"Formats: {', '.join(book.available_formats())}\n"
                f"Languages: {', '.join(book.languages)}"
            )
            self.results_list.addItem(item)
        if books:
            self.results_list.setCurrentRow(0)
            self._busy(False, f"{len(books)} match(es). Pick one, or refine the search.")
        else:
            self._busy(False, "Nothing matched. Try fewer words, or clear the author.")

    # -- download ----------------------------------------------------------- #
    def _download(self) -> None:
        row = self.results_list.currentRow()
        if row < 0 or row >= len(self._books):
            return
        book = self._books[row]
        self._busy(True, f"Downloading '{book.title}'…")

        self._download_worker = GutenbergDownloadWorker(book, self.prefer_combo.currentData())
        self._download_worker.downloaded.connect(self._on_downloaded)
        self._download_worker.message.connect(self.status.setText)
        self._download_worker.failed.connect(self._on_failed)
        self._download_worker.start()

    def _on_downloaded(self, downloaded) -> None:
        self.result_book = downloaded
        self.accept()

    def _on_failed(self, message: str) -> None:
        self._busy(False)
        self.status.setText(message)
        QMessageBox.warning(self, "Project Gutenberg", message)


class ResearchDialog(QDialog):
    """Ask Gemini Deep Research a question and narrate the report.

    A run takes 2–15 minutes, which is far too long for a spinner, so this shows
    live progress (search count and elapsed time) and can be cancelled.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Research a topic with Gemini")
        self.setModal(True)
        self.setMinimumSize(640, 460)

        self.result_research = None  # set to a ResearchResult on success
        self._worker = None

        self.topic_edit = QPlainTextEdit()
        self.topic_edit.setPlaceholderText(
            "What should it research? e.g. the history of the marine chronometer and "
            "its effect on navigation"
        )
        self.topic_edit.setMinimumHeight(90)
        self.topic_edit.textChanged.connect(self._suggest_name)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Used for the audio filename and title")
        self.name_edit.textEdited.connect(self._name_touched)
        self._name_is_auto = True

        self.agent_combo = QComboBox()
        self.agent_combo.addItem("Standard — a few minutes", "standard")
        self.agent_combo.addItem("Max — many more searches, slower", "max")
        self.agent_combo.addItem("Pro", "pro")
        idx = self.agent_combo.findData(ec.RESEARCH_AGENT)
        if idx >= 0:
            self.agent_combo.setCurrentIndex(idx)

        self.keep_check = QCheckBox("Keep the report and its citations in the project")
        self.keep_check.setChecked(True)
        self.keep_check.setToolTip(
            "Writes <name>.md and <name>.notes.md into resources/research/ "
            "(gitignored). Otherwise a temporary directory is used."
        )

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        form.setVerticalSpacing(10)
        form.addRow("Topic:", self.topic_edit)
        form.addRow("Name:", self.name_edit)
        form.addRow("Depth:", self.agent_combo)
        form.addRow("", self.keep_check)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(500)
        self.log_view.setPlaceholderText("Progress will appear here once research starts…")
        mono = QFont()
        mono.setStyleHint(QFont.Monospace)
        mono.setFamily("Menlo")
        self.log_view.setFont(mono)
        self.log_view.setMinimumHeight(QFontMetrics(mono).lineSpacing() * 4 + 14)

        self.status = QLabel("Deep Research plans, searches the web and writes a cited report.")
        self.status.setWordWrap(True)

        self.start_btn = QPushButton("Start research")
        self.start_btn.setObjectName("primary")
        self.start_btn.setDefault(True)
        self.start_btn.clicked.connect(self._start)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self._cancel)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.cancel_btn)
        buttons.addWidget(self.start_btn)

        heading = QLabel("Progress")
        heading.setObjectName("sectionHeading")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)
        layout.addLayout(form)
        layout.addWidget(heading)
        layout.addWidget(self.log_view, 1)
        layout.addWidget(self.status)
        layout.addLayout(buttons)

    # -- name suggestion ---------------------------------------------------- #
    def _name_touched(self) -> None:
        self._name_is_auto = not self.name_edit.text().strip()

    def _suggest_name(self) -> None:
        """Pre-fill the name from the topic, until the user types their own."""
        if self._name_is_auto:
            self.name_edit.setText(gs.slugify(self.topic_edit.toPlainText()))

    # -- running ------------------------------------------------------------ #
    def _running(self, running: bool) -> None:
        self.start_btn.setEnabled(not running)
        self.topic_edit.setReadOnly(running)
        self.name_edit.setReadOnly(running)
        self.agent_combo.setEnabled(not running)
        self.keep_check.setEnabled(not running)
        self.cancel_btn.setText("Stop" if running else "Cancel")

    def _start(self) -> None:
        topic = self.topic_edit.toPlainText().strip()
        name = self.name_edit.text().strip()
        if not topic:
            self.status.setText("Please describe what to research.")
            return
        if not name:
            self.status.setText("Please give this a name — it names the audio file.")
            return

        from echo.research import DeepResearcher

        ok, reason = DeepResearcher().is_available()
        if not ok:
            self.status.setText(reason)
            QMessageBox.warning(self, "Deep Research", reason)
            return

        self.log_view.clear()
        self._running(True)
        self.status.setText("Researching… this takes 2–15 minutes. You can stop it.")

        self._worker = ResearchWorker(topic, name, self.agent_combo.currentData(),
                                      self.keep_check.isChecked())
        self._worker.message.connect(self.log_view.appendPlainText)
        self._worker.finished_ok.connect(self._done)
        self._worker.failed.connect(self._failed)
        self._worker.start()

    def _cancel(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            self.log_view.appendPlainText("Stopping…")
            self._worker.cancel()
            self._running(False)
            self.status.setText("Stopped.")
            return
        self.reject()

    def _done(self, result) -> None:
        self.result_research = result
        self.accept()

    def _failed(self, message: str) -> None:
        self._running(False)
        self.status.setText(message)
        QMessageBox.warning(self, "Deep Research", message)


class QueueDialog(QDialog):
    """What is converting now, and what waits behind it.

    Bound to a :class:`~gui.jobs.ConversionQueue` and refreshed on its
    ``changed`` signal, so the list stays live while jobs finish and start
    behind the (modal) dialog.
    """

    def __init__(self, queue: ConversionQueue, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Conversion queue")
        self.setModal(True)
        self.setMinimumSize(520, 360)
        self._queue = queue

        self.current_label = QLabel()
        self.current_label.setWordWrap(True)

        self.pending_list = QListWidget()
        self.pending_list.setAlternatingRowColors(True)
        self.pending_list.setWordWrap(True)
        self.pending_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.pending_list.itemSelectionChanged.connect(self._sync_buttons)

        self.remove_btn = QPushButton("Remove selected")
        self.remove_btn.clicked.connect(self._remove_selected)
        self.clear_btn = QPushButton("Clear queue")
        self.clear_btn.clicked.connect(self._queue.clear_pending)
        close_btn = QPushButton("Close")
        close_btn.setObjectName("primary")
        close_btn.setDefault(True)
        close_btn.clicked.connect(self.accept)

        buttons = QHBoxLayout()
        buttons.addWidget(self.remove_btn)
        buttons.addWidget(self.clear_btn)
        buttons.addStretch(1)
        buttons.addWidget(close_btn)

        now_heading = QLabel("Now converting")
        now_heading.setObjectName("sectionHeading")
        self.waiting_heading = QLabel("Waiting")
        self.waiting_heading.setObjectName("sectionHeading")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)
        layout.addWidget(now_heading)
        layout.addWidget(self.current_label)
        layout.addWidget(self.waiting_heading)
        layout.addWidget(self.pending_list, 1)
        layout.addLayout(buttons)

        self._queue.changed.connect(self._refresh)
        self._refresh()

    def _refresh(self) -> None:
        current = self._queue.current
        if current is not None:
            self.current_label.setText(f"{current.name}\n{current.detail}")
        else:
            self.current_label.setText("Nothing is converting.")

        pending = self._queue.pending
        self.waiting_heading.setText(f"Waiting ({len(pending)})" if pending else "Waiting")
        self.pending_list.clear()
        for i, job in enumerate(pending, start=1):
            item = QListWidgetItem(f"{i}. {job.name}")
            item.setToolTip(job.detail)
            self.pending_list.addItem(item)
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        self.remove_btn.setEnabled(self.pending_list.currentRow() >= 0)
        self.clear_btn.setEnabled(len(self._queue) > 0)

    def _remove_selected(self) -> None:
        row = self.pending_list.currentRow()
        if row >= 0:
            self._queue.remove(row)


class FitScrollArea(QScrollArea):
    """A scroll area whose size hint tracks its content.

    Plain QScrollArea reports a fixed default hint, which would force the tab
    pane to a size unrelated to its content (leaving a big empty gap). Reporting
    the inner widget's hint lets the pane hug its content, while a small minimum
    hint still allows it to shrink and scroll when the window is short.
    """

    def sizeHint(self):
        inner = self.widget()
        if inner is not None:
            fw = self.frameWidth() * 2
            hint = inner.sizeHint()
            return QSize(hint.width() + fw, hint.height() + fw)
        return super().sizeHint()


# --------------------------------------------------------------------------- #
# Convert File tab
# --------------------------------------------------------------------------- #
class ConvertTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        # The chosen source. The input field describes it; this holds the truth.
        self._source: gs.SourceSelection | None = None

        self.input_edit = QLineEdit()
        self.input_edit.setReadOnly(True)
        self.input_edit.setPlaceholderText("Choose a file, a Gutenberg book, or a research topic →")

        # One split button rather than three: clicking the body browses (the common
        # case), the arrow offers the other two sources.
        self.source_btn = QToolButton()
        self.source_btn.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.source_btn.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.source_btn.setCursor(Qt.PointingHandCursor)

        self.browse_action = QAction("Browse…", self)
        self.browse_action.setToolTip("Choose a PDF, EPUB, Markdown or text file")
        self.browse_action.triggered.connect(self._pick_input)
        self.gutenberg_action = QAction("Project Gutenberg…", self)
        self.gutenberg_action.setToolTip("Search Project Gutenberg for a free public-domain book")
        self.gutenberg_action.triggered.connect(self._pick_gutenberg)
        self.research_action = QAction("Deep Research…", self)
        self.research_action.setToolTip("Have Gemini research a topic, then narrate the report")
        self.research_action.triggered.connect(self._pick_research)

        source_menu = QMenu(self.source_btn)
        source_menu.addAction(self.browse_action)
        source_menu.addAction(self.gutenberg_action)
        source_menu.addAction(self.research_action)
        self.source_btn.setMenu(source_menu)
        # Browse is the default: pressing the button body does it directly.
        self.source_btn.setDefaultAction(self.browse_action)

        input_row = QHBoxLayout()
        input_row.setContentsMargins(0, 0, 0, 0)
        input_row.addWidget(self.input_edit, 1)
        input_row.addWidget(self.source_btn)

        # Engine choices come from the backend registry; unavailable ones stay
        # visible but disabled, with the reason in their tooltip.
        self.engine_combo = QComboBox()
        self._engine_choices = gv.engine_choices()
        for choice in self._engine_choices:
            self.engine_combo.addItem(choice.display, choice.name)
            row = self.engine_combo.count() - 1
            self.engine_combo.setItemData(row, choice.reason or choice.label, Qt.ToolTipRole)
            if not choice.available:
                model = self.engine_combo.model()
                model.item(row).setEnabled(False)
        start = self.engine_combo.findData(ec.DEFAULT_ENGINE)
        first_available = next((c.name for c in self._engine_choices if c.available), None)
        if start >= 0 and self._engine_choices[start].available:
            self.engine_combo.setCurrentIndex(start)
        elif first_available:
            self.engine_combo.setCurrentIndex(self.engine_combo.findData(first_available))
        self.engine_combo.currentIndexChanged.connect(self._on_engine_changed)

        self.voice_picker = VoicePicker(ec.DEFAULT_VOICE, engine=self.current_engine())
        self.speed = SpeedControl(float(ec.DEFAULT_SPEED))

        self.format_combo = QComboBox()
        for fmt in FORMATS:
            self.format_combo.addItem(FORMAT_BLURBS.get(fmt, fmt.upper()), fmt)
        fmt_idx = self.format_combo.findData(ec.DEFAULT_FORMAT)
        if fmt_idx >= 0:
            self.format_combo.setCurrentIndex(fmt_idx)
        self.format_combo.currentIndexChanged.connect(self._sync_output_suffix)

        self.output_edit = QLineEdit()
        output_browse = QPushButton("Browse…")
        output_browse.clicked.connect(self._pick_output)
        output_row = self._row(self.output_edit, output_browse)

        # A grid (rather than a form) so the "Voice:" label can span and center
        # against the two-row voice picker instead of top-aligning on its filters.
        form = QGridLayout()
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(12)
        form.setColumnStretch(1, 1)
        r = 0
        # "Source", not "Input file" — it may be a research topic or a catalogue entry.
        form.addWidget(QLabel("Source:"), r, 0, Qt.AlignLeft | Qt.AlignVCenter)
        form.addLayout(input_row, r, 1)
        r += 1
        form.addWidget(QLabel("Engine:"), r, 0, Qt.AlignLeft | Qt.AlignVCenter)
        form.addWidget(self.engine_combo, r, 1)
        r += 1
        form.addWidget(QLabel("Voice:"), r, 0, Qt.AlignLeft | Qt.AlignVCenter)
        form.addWidget(self.voice_picker, r, 1)  # tall; label centers against it
        r += 1
        form.addWidget(QLabel("Speed:"), r, 0, Qt.AlignLeft | Qt.AlignVCenter)
        form.addWidget(self.speed, r, 1)
        r += 1
        form.addWidget(QLabel("Format:"), r, 0, Qt.AlignLeft | Qt.AlignVCenter)
        form.addWidget(self.format_combo, r, 1)
        r += 1
        form.addWidget(QLabel("Output file:"), r, 0, Qt.AlignLeft | Qt.AlignVCenter)
        form.addLayout(output_row, r, 1)

        # Advanced settings live in a modal dialog opened by the status-bar gear.
        self.settings = SettingsDialog(self)

        self.convert_btn = QPushButton("Create audiobook")
        self.convert_btn.setObjectName("primary")  # accent-styled primary action
        self.convert_btn.setDefault(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addLayout(form)
        layout.addWidget(self.convert_btn)

    def open_settings(self) -> None:
        """Show the modal configuration dialog."""
        self.settings.exec()

    @staticmethod
    def _row(field, button=None) -> QHBoxLayout:
        """Zero-margin row: a stretching field + optional trailing button.

        Zeroing the margins keeps the row the same height as its label so the
        form label centers vertically against the field instead of top-aligning.
        """
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(field, 1)
        if button is not None:
            row.addWidget(button)
        return row

    def _set_source(self, source: gs.SourceSelection) -> None:
        """Adopt a chosen source: describe it, and rename the output after it."""
        self._source = source
        self.input_edit.setText(source.display)
        # setText leaves the cursor at the end, which scrolls a long description so
        # only its tail is visible. The beginning is the useful part.
        self.input_edit.setCursorPosition(0)
        self.input_edit.setToolTip(f"{source.display}\n\nReads: {source.path}")
        self.output_edit.clear()  # any previous output name no longer fits
        self._autofill_output()

        # Fill metadata the source knows about, without overwriting anything typed.
        if title := source.meta.get("title"):
            if not self.settings.title_edit.text().strip():
                self.settings.title_edit.setText(title)
        if author := source.meta.get("author"):
            if not self.settings.author_edit.text().strip():
                self.settings.author_edit.setText(author)
        if cover := source.meta.get("image_path"):
            if not self.settings.cover_edit.text().strip():
                self.settings.cover_edit.setText(str(cover))

    def _pick_input(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select input file", "", SUPPORTED_INPUTS)
        if not path:
            return
        self._set_source(gs.SourceSelection.from_file(path))

    def source_name(self) -> str:
        """The chosen source's display name — labels its job in the queue."""
        return self._source.name if self._source else ""

    def current_engine(self) -> str:
        return self.engine_combo.currentData() or ec.DEFAULT_ENGINE

    def current_format(self) -> str:
        return self.format_combo.currentData() or ec.DEFAULT_FORMAT

    def _on_engine_changed(self) -> None:
        """Repopulate the voice list for the newly chosen engine."""
        from echo.audio.engines import get_engine

        engine_name = self.current_engine()
        try:
            default_voice = get_engine(engine_name).default_voice()
        except Exception:
            default_voice = None
        self.voice_picker.set_engine(engine_name, default_voice)

    def _sync_output_suffix(self) -> None:
        """Keep the output path's extension in step with the chosen format."""
        current = self.output_edit.text().strip()
        if current:
            self.output_edit.setText(str(Path(current).with_suffix(f".{self.current_format()}")))

    def _pick_gutenberg(self) -> None:
        """Search Project Gutenberg, then use the download as the source.

        The catalogue also gives us title, author and cover art, so ``_set_source``
        fills the metadata fields in — without overwriting anything already typed.
        """
        dialog = GutenbergDialog(self)
        if dialog.exec() != QDialog.Accepted or dialog.result_book is None:
            return
        self._set_source(
            gs.SourceSelection.from_gutenberg(
                dialog.result_book,
                name=dialog.name_edit.text(),
                language=dialog.language_combo.currentText(),
            )
        )

    def _pick_research(self) -> None:
        """Run Gemini Deep Research, then narrate the report it produced."""
        dialog = ResearchDialog(self)
        if dialog.exec() != QDialog.Accepted or dialog.result_research is None:
            return
        self._set_source(gs.SourceSelection.from_research(dialog.result_research))

    def _autofill_output(self) -> None:
        """Name the output after the source's name, not its filename.

        A Gutenberg cache file is called ``pg2680_meditations.epub`` and a research
        report lives in a temp directory, so the source's own name is the only sane
        basis for the audio filename.
        """
        if self._source is None or self.output_edit.text().strip():
            return  # respect a path the user already chose
        out_dir = Path(ec.OUTPUT_FOLDER) if ec.OUTPUT_FOLDER else self._source.path.parent
        if self._source.kind != gs.FILE and not ec.OUTPUT_FOLDER:
            # Don't drop an audiobook into a temp or cache directory.
            out_dir = Path.home() / "Audiobooks"
        self.output_edit.setText(str(out_dir / f"{self._source.name}.{self.current_format()}"))

    def _pick_output(self) -> None:
        start = self.output_edit.text() or (ec.OUTPUT_FOLDER or "")
        fmt = self.current_format()
        path, _ = QFileDialog.getSaveFileName(
            self, f"Save {fmt.upper()} as", start, f"{fmt.upper()} audio (*.{fmt})"
        )
        if path:
            self.output_edit.setText(str(Path(path).with_suffix(f".{fmt}")))

    def gather(self) -> dict:
        """Validate and collect parameters for ``core.file_to_audio``.

        Raises ``ValueError`` with a user-facing message on invalid input.
        Advanced options are read from the (modal) settings dialog.
        """
        if self._source is None:
            raise ValueError(
                "Please choose a source first — a file, a Project Gutenberg book, or "
                "a Deep Research topic."
            )
        file_path = str(self._source.path)
        if not self._source.path.exists():
            raise ValueError(f"The chosen source is no longer on disk:\n{file_path}")

        output_path = self.output_edit.text().strip()
        if not output_path:
            raise ValueError("Please choose where to save the audiobook.")

        engine_name = self.current_engine()
        choice = next((c for c in self._engine_choices if c.name == engine_name), None)
        if choice is not None and not choice.available:
            raise ValueError(f"The {choice.label} engine needs setup first:\n\n{choice.reason}")

        s = self.settings
        # The source's own metadata sits underneath, so anything typed here wins.
        meta: dict = dict(self._source.meta)
        if s.title_edit.text().strip():
            meta["title"] = s.title_edit.text().strip()
        if s.author_edit.text().strip():
            meta["author"] = s.author_edit.text().strip()
        if s.cover_edit.text().strip():
            cover = s.cover_edit.text().strip()
            if not Path(cover).exists():
                raise ValueError(f"Cover image does not exist:\n{cover}")
            meta["image_path"] = cover
        elif meta.get("image_path") and not Path(meta["image_path"]).exists():
            meta.pop("image_path")  # a stale cached cover shouldn't fail the run

        normalizer_name = s.normalizer.currentData()
        if reason := s._normalizer_reasons.get(normalizer_name):
            raise ValueError(f"Text normalization is not available:\n\n{reason}")

        parser_configs = {
            "first_page": s.first_page.value(),
            "last_page": s.last_page.value(),
            "force_ocr": s.force_ocr.isChecked(),
            "use_docling": s.use_docling.isChecked(),
        }

        return dict(
            file_path=file_path,
            output_path=output_path,
            voice=self.voice_picker.current_voice(),
            speed=self.speed.value(),
            engine=engine_name,
            fmt=self.current_format(),
            normalizer=normalizer_name,
            meta=meta,
            save_text=s.save_text.isChecked(),
            write_transcript=s.write_transcript.isChecked(),
            resume=s.resume.isChecked(),
            parser_configs=parser_configs,
            log_level=s.verbosity.currentData(),
        )


# --------------------------------------------------------------------------- #
# Main window
# --------------------------------------------------------------------------- #
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("echo — text to audio")
        self.resize(780, 600)
        self.setMinimumSize(600, 460)
        self._worker = None  # keep a reference so the QThread isn't GC'd mid-run
        self._last_output = None  # most recent generated file, for the play button
        self.queue = ConversionQueue(self)
        self.queue.changed.connect(self._sync_queue_button)
        # Results of the batch being drained, reported once when the queue empties.
        self._batch: list[tuple[ConversionJob, bool, str]] = []

        self.convert_tab = ConvertTab()
        # Wrap in a scroll area so a small window scrolls rather than compressing
        # the fields.
        convert_area = self._scrollable(self.convert_tab)

        # --- status row: the status bar, plus separate icon buttons beside it ---
        self.progress = QProgressBar()
        self.progress.setTextVisible(True)
        self.progress.setFixedHeight(18)
        self.progress.setMinimumWidth(160)
        self.progress.setMaximumWidth(240)
        self.progress.setVisible(False)  # only shown while a job is running

        self.status = QLabel("Ready")
        status_label = QLabel("Status:")
        status_label.setObjectName("sectionHeading")

        status_bar = QFrame()
        status_bar.setObjectName("statusbar")
        sb = QHBoxLayout(status_bar)
        sb.setContentsMargins(12, 6, 12, 6)
        sb.setSpacing(8)
        sb.addWidget(status_label)
        sb.addWidget(self.status)
        sb.addStretch(1)
        sb.addWidget(self.progress)

        # Play button: reopen/play the most recently generated audiobook.
        self.play_btn = QToolButton()
        self.play_btn.setObjectName("iconbtn")
        self.play_btn.setText("♪")
        self.play_btn.setFixedSize(40, 34)
        self.play_btn.setCursor(Qt.PointingHandCursor)
        self.play_btn.setToolTip("Play the generated audiobook")
        self.play_btn.setEnabled(False)  # enabled once a file has been produced
        self.play_btn.clicked.connect(self._play_last)

        # Settings gear: opens the modal configuration dialog.
        self.gear = QToolButton()
        self.gear.setObjectName("iconbtn")
        self.gear.setText("⚙")
        self.gear.setFixedSize(40, 34)
        self.gear.setCursor(Qt.PointingHandCursor)
        self.gear.setToolTip("Conversion settings")
        self.gear.clicked.connect(self.convert_tab.open_settings)

        # Queue button: a count of what's waiting; clicking shows the details.
        self.queue_btn = QToolButton()
        self.queue_btn.setObjectName("iconbtn")
        self.queue_btn.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.queue_btn.setFixedHeight(34)
        self.queue_btn.setMinimumWidth(40)
        self.queue_btn.setCursor(Qt.PointingHandCursor)
        self.queue_btn.clicked.connect(self._show_queue)
        self._sync_queue_button()

        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        status_row.addWidget(status_bar, 1)
        status_row.addWidget(self.queue_btn)
        status_row.addWidget(self.play_btn)
        status_row.addWidget(self.gear)

        # --- output (~4 lines, grows if the window is enlarged) ---
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(5000)
        self.log_view.setPlaceholderText("Process output will appear here…")
        mono = QFont()
        mono.setStyleHint(QFont.Monospace)
        mono.setFamily("Menlo")  # preferred on macOS; style hint covers other OSes
        self.log_view.setFont(mono)
        self.log_view.setMinimumHeight(QFontMetrics(mono).lineSpacing() * 4 + 14)

        output_card = QFrame()
        output_card.setObjectName("card")
        out_layout = QVBoxLayout(output_card)
        out_layout.setContentsMargins(12, 10, 12, 12)
        out_layout.setSpacing(6)
        out_heading = QLabel("Output")
        out_heading.setObjectName("sectionHeading")
        out_layout.addWidget(out_heading)
        out_layout.addWidget(self.log_view, 1)

        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(10)
        outer.addWidget(convert_area, 0)  # hugs its content (no filler gap)
        outer.addLayout(status_row)
        outer.addWidget(output_card, 1)  # takes the slack; grows with the window
        self.setCentralWidget(central)

        # Wiring
        self.convert_tab.convert_btn.clicked.connect(self._on_convert)
        self.convert_tab.voice_picker.preview_btn.clicked.connect(
            lambda: self._preview(self.convert_tab.voice_picker, self.convert_tab.speed)
        )

    # -- helpers ----------------------------------------------------------- #
    @staticmethod
    def _scrollable(widget: QWidget) -> QScrollArea:
        sa = FitScrollArea()  # size hint tracks content so the pane hugs it
        sa.setWidgetResizable(True)  # inner widget keeps its width, scrolls in y
        sa.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        sa.setFrameShape(QFrame.NoFrame)
        sa.setWidget(widget)
        return sa

    def _append_log(self, line: str) -> None:
        self.log_view.appendPlainText(line)

    def _on_progress(self, pct: int) -> None:
        if self.progress.maximum() == 0:  # was in "busy" mode
            self.progress.setRange(0, 100)
        self.progress.setValue(pct)

    def _busy(self, running: bool, status: str = "") -> None:
        """Toggle UI enabled state and show the progress bar only while running.

        The convert button stays enabled on purpose: while a job runs, clicking
        it queues the next one.
        """
        self.convert_tab.voice_picker.preview_btn.setEnabled(not running)
        self.progress.setVisible(running)
        if running:
            self.progress.setRange(0, 0)  # indeterminate until first % arrives
        if status:
            self.status.setText(status)

    def _start(self, worker, start_status: str) -> None:
        """Run a one-off worker (a preview) that isn't part of the queue."""
        self._worker = worker
        worker.message.connect(self._append_log)
        worker.progress.connect(self._on_progress)
        worker.succeeded.connect(self._on_success)
        worker.failed.connect(self._on_failure)
        worker.finished.connect(self._on_worker_finished)
        self.log_view.clear()
        self.status.setText(start_status)
        self._busy(True)
        worker.start()

    def _play_last(self) -> None:
        if self._last_output and Path(self._last_output).exists():
            open_in_default_app(Path(self._last_output))
        else:
            QMessageBox.information(self, "No file", "No generated audio file to play yet.")

    def _on_success(self, path: str) -> None:
        self._busy(False, f"Done → {path}")
        self._last_output = path
        self.play_btn.setEnabled(True)
        self._show_created(path)

    def _show_created(self, path: str) -> None:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Information)
        box.setWindowTitle("Success")
        box.setText("Audio file created:")
        box.setInformativeText(path)
        open_btn = box.addButton("Open file", QMessageBox.AcceptRole)
        box.addButton("Close", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is open_btn:
            open_in_default_app(Path(path))

    def _on_failure(self, message: str) -> None:
        self._busy(False)
        self.status.setText("Failed.")
        QMessageBox.critical(self, "Error", message)

    # -- the queue ----------------------------------------------------------- #
    def _sync_queue_button(self) -> None:
        waiting = len(self.queue)
        self.queue_btn.setText(f"≡ {waiting}" if waiting else "≡")
        noun = f"{waiting} waiting" if waiting else "empty"
        self.queue_btn.setToolTip(f"Conversion queue — {noun}")

    def _show_queue(self) -> None:
        QueueDialog(self.queue, self).exec()

    def _maybe_start_next(self) -> None:
        if self._worker is not None:
            return
        job = self.queue.pop_next()
        if job is not None:
            self._start_conversion(job)

    def _start_conversion(self, job: ConversionJob) -> None:
        worker = ConversionWorker(**job.params)
        self._worker = worker
        worker.message.connect(self._append_log)
        worker.progress.connect(self._on_progress)
        worker.succeeded.connect(self._on_job_success)
        worker.failed.connect(self._on_job_failure)
        worker.finished.connect(self._on_worker_finished)
        if self._batch:
            self._append_log(f"— {job.name} —")
        else:
            self.log_view.clear()  # first job of a fresh batch
        self.status.setText(f"Converting {job.name}…")
        self._busy(True)
        worker.start()

    def _on_job_success(self, path: str) -> None:
        self._batch.append((self.queue.current, True, path))
        self._last_output = path
        self.play_btn.setEnabled(True)
        self.status.setText(f"Done → {path}")

    def _on_job_failure(self, message: str) -> None:
        job = self.queue.current
        self._batch.append((job, False, message))
        self.status.setText(f"Failed: {job.name}" if job else "Failed.")

    def _on_worker_finished(self) -> None:
        """One worker ended (conversion or preview): advance the queue."""
        self._worker = None
        if self.queue.current is not None:
            self.queue.finish_current()
        job = self.queue.pop_next()
        if job is not None:
            self._start_conversion(job)
            return
        if self._batch:
            self._busy(False)
            self._finish_batch()

    def _finish_batch(self) -> None:
        """Report the drained queue: one dialog for the batch, not one per book."""
        results, self._batch = self._batch, []
        if len(results) == 1:
            job, ok, payload = results[0]
            if ok:
                self._show_created(payload)
            else:
                QMessageBox.critical(self, "Error", payload)
            return

        failures = [r for r in results if not r[1]]
        lines = [
            f"✓ {job.name} → {payload}" if ok else f"✗ {job.name}: {payload}"
            for job, ok, payload in results
        ]
        self.status.setText(f"Queue finished — {len(results) - len(failures)} of {len(results)} succeeded.")
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning if failures else QMessageBox.Information)
        box.setWindowTitle("Queue finished")
        box.setText(f"{len(results) - len(failures)} of {len(results)} audiobooks created.")
        box.setInformativeText("\n".join(lines))
        box.exec()

    # -- actions ----------------------------------------------------------- #
    def _on_convert(self) -> None:
        try:
            params = self.convert_tab.gather()
        except ValueError as exc:
            QMessageBox.warning(self, "Missing information", str(exc))
            return
        if self.queue.holds_output(params["output_path"]):
            QMessageBox.information(
                self,
                "Already queued",
                f"A queued conversion already writes to:\n{params['output_path']}\n\n"
                "Change the output file to queue this again.",
            )
            return
        job = ConversionJob(name=self.convert_tab.source_name(), params=params)
        self.queue.add(job)
        if self._worker is not None:
            self._append_log(f"Queued: {job.name} ({len(self.queue)} waiting)")
        self._maybe_start_next()

    def _preview(self, picker: VoicePicker, speed: SpeedControl) -> None:
        voice = picker.current_voice()
        if not voice:
            QMessageBox.warning(self, "No voice", "Please select a voice to preview.")
            return
        engine = self.convert_tab.current_engine()
        self._start(PreviewWorker(voice, speed.value(), engine=engine), f"Previewing {voice}…")


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("echo")
    apply_theme(app)

    # Locate ffmpeg up front (bundled with a frozen build, otherwise on PATH) so a
    # missing install is reported before a conversion has run.
    from echo.audio.mp3_utils import configure_ffmpeg

    if configure_ffmpeg() is None:
        logging.getLogger("echo").warning(
            "ffmpeg was not found — audio cannot be assembled. Install it with "
            "`brew install ffmpeg`."
        )

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
