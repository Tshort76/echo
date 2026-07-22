"""echo desktop GUI — a PySide6 front end for the file→MP3 and Deep Research flows.

Run via ``python echo_gui.py`` from the repo root. This module imports the
``echo`` backend but the backend never imports it: the CLI keeps working with no
knowledge that a GUI exists.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QFont, QFontMetrics
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
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QStyle,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

import echo.constants as ec
from gui import voices as gv
from gui.style import apply_theme
from gui.workers import (
    ConversionWorker,
    PreviewWorker,
    open_in_default_app,
)
# DeepResearchWorker is intentionally not imported here — the Deep Research UI is
# parked (see DeepResearchTab / MainWindow). Re-add it when restoring the tab.

SUPPORTED_INPUTS = "Supported files (*.txt *.md *.pdf *.epub);;All files (*)"


# --------------------------------------------------------------------------- #
# Reusable widgets
# --------------------------------------------------------------------------- #
class SpeedControl(QWidget):
    """A slider + label for the playback-speed multiplier (0.5×–3.0×, step 0.05)."""

    _MIN, _MAX, _STEP = 0.5, 3.0, 0.05

    def __init__(self, initial: float = 1.25, parent=None):
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

    def __init__(self, default_voice: str, parent=None):
        super().__init__(parent)
        self.setObjectName("voicebox")
        self._all_voices = gv.load_voices()
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

        if not self._all_voices:
            # No cache available — fall back to free-text entry.
            self.voice_combo.setEditable(True)
            self.voice_combo.setEditText(default_voice)

        self.gender_combo.addItems(["All", "Female", "Male"])
        self.lang_combo.addItem("All", None)
        for lang in gv.languages(self._all_voices):
            self.lang_combo.addItem(lang, lang)

        # Preselect the default voice's language, if we can find it.
        default = next((v for v in self._all_voices if v.short_name == default_voice), None)
        if default:
            idx = self.lang_combo.findData(default.language)
            if idx >= 0:
                self.lang_combo.setCurrentIndex(idx)

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
            self.voice_combo.addItem(v.display, v.short_name)
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

        meta_form = QFormLayout()
        meta_form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        meta_form.setVerticalSpacing(10)
        meta_form.addRow("Title:", self.title_edit)
        meta_form.addRow("Author:", self.author_edit)
        meta_form.addRow("Cover image:", cover_row)
        meta_form.addRow("PDF page range:", page_row)

        # --- Output & visibility ---
        self.save_text = QCheckBox("Save the cleaned intermediate text (.txt)")
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
        vis_form.addRow("Output verbosity:", verb_row)

        meta_heading = QLabel("Metadata")
        meta_heading.setObjectName("sectionHeading")
        vis_heading = QLabel("Output & visibility")
        vis_heading.setObjectName("sectionHeading")

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


class FitTabWidget(QTabWidget):
    """A tab widget sized to the *current* page rather than the tallest page.

    Parked: currently unused (the UI shows only the Convert view). Kept for when
    the Deep Research tab is restored alongside Convert.

    The default hint is the max over all pages, which would stretch the short
    tab's pane to the tall tab's height and leave an empty gap. Tracking the
    current page keeps the pane hugging what's actually shown.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.currentChanged.connect(lambda _: self.updateGeometry())

    def sizeHint(self):
        page = self.currentWidget()
        if page is not None:
            tab_h = self.tabBar().sizeHint().height()
            hint = page.sizeHint()
            return QSize(hint.width(), hint.height() + tab_h)
        return super().sizeHint()


# --------------------------------------------------------------------------- #
# Convert File tab
# --------------------------------------------------------------------------- #
class ConvertTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.input_edit = QLineEdit()
        input_browse = QPushButton("Browse…")
        input_browse.clicked.connect(self._pick_input)
        input_row = self._row(self.input_edit, input_browse)

        self.voice_picker = VoicePicker(ec.DEFAULT_VOICE)
        self.speed = SpeedControl(float(ec.DEFAULT_SPEED))

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
        form.addWidget(QLabel("Input file:"), r, 0, Qt.AlignLeft | Qt.AlignVCenter)
        form.addLayout(input_row, r, 1)
        r += 1
        form.addWidget(QLabel("Voice:"), r, 0, Qt.AlignLeft | Qt.AlignVCenter)
        form.addWidget(self.voice_picker, r, 1)  # tall; label centers against it
        r += 1
        form.addWidget(QLabel("Speed:"), r, 0, Qt.AlignLeft | Qt.AlignVCenter)
        form.addWidget(self.speed, r, 1)
        r += 1
        form.addWidget(QLabel("Output MP3:"), r, 0, Qt.AlignLeft | Qt.AlignVCenter)
        form.addLayout(output_row, r, 1)

        # Advanced settings live in a modal dialog opened by the status-bar gear.
        self.settings = SettingsDialog(self)

        self.convert_btn = QPushButton("Convert to MP3")
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

    def _pick_input(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select input file", "", SUPPORTED_INPUTS)
        if not path:
            return
        self.input_edit.setText(path)
        self._autofill_output(path)

    def _autofill_output(self, input_path: str) -> None:
        if self.output_edit.text().strip():
            return  # respect a path the user already chose
        src = Path(input_path)
        out_dir = Path(ec.OUTPUT_FOLDER) if ec.OUTPUT_FOLDER else src.parent
        self.output_edit.setText(str(out_dir / f"{src.stem}.mp3"))

    def _pick_output(self) -> None:
        start = self.output_edit.text() or (ec.OUTPUT_FOLDER or "")
        path, _ = QFileDialog.getSaveFileName(self, "Save MP3 as", start, "MP3 audio (*.mp3)")
        if path:
            if not path.lower().endswith(".mp3"):
                path += ".mp3"
            self.output_edit.setText(path)

    def gather(self) -> dict:
        """Validate and collect parameters for ``core.file_to_mp3``.

        Raises ``ValueError`` with a user-facing message on invalid input.
        Advanced options are read from the (modal) settings dialog.
        """
        file_path = self.input_edit.text().strip()
        if not file_path:
            raise ValueError("Please choose an input file.")
        if not Path(file_path).exists():
            raise ValueError(f"Input file does not exist:\n{file_path}")

        output_path = self.output_edit.text().strip()
        if not output_path:
            raise ValueError("Please choose an output MP3 path.")

        s = self.settings
        meta: dict = {}
        if s.title_edit.text().strip():
            meta["title"] = s.title_edit.text().strip()
        if s.author_edit.text().strip():
            meta["author"] = s.author_edit.text().strip()
        if s.cover_edit.text().strip():
            cover = s.cover_edit.text().strip()
            if not Path(cover).exists():
                raise ValueError(f"Cover image does not exist:\n{cover}")
            meta["image_path"] = cover

        parser_configs = {
            "first_page": s.first_page.value(),
            "last_page": s.last_page.value(),
        }

        return dict(
            file_path=file_path,
            output_path=output_path,
            voice=self.voice_picker.current_voice(),
            speed=self.speed.value(),
            meta=meta,
            save_text=s.save_text.isChecked(),
            parser_configs=parser_configs,
            log_level=s.verbosity.currentData(),
        )


# --------------------------------------------------------------------------- #
# Deep Research tab
# --------------------------------------------------------------------------- #
class DeepResearchTab(QWidget):
    """Parked: not currently shown in the UI (Deep Research was temporarily
    removed). Left intact — along with FitTabWidget and DeepResearchWorker — so
    the tab can be re-added to MainWindow without rebuilding it."""

    def __init__(self, parent=None):
        super().__init__(parent)

        note = QLabel(
            "Generate audio from a Gemini Deep Research topic, or convert an "
            "existing research .txt file.\n"
            "Topic mode requires <b>google-generativeai</b> installed and "
            "<b>GEMINI_API_KEY</b> set in your environment/.env."
        )
        note.setTextFormat(Qt.RichText)  # render the <b> emphasis, not literal tags
        note.setWordWrap(True)

        self.topic_radio = QRadioButton("Research a topic with Gemini")
        self.text_radio = QRadioButton("Convert an existing research .txt file")
        self.topic_radio.setChecked(True)
        self.topic_radio.toggled.connect(self._sync_mode)

        # Topic-mode fields
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Short name used for output files, e.g. quantum_computing")
        self.topic_edit = QPlainTextEdit()
        self.topic_edit.setPlaceholderText("Describe the topic to research…")
        self.topic_edit.setMinimumHeight(90)

        # Text-mode field
        self.text_edit = QLineEdit()
        text_browse = QPushButton("Browse…")
        text_browse.clicked.connect(self._pick_text)
        text_row = ConvertTab._row(self.text_edit, text_browse)

        self.voice_picker = VoicePicker(ec.DEFAULT_VOICE)
        self.speed = SpeedControl(1.5)  # matches the deep-research CLI default

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        form.setVerticalSpacing(10)
        form.addRow(self.topic_radio)
        form.addRow("Name:", self.name_edit)
        form.addRow("Topic:", self.topic_edit)
        form.addRow(self.text_radio)
        form.addRow("Research file:", text_row)
        form.addRow("Voice:", self.voice_picker)
        form.addRow("Speed:", self.speed)

        self.run_btn = QPushButton("Generate audio")
        self.run_btn.setObjectName("primary")  # accent-styled primary action

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(note)
        layout.addLayout(form)
        layout.addWidget(self.run_btn)
        layout.addStretch(1)  # keep content top-aligned

        self._sync_mode()

    def _sync_mode(self) -> None:
        topic_mode = self.topic_radio.isChecked()
        self.name_edit.setEnabled(topic_mode)
        self.topic_edit.setEnabled(topic_mode)
        self.text_edit.setEnabled(not topic_mode)

    def _pick_text(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select research text file", "", "Text files (*.txt)")
        if path:
            self.text_edit.setText(path)
            if not self.name_edit.text().strip():
                self.name_edit.setText(Path(path).stem)

    def gather(self) -> dict:
        if self.topic_radio.isChecked():
            name = self.name_edit.text().strip()
            topic = self.topic_edit.toPlainText().strip()
            if not name:
                raise ValueError("Please provide a short name for the research.")
            if not topic:
                raise ValueError("Please describe the topic to research.")
            return dict(
                mode="topic",
                name=name,
                topic=topic,
                text_path="",
                voice=self.voice_picker.current_voice(),
                speed=self.speed.value(),
            )
        text_path = self.text_edit.text().strip()
        if not text_path or not Path(text_path).exists():
            raise ValueError("Please choose an existing research .txt file.")
        return dict(
            mode="text",
            name=Path(text_path).stem,
            topic="",
            text_path=text_path,
            voice=self.voice_picker.current_voice(),
            speed=self.speed.value(),
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
        self._last_output = None  # most recent generated MP3, for the play button

        self.convert_tab = ConvertTab()
        # Deep Research is temporarily removed from the UI; the Convert view is the
        # whole window. DeepResearchTab / DeepResearchWorker (and FitTabWidget) are
        # left in the codebase so the tab can be restored later.
        # Wrap in a scroll area so expanding the advanced settings (or a small
        # window) scrolls rather than compressing the fields.
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

        # Play button: reopen/play the most recently generated MP3.
        self.play_btn = QToolButton()
        self.play_btn.setObjectName("iconbtn")
        self.play_btn.setText("♪")
        self.play_btn.setFixedSize(40, 34)
        self.play_btn.setCursor(Qt.PointingHandCursor)
        self.play_btn.setToolTip("Play the generated MP3")
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

        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        status_row.addWidget(status_bar, 1)
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
        """Toggle UI enabled state and show the progress bar only while running."""
        self.convert_tab.convert_btn.setEnabled(not running)
        self.convert_tab.voice_picker.preview_btn.setEnabled(not running)
        self.progress.setVisible(running)
        if running:
            self.progress.setRange(0, 0)  # indeterminate until first % arrives
        if status:
            self.status.setText(status)

    def _start(self, worker, start_status: str) -> None:
        self._worker = worker
        worker.message.connect(self._append_log)
        worker.progress.connect(self._on_progress)
        worker.succeeded.connect(self._on_success)
        worker.failed.connect(self._on_failure)
        worker.finished.connect(lambda: setattr(self, "_worker", None))
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

    # -- actions ----------------------------------------------------------- #
    def _on_convert(self) -> None:
        try:
            params = self.convert_tab.gather()
        except ValueError as exc:
            QMessageBox.warning(self, "Missing information", str(exc))
            return
        self._start(ConversionWorker(**params), "Converting…")

    def _preview(self, picker: VoicePicker, speed: SpeedControl) -> None:
        voice = picker.current_voice()
        if not voice:
            QMessageBox.warning(self, "No voice", "Please select a voice to preview.")
            return
        self._start(PreviewWorker(voice, speed.value()), f"Previewing {voice}…")


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("echo")
    apply_theme(app)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
