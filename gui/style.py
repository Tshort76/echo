"""Visual theme for the echo GUI.

Two palettes behind one Qt Style Sheet (QSS): a Material-inspired **light** theme
(cool blue-grey surfaces, deep teal accent) and a Nord-based **dark** theme
(arctic blue-greys with a frost accent — palette from nordtheme.com). The two
share a cool blue-grey temperature, so switching between them reads as one app
in two lights rather than two different apps. Which one renders is an
*appearance mode*:
``light``, ``dark``, or ``system`` (follow the OS, live — Qt 6.5+ reports the
platform scheme and signals when it flips). The choice persists in ``QSettings``
and is exposed in the GUI's settings dialog.

Applied globally in ``gui.app.main`` via ``apply_theme(app)``; nothing else in
the UI hard-codes colors, so the two ``Palette`` instances below are the single
place to retune either look.
"""

from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QPointF, QSettings, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen
from PySide6.QtWidgets import QApplication

log = logging.getLogger(__name__)


# --- palettes --------------------------------------------------------------- #
@dataclass(frozen=True)
class Palette:
    """Every color the stylesheet needs. No hex codes live outside these."""

    name: str
    bg: str  # window background
    surface: str  # cards, inputs, dialogs
    surface_alt: str  # log panel / subtle surfaces
    border: str  # hairline borders
    border_strong: str  # input borders
    text: str  # primary text
    muted: str  # secondary text / headings / disabled hints
    accent: str  # primary actions, focus, selection
    accent_hover: str
    accent_pressed: str
    accent_soft: str  # light accent tint (list selection)
    accent_disabled: str
    on_accent: str  # text drawn on top of the accent
    disabled_bg: str  # disabled inputs and buttons
    disabled_text: str
    hover_bg: str  # secondary-button hover fill
    pressed_bg: str
    hover_border: str
    scroll_hover: str
    slider_hover: str
    icon_disabled: str


#: The light theme: Material teal — cool blue-grey greys with a deep teal accent,
#: in the qt-material tradition. Replaced the original warm-paper look.
MATERIAL_LIGHT = Palette(
    name="light",
    bg="#ECEFF1",
    surface="#FFFFFF",
    surface_alt="#F7F9FA",
    border="#DDE3E6",
    border_strong="#C6CFD4",
    text="#20292E",
    muted="#6F7E86",
    accent="#00838F",
    accent_hover="#00707A",
    accent_pressed="#005E66",
    accent_soft="#D2EBEE",
    accent_disabled="#8FC3C9",
    on_accent="#FFFFFF",
    disabled_bg="#E4E9EC",
    disabled_text="#9AA7AD",
    hover_bg="#E4E9EC",
    pressed_bg="#D8DFE3",
    hover_border="#AEBBC2",
    scroll_hover="#AEBBC2",
    slider_hover="#D2EBEE",
    icon_disabled="#AEBBC2",
)

#: The dark theme: Nord (nordtheme.com) — polar-night surfaces, frost accent.
#: The accent is *light*, so text on it is dark, unlike the light theme.
NORD_DARK = Palette(
    name="dark",
    bg="#2E3440",
    surface="#3B4252",
    surface_alt="#333947",
    border="#434C5E",
    border_strong="#4C566A",
    text="#ECEFF4",
    muted="#93A1B6",
    accent="#88C0D0",
    accent_hover="#9AD0E0",
    accent_pressed="#6FAFC2",
    accent_soft="#3E4F5E",
    accent_disabled="#5E7E8A",
    on_accent="#2E3440",
    disabled_bg="#434C5E",
    disabled_text="#7B8798",
    hover_bg="#434C5E",
    pressed_bg="#353C4A",
    hover_border="#616E85",
    scroll_hover="#616E85",
    slider_hover="#3E4F5E",
    icon_disabled="#616E85",
)

# --- appearance mode --------------------------------------------------------- #
THEME_MODES = ("system", "light", "dark")
_SETTINGS_ORG, _SETTINGS_APP, _SETTINGS_KEY = "echo", "echo", "appearance"


def saved_mode() -> str:
    """The persisted appearance mode; anything unrecognized falls back to system."""
    mode = QSettings(_SETTINGS_ORG, _SETTINGS_APP).value(_SETTINGS_KEY, "system")
    return mode if mode in THEME_MODES else "system"


def save_mode(mode: str) -> None:
    QSettings(_SETTINGS_ORG, _SETTINGS_APP).setValue(_SETTINGS_KEY, mode)


def system_scheme(app: QApplication) -> str:
    """What the OS says: 'dark' or 'light' (Unknown counts as light)."""
    return "dark" if app.styleHints().colorScheme() == Qt.ColorScheme.Dark else "light"


def palette_for(mode: str, app: QApplication = None) -> Palette:
    """Resolve a mode to a palette. 'system' needs the app to ask the OS."""
    if mode == "system" and app is not None:
        mode = system_scheme(app)
    return NORD_DARK if mode == "dark" else MATERIAL_LIGHT


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


def chevron_asset(color: str = MATERIAL_LIGHT.muted, size: int = _CHEVRON_PX) -> Path | None:
    """Paint a downward chevron to a PNG and return its path, or None on failure.

    A QComboBox needs an *image* for its arrow: as soon as ``::drop-down`` is styled
    at all, Qt stops drawing its own indicator, and a stylesheet cannot describe a
    glyph. Rather than ship an asset — one more file to resolve in a frozen build —
    draw it here and cache it under the temp directory. The filename encodes colour
    and size, so repeated runs (and theme switches) reuse one file per look instead
    of leaking a new one each time.

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


def _combo_rules(chevron: Path | None, p: Palette = MATERIAL_LIGHT) -> str:
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
        border-left: 1px solid {p.border};
        background: transparent;
    }}
    QComboBox::down-arrow {{
        image: url("{chevron.as_posix()}");
        width: {_CHEVRON_PX}px;
        height: {_CHEVRON_PX}px;
    }}
    QComboBox:hover {{ border-color: {p.accent}; }}
    """


def _stylesheet(p: Palette) -> str:
    return f"""
    QMainWindow, QWidget {{
        background-color: {p.bg};
        color: {p.text};
    }}
    QLabel {{ background: transparent; }}

    /* ---- Tabs ---- */
    QTabWidget::pane {{
        border: 1px solid {p.border};
        border-radius: 12px;
        background: {p.surface};
        top: -1px;
    }}
    QTabBar::tab {{
        background: transparent;
        color: {p.muted};
        padding: 8px 18px;
        margin-right: 4px;
        border: 1px solid transparent;
        border-radius: 8px;
        font-weight: 600;
    }}
    QTabBar::tab:selected {{
        background: {p.surface};
        color: {p.text};
        border: 1px solid {p.border};
    }}
    QTabBar::tab:hover:!selected {{ color: {p.text}; }}

    /* ---- Group boxes ---- */
    QGroupBox {{
        background: {p.surface};
        border: 1px solid {p.border};
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
        color: {p.text};
    }}

    /* ---- Text inputs ---- */
    QLineEdit, QPlainTextEdit, QComboBox, QSpinBox {{
        background: {p.surface};
        border: 1px solid {p.border_strong};
        border-radius: 8px;
        padding: 6px 10px;
        color: {p.text};
        selection-background-color: {p.accent};
        selection-color: {p.on_accent};
    }}
    QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus {{
        border: 1px solid {p.accent};
    }}
    QLineEdit:disabled, QPlainTextEdit:disabled,
    QComboBox:disabled, QSpinBox:disabled {{
        background: {p.disabled_bg};
        color: {p.disabled_text};
    }}
    QPlainTextEdit {{ background: {p.surface_alt}; }}

    /* ---- Combo boxes: a chevron and a divider, so they read as dropdowns ---- */
    {_combo_rules(chevron_asset(p.muted), p)}

    /* ---- Combo popup ---- */
    QComboBox QAbstractItemView {{
        background: {p.surface};
        border: 1px solid {p.border};
        border-radius: 8px;
        padding: 4px;
        selection-background-color: {p.accent_soft};
        selection-color: {p.text};
        outline: none;
    }}

    /* ---- Buttons (secondary by default) ---- */
    QPushButton {{
        background: {p.surface};
        border: 1px solid {p.border_strong};
        border-radius: 8px;
        padding: 7px 14px;
        color: {p.text};
        font-weight: 600;
    }}
    QPushButton:hover {{ background: {p.hover_bg}; border-color: {p.hover_border}; }}
    QPushButton:pressed {{ background: {p.pressed_bg}; }}
    QPushButton:disabled {{
        color: {p.disabled_text}; background: {p.disabled_bg}; border-color: {p.border};
    }}

    /* ---- Primary buttons (Convert / Generate) ---- */
    QPushButton#primary {{
        background: {p.accent};
        border: 1px solid {p.accent};
        color: {p.on_accent};
        padding: 9px 18px;
    }}
    QPushButton#primary:hover {{
        background: {p.accent_hover}; border-color: {p.accent_hover};
    }}
    QPushButton#primary:pressed {{
        background: {p.accent_pressed}; border-color: {p.accent_pressed};
    }}
    QPushButton#primary:disabled {{
        background: {p.accent_disabled}; border-color: {p.accent_disabled};
        color: {p.on_accent};
    }}

    /* ---- Collapsible "advanced" disclosure ---- */
    QToolButton#disclosure {{
        background: transparent;
        border: none;
        padding: 4px 2px;
        color: {p.text};
        font-weight: 600;
    }}
    QToolButton#disclosure:hover {{ color: {p.accent}; }}
    QToolButton#iconbtn {{
        background: {p.surface};
        border: 1px solid {p.border_strong};
        border-radius: 8px;
        font-size: 17px;
        color: {p.text};
    }}
    QToolButton#iconbtn:hover {{ border-color: {p.accent}; color: {p.accent}; }}
    QToolButton#iconbtn:checked {{
        background: {p.accent}; border-color: {p.accent}; color: {p.on_accent};
    }}
    QToolButton#iconbtn:disabled {{
        background: {p.disabled_bg}; border-color: {p.border}; color: {p.icon_disabled};
    }}
    QFrame#card {{
        background: {p.surface};
        border: 1px solid {p.border};
        border-radius: 12px;
    }}
    QLabel#sectionHeading {{
        color: {p.muted};
        font-weight: 700;
    }}
    QFrame#voicebox {{
        border: 1px solid {p.border_strong};
        border-radius: 10px;
        background: transparent;
    }}
    QFrame#statusbar {{
        background: {p.surface};
        border: 1px solid {p.border};
        border-radius: 10px;
    }}

    /* ---- Checkboxes / radios / group check ---- */
    QCheckBox, QRadioButton {{ background: transparent; spacing: 8px; }}
    QCheckBox::indicator, QRadioButton::indicator, QGroupBox::indicator {{
        width: 18px; height: 18px;
        border: 1px solid {p.border_strong};
        background: {p.surface};
    }}
    QCheckBox::indicator, QGroupBox::indicator {{ border-radius: 5px; }}
    QRadioButton::indicator {{ border-radius: 9px; }}
    QCheckBox::indicator:checked, QGroupBox::indicator:checked,
    QRadioButton::indicator:checked {{
        background: {p.accent}; border-color: {p.accent};
    }}
    QCheckBox::indicator:hover, QRadioButton::indicator:hover,
    QGroupBox::indicator:hover {{ border-color: {p.accent}; }}

    /* ---- Slider ---- */
    QSlider::groove:horizontal {{
        height: 6px; background: {p.border}; border-radius: 3px;
    }}
    QSlider::sub-page:horizontal {{
        background: {p.accent}; border-radius: 3px;
    }}
    QSlider::handle:horizontal {{
        background: {p.surface};
        border: 2px solid {p.accent};
        width: 16px; height: 16px;
        margin: -7px 0;
        border-radius: 9px;
    }}
    QSlider::handle:horizontal:hover {{ background: {p.slider_hover}; }}

    /* ---- Progress bar ---- */
    QProgressBar {{
        border: 1px solid {p.border};
        border-radius: 8px;
        background: {p.surface};
        text-align: center;
        color: {p.text};
        min-height: 18px;
    }}
    QProgressBar::chunk {{
        background: {p.accent};
        border-radius: 7px;
        margin: 1px;
    }}

    /* ---- Scrollbars ---- */
    QScrollBar:vertical {{
        background: transparent; width: 10px; margin: 2px;
    }}
    QScrollBar::handle:vertical {{
        background: {p.border_strong}; border-radius: 5px; min-height: 24px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {p.scroll_hover}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
        background: transparent;
    }}

    /* ---- Tooltips (inverted surface, so they read in both themes) ---- */
    QToolTip {{
        background: {p.text}; color: {p.bg};
        border: none; border-radius: 6px; padding: 5px 8px;
    }}
    """


def apply_theme(app: QApplication, mode: str = None) -> None:
    """Apply the echo theme to ``app`` (Fusion base + font + stylesheet).

    ``mode`` is 'light', 'dark' or 'system'; None uses the persisted setting.
    """
    # Fusion is a consistent, fully style-sheet-able base across macOS & Windows,
    # so the QSS below renders the same everywhere rather than fighting the
    # native platform styles.
    app.setStyle("Fusion")

    font = QFont()
    font.setFamilies(_FONT_STACK)
    font.setPointSize(13)
    app.setFont(font)

    app.setStyleSheet(_stylesheet(palette_for(mode or saved_mode(), app)))


def set_theme_mode(app: QApplication, mode: str) -> None:
    """Persist an appearance choice and re-theme the running app immediately."""
    save_mode(mode)
    apply_theme(app, mode)


def watch_system_theme(app: QApplication) -> None:
    """Re-theme when the OS flips light/dark, if the user follows the system."""
    app.styleHints().colorSchemeChanged.connect(
        lambda *_: apply_theme(app) if saved_mode() == "system" else None
    )
