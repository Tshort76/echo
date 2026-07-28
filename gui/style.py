"""Visual theme for the echo GUI.

A single Qt Style Sheet (QSS) that gives the app a warm, rounded, "Claude
artifact" look — cream paper surfaces, a coral accent, soft borders, and
friendlier controls — instead of the flat default widgets. Applied globally in
``gui.app.main`` via ``apply_theme(app)``; nothing else in the UI hard-codes
colors, so the palette below is the single place to retune the look.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen
from PySide6.QtWidgets import QApplication

log = logging.getLogger(__name__)

# --- palette -------------------------------------------------------------- #
BG = "#F5F4EE"  # warm paper (window background)
SURFACE = "#FFFFFF"  # cards, inputs, tab pane
SURFACE_ALT = "#FBFAF6"  # log panel / subtle surfaces
BORDER = "#E4E2D8"  # hairline borders
BORDER_STRONG = "#D3D0C4"  # input borders
TEXT = "#2B2A26"  # primary text
MUTED = "#8A867B"  # secondary text / unselected tabs / disabled
ACCENT = "#D97757"  # coral — primary actions, focus, selection
ACCENT_HOVER = "#C96442"
ACCENT_PRESSED = "#B5563A"
ACCENT_SOFT = "#F0DFD6"  # light coral tint (list selection)
ACCENT_DISABLED = "#E7C4B6"

# Width of the drop-down well on a QComboBox. Also sets the combo's right padding,
# so a long voice id is never drawn underneath the chevron.
_ARROW_WELL = 24
_CHEVRON_PX = 13

# Preferred UI fonts per platform; QFont.setFamilies falls back left→right.
_FONT_STACK = [
    ".AppleSystemUIFont",
    "SF Pro Text",
    "Segoe UI",
    "Inter",
    "Helvetica Neue",
    "Arial",
]


def chevron_asset(color: str = MUTED, size: int = _CHEVRON_PX) -> Path | None:
    """Paint a downward chevron to a PNG and return its path, or None on failure.

    A QComboBox needs an *image* for its arrow: as soon as ``::drop-down`` is styled
    at all, Qt stops drawing its own indicator, and a stylesheet cannot describe a
    glyph. Rather than ship an asset — one more file to resolve in a frozen build —
    draw it here and cache it under the temp directory. The filename encodes colour
    and size, so repeated runs reuse one file instead of leaking a new one each time.

    Returning None rather than raising matters: the caller then leaves ``::drop-down``
    unstyled and Qt's native arrow reappears. An unwritable temp directory should cost
    a nicer glyph, not the affordance itself — which is exactly the bug this replaces.
    """
    path = Path(tempfile.gettempdir()) / "echo-ui" / f"chevron-{color.lstrip('#')}-{size}.png"
    if path.exists():
        return path

    scale = 3  # supersample, so the downscale to 1x/2x stays crisp
    px = size * scale
    image = QImage(px, px, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    try:
        painter.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor(color))
        pen.setWidthF(1.7 * scale)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.drawPolyline(
            [QPointF(px * 0.24, px * 0.40), QPointF(px * 0.50, px * 0.64), QPointF(px * 0.76, px * 0.40)]
        )
    finally:
        painter.end()  # before save(), or the image is still owned by the painter

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if image.save(str(path), "PNG"):
            return path
        log.debug("Could not write the combo-box chevron to %s; using Qt's own arrow.", path)
    except OSError as ex:
        log.debug("Could not write the combo-box chevron (%s); using Qt's own arrow.", ex)
    return None


def _combo_rules(chevron: Path | None) -> str:
    """Styling that makes a QComboBox read as a dropdown rather than a text field.

    Skipped entirely when there is no chevron to draw. Styling ``::drop-down`` without
    supplying an image removes Qt's indicator and leaves a control indistinguishable
    from a QLineEdit, so no styling is strictly better than half of it.
    """
    if chevron is None:
        return ""
    # Qt places a *state-dependent* arrow image by the widget rect rather than the
    # drop-down rect, painting a second chevron over the text. So one image, no
    # :hover / :disabled variants — hover feedback comes from the border instead.
    return f"""
    QComboBox {{ padding-right: {_ARROW_WELL + 8}px; }}
    QComboBox::drop-down {{
        subcontrol-origin: padding;
        subcontrol-position: center right;
        width: {_ARROW_WELL}px;
        border: none;
        border-left: 1px solid {BORDER};
        background: transparent;
    }}
    QComboBox::down-arrow {{
        image: url("{chevron.as_posix()}");
        width: {_CHEVRON_PX}px;
        height: {_CHEVRON_PX}px;
    }}
    QComboBox:hover {{ border-color: {ACCENT}; }}
    """


def _stylesheet() -> str:
    return f"""
    QMainWindow, QWidget {{
        background-color: {BG};
        color: {TEXT};
    }}
    QLabel {{ background: transparent; }}

    /* ---- Tabs ---- */
    QTabWidget::pane {{
        border: 1px solid {BORDER};
        border-radius: 12px;
        background: {SURFACE};
        top: -1px;
    }}
    QTabBar::tab {{
        background: transparent;
        color: {MUTED};
        padding: 8px 18px;
        margin-right: 4px;
        border: 1px solid transparent;
        border-radius: 8px;
        font-weight: 600;
    }}
    QTabBar::tab:selected {{
        background: {SURFACE};
        color: {TEXT};
        border: 1px solid {BORDER};
    }}
    QTabBar::tab:hover:!selected {{ color: {TEXT}; }}

    /* ---- Group boxes ---- */
    QGroupBox {{
        background: {SURFACE};
        border: 1px solid {BORDER};
        border-radius: 12px;
        margin-top: 14px;
        padding: 14px 14px 10px 14px;
        font-weight: 600;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        subcontrol-position: top left;
        left: 12px;
        padding: 0 6px;
        color: {TEXT};
    }}

    /* ---- Text inputs ---- */
    QLineEdit, QPlainTextEdit, QComboBox, QSpinBox {{
        background: {SURFACE};
        border: 1px solid {BORDER_STRONG};
        border-radius: 8px;
        padding: 6px 10px;
        color: {TEXT};
        selection-background-color: {ACCENT};
        selection-color: #FFFFFF;
    }}
    QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus {{
        border: 1px solid {ACCENT};
    }}
    QLineEdit:disabled, QPlainTextEdit:disabled,
    QComboBox:disabled, QSpinBox:disabled {{
        background: #F2F1EB;
        color: #A9A59B;
    }}
    QPlainTextEdit {{ background: {SURFACE_ALT}; }}

    /* ---- Combo boxes: a chevron and a divider, so they read as dropdowns ---- */
    {_combo_rules(chevron_asset())}

    /* ---- Combo popup ---- */
    QComboBox QAbstractItemView {{
        background: {SURFACE};
        border: 1px solid {BORDER};
        border-radius: 8px;
        padding: 4px;
        selection-background-color: {ACCENT_SOFT};
        selection-color: {TEXT};
        outline: none;
    }}

    /* ---- Buttons (secondary by default) ---- */
    QPushButton {{
        background: {SURFACE};
        border: 1px solid {BORDER_STRONG};
        border-radius: 8px;
        padding: 7px 14px;
        color: {TEXT};
        font-weight: 600;
    }}
    QPushButton:hover {{ background: #F2F1EB; border-color: #C4C0B4; }}
    QPushButton:pressed {{ background: #E9E7DF; }}
    QPushButton:disabled {{
        color: #A9A59B; background: #F2F1EB; border-color: {BORDER};
    }}

    /* ---- Primary buttons (Convert / Generate) ---- */
    QPushButton#primary {{
        background: {ACCENT};
        border: 1px solid {ACCENT};
        color: #FFFFFF;
        padding: 9px 18px;
    }}
    QPushButton#primary:hover {{
        background: {ACCENT_HOVER}; border-color: {ACCENT_HOVER};
    }}
    QPushButton#primary:pressed {{
        background: {ACCENT_PRESSED}; border-color: {ACCENT_PRESSED};
    }}
    QPushButton#primary:disabled {{
        background: {ACCENT_DISABLED}; border-color: {ACCENT_DISABLED};
        color: #FFFFFF;
    }}

    /* ---- Collapsible "advanced" disclosure ---- */
    QToolButton#disclosure {{
        background: transparent;
        border: none;
        padding: 4px 2px;
        color: {TEXT};
        font-weight: 600;
    }}
    QToolButton#disclosure:hover {{ color: {ACCENT}; }}
    QToolButton#iconbtn {{
        background: {SURFACE};
        border: 1px solid {BORDER_STRONG};
        border-radius: 8px;
        font-size: 17px;
        color: {TEXT};
    }}
    QToolButton#iconbtn:hover {{ border-color: {ACCENT}; color: {ACCENT}; }}
    QToolButton#iconbtn:checked {{
        background: {ACCENT}; border-color: {ACCENT}; color: #FFFFFF;
    }}
    QToolButton#iconbtn:disabled {{
        background: #F2F1EB; border-color: {BORDER}; color: #BEBAB0;
    }}
    QFrame#card {{
        background: {SURFACE};
        border: 1px solid {BORDER};
        border-radius: 12px;
    }}
    QLabel#sectionHeading {{
        color: {MUTED};
        font-weight: 700;
    }}
    QFrame#voicebox {{
        border: 1px solid {BORDER_STRONG};
        border-radius: 10px;
        background: transparent;
    }}
    QFrame#statusbar {{
        background: {SURFACE};
        border: 1px solid {BORDER};
        border-radius: 10px;
    }}

    /* ---- Checkboxes / radios / group check ---- */
    QCheckBox, QRadioButton {{ background: transparent; spacing: 8px; }}
    QCheckBox::indicator, QRadioButton::indicator, QGroupBox::indicator {{
        width: 18px; height: 18px;
        border: 1px solid {BORDER_STRONG};
        background: {SURFACE};
    }}
    QCheckBox::indicator, QGroupBox::indicator {{ border-radius: 5px; }}
    QRadioButton::indicator {{ border-radius: 9px; }}
    QCheckBox::indicator:checked, QGroupBox::indicator:checked,
    QRadioButton::indicator:checked {{
        background: {ACCENT}; border-color: {ACCENT};
    }}
    QCheckBox::indicator:hover, QRadioButton::indicator:hover,
    QGroupBox::indicator:hover {{ border-color: {ACCENT}; }}

    /* ---- Slider ---- */
    QSlider::groove:horizontal {{
        height: 6px; background: {BORDER}; border-radius: 3px;
    }}
    QSlider::sub-page:horizontal {{
        background: {ACCENT}; border-radius: 3px;
    }}
    QSlider::handle:horizontal {{
        background: {SURFACE};
        border: 2px solid {ACCENT};
        width: 16px; height: 16px;
        margin: -7px 0;
        border-radius: 9px;
    }}
    QSlider::handle:horizontal:hover {{ background: #FBEDE7; }}

    /* ---- Progress bar ---- */
    QProgressBar {{
        border: 1px solid {BORDER};
        border-radius: 8px;
        background: {SURFACE};
        text-align: center;
        color: {TEXT};
        min-height: 18px;
    }}
    QProgressBar::chunk {{
        background: {ACCENT};
        border-radius: 7px;
        margin: 1px;
    }}

    /* ---- Scrollbars ---- */
    QScrollBar:vertical {{
        background: transparent; width: 10px; margin: 2px;
    }}
    QScrollBar::handle:vertical {{
        background: {BORDER_STRONG}; border-radius: 5px; min-height: 24px;
    }}
    QScrollBar::handle:vertical:hover {{ background: #BDB9AC; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
        background: transparent;
    }}

    /* ---- Tooltips ---- */
    QToolTip {{
        background: {TEXT}; color: #FFFFFF;
        border: none; border-radius: 6px; padding: 5px 8px;
    }}
    """


def apply_theme(app: QApplication) -> None:
    """Apply the echo theme to ``app`` (Fusion base + font + stylesheet)."""
    # Fusion is a consistent, fully style-sheet-able base across macOS & Windows,
    # so the QSS below renders the same everywhere rather than fighting the
    # native platform styles.
    app.setStyle("Fusion")

    font = QFont()
    font.setFamilies(_FONT_STACK)
    font.setPointSize(13)
    app.setFont(font)

    app.setStyleSheet(_stylesheet())
