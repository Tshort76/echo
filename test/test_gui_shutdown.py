"""Exercise interpreter shutdown; an in-process assertion cannot catch a late Qt crash."""

import os
from pathlib import Path
import subprocess
import sys

import pytest

pytest.importorskip("PySide6", reason="GUI dependencies not installed")


@pytest.mark.parametrize("action", ["self.close", "QApplication.instance().quit"])
def test_gui_process_exits_cleanly(action):
    script = f"""
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
import gui.app as gui
import echo_gui

class AutoClose(gui.MainWindow):
    def show(self):
        super().show()
        QTimer.singleShot(0, {action})

gui.MainWindow = AutoClose
raise SystemExit(echo_gui.main())
"""
    result = subprocess.run(
        [sys.executable, "-X", "faulthandler", "-c", script],
        cwd=Path(__file__).resolve().parent.parent,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "shared QObject was deleted directly" not in result.stderr
