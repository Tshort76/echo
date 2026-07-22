"""Launcher for the echo desktop GUI.

Run from the repo root:

    python echo_gui.py

Requires the GUI dependencies:

    pip install -r requirements-gui.txt

The CLI entry points (create_audio.py, deep_research_cli.py) do not depend on
this file or on PySide6 — the GUI is a separate, optional layer.
"""

import sys


def main() -> int:
    try:
        from gui.app import main as run_app
    except ImportError as exc:  # most likely: PySide6 not installed
        sys.stderr.write(
            "Could not start the echo GUI. Its dependencies may be missing.\n"
            f"  ({exc})\n"
            "Install them with:\n"
            "    pip install -r requirements-gui.txt\n"
        )
        return 1
    return run_app()


if __name__ == "__main__":
    sys.exit(main())
