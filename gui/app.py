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
from gui import voices as gv
from gui.style import apply_theme
from gui.workers import (
    ConversionWorker,
    PreviewWorker,
    open_in_default_app,
)

SUPPORTED_INPUTS = "Supported files (*.txt *.md *.pdf *.epub);;All files (*)"
FORMAT_BLURBS = {
    "m4b": "M4B — audiobook with chapter marks",
    "mp3": "MP3 — plays everywhere, no chapters",
}


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

        # --- Narration ---
        self.normalizer = QComboBox()
        self.normalizer.addItem("Off — deterministic rules only", "off")
        self.normalizer.addItem("Local model (LM Studio / Ollama)", "local")
        self.normalizer.addItem("Gemini (needs GEMINI_API_KEY)", "gemini")
        idx = self.normalizer.findData(ec.NORMALIZER)
        if idx >= 0:
            self.normalizer.setCurrentIndex(idx)
        self.normalizer.setToolTip(
            "Optional: have a language model expand abbreviations, numbers and "
            "symbols into spoken words. Guarded so it cannot rewrite your prose."
        )
        norm_row = QHBoxLayout()
        norm_row.setContentsMargins(0, 0, 0, 0)
        norm_row.addWidget(self.normalizer, 1)

        # --- Output & visibility ---
        self.save_text = QCheckBox("Save the narrated text (.txt)")
        self.write_transcript = QCheckBox("Save a timed transcript (.srt), when available")
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
        vis_form.addRow("Output verbosity:", verb_row)

        norm_form = QFormLayout()
        norm_form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        norm_form.setVerticalSpacing(10)
        norm_form.addRow("Text normalization:", norm_row)

        meta_heading = QLabel("Metadata")
        meta_heading.setObjectName("sectionHeading")
        norm_heading = QLabel("Narration")
        norm_heading.setObjectName("sectionHeading")
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

        self.input_edit = QLineEdit()
        input_browse = QPushButton("Browse…")
        input_browse.clicked.connect(self._pick_input)
        input_row = self._row(self.input_edit, input_browse)

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
        form.addWidget(QLabel("Input file:"), r, 0, Qt.AlignLeft | Qt.AlignVCenter)
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

    def _pick_input(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select input file", "", SUPPORTED_INPUTS)
        if not path:
            return
        self.input_edit.setText(path)
        self._autofill_output(path)

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

    def _autofill_output(self, input_path: str) -> None:
        if self.output_edit.text().strip():
            return  # respect a path the user already chose
        src = Path(input_path)
        out_dir = Path(ec.OUTPUT_FOLDER) if ec.OUTPUT_FOLDER else src.parent
        self.output_edit.setText(str(out_dir / f"{src.stem}.{self.current_format()}"))

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
        file_path = self.input_edit.text().strip()
        if not file_path:
            raise ValueError("Please choose an input file.")
        if not Path(file_path).exists():
            raise ValueError(f"Input file does not exist:\n{file_path}")

        output_path = self.output_edit.text().strip()
        if not output_path:
            raise ValueError("Please choose where to save the audiobook.")

        engine_name = self.current_engine()
        choice = next((c for c in self._engine_choices if c.name == engine_name), None)
        if choice is not None and not choice.available:
            raise ValueError(f"The {choice.label} engine needs setup first:\n\n{choice.reason}")

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
            engine=engine_name,
            fmt=self.current_format(),
            normalizer=s.normalizer.currentData(),
            meta=meta,
            save_text=s.save_text.isChecked(),
            write_transcript=s.write_transcript.isChecked(),
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
