"""Visual theme for the echo GUI.

A single Qt Style Sheet (QSS) that gives the app a warm, rounded, "Claude
artifact" look — cream paper surfaces, a coral accent, soft borders, and
friendlier controls — instead of the flat default widgets. Applied globally in
``gui.app.main`` via ``apply_theme(app)``; nothing else in the UI hard-codes
colors, so the palette below is the single place to retune the look.
"""

from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

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

# Preferred UI fonts per platform; QFont.setFamilies falls back left→right.
_FONT_STACK = [
    ".AppleSystemUIFont",
    "SF Pro Text",
    "Segoe UI",
    "Inter",
    "Helvetica Neue",
    "Arial",
]


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

    /* ---- Combo popup ---- */
    QComboBox::drop-down {{ border: none; width: 22px; }}
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
