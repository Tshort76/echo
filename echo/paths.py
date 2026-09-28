"""Locating data shipped with the library, and files bundled into a frozen app.

Two different things. Package data (the edge voice catalogue) lives inside the
``echo`` package, so it travels with a pip install. A frozen PyInstaller build
additionally unpacks bundled files — its own ffmpeg — under ``sys._MEIPASS``.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PACKAGE_DIR = Path(__file__).resolve().parent


def package_data(name: str) -> Path:
    """Absolute path to a file under ``echo/data/``, in a checkout, an install or a frozen app."""
    return _PACKAGE_DIR / "data" / name


def frozen_path(relative: str | Path) -> Path | None:
    """Path to a file bundled into a frozen build, or None when not frozen."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / relative
    return None
