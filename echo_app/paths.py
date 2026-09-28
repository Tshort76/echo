"""Resource paths for the app: the repo root in a checkout, ``sys._MEIPASS`` when frozen."""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent


def resource_path(relative: str | Path) -> Path:
    """Absolute path to an app resource (e.g. ``"resources/research"``)."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / relative
    return _REPO_ROOT / relative
