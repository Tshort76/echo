"""Resource-path resolution that works both in a normal checkout and when the
app is frozen by PyInstaller.

PyInstaller unpacks bundled data files under ``sys._MEIPASS`` (both for one-file
and one-dir builds). In a normal checkout there is no ``_MEIPASS``; data lives at
the repo root (this file is ``echo/paths.py``, one level below it). Routing every
bundled-resource lookup through :func:`resource_path` keeps the CLI working from
any working directory *and* lets the packaged GUI find its data.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Repo root in a normal checkout (parent of the ``echo`` package).
_REPO_ROOT = Path(__file__).resolve().parent.parent


def resource_path(relative: str | Path) -> Path:
    """Absolute path to a bundled resource (e.g. ``"resources/voices.csv"``)."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        base = Path(sys._MEIPASS)  # PyInstaller extraction dir
    else:
        base = _REPO_ROOT
    return base / relative
