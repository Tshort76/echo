"""Build the echo standalone app with PyInstaller.

Usage (from a build venv with requirements-build.txt installed):
    python packaging/build_app.py

Steps: sanity-check the Python version, ensure a static ffmpeg is vendored
(bundled so the packaged app works without a system ffmpeg), then run
PyInstaller against echo_gui.spec. PyInstaller cannot cross-compile — run this
on macOS to get Echo.app and on Windows to get Echo.exe.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _check_python() -> None:
    major, minor = sys.version_info[:2]
    if (major, minor) >= (3, 14):
        print(f"⚠️  Python {major}.{minor}: PyInstaller + PySide6 hooks are less proven "
              "here, and Kokoro's misaki phonemizer cannot install (spaCy has no 3.14 "
              "wheels). If the build or the frozen app misbehaves, retry in a "
              "3.11–3.13 build venv.")
    elif (major, minor) < (3, 11):
        print(f"⚠️  Python {major}.{minor} is older than recommended (3.11–3.13).")


def _ensure_ffmpeg() -> None:
    key = "windows" if sys.platform.startswith("win") else ("darwin" if sys.platform == "darwin" else "linux")
    name = "ffmpeg.exe" if key == "windows" else "ffmpeg"
    binary = REPO_ROOT / "vendor" / "ffmpeg" / key / name
    if binary.exists():
        print(f"✓ bundling ffmpeg: {binary}")
        return
    print(f"• no vendored ffmpeg at {binary} — attempting fetch…")
    result = subprocess.run([sys.executable, str(REPO_ROOT / "packaging" / "fetch_ffmpeg.py")])
    if result.returncode != 0:
        print("⚠️  Could not vendor ffmpeg automatically. The app will build but will "
              "rely on a system ffmpeg on PATH at runtime (long conversions fail "
              "without it). See packaging/fetch_ffmpeg.py.")


def main() -> int:
    _check_python()
    _ensure_ffmpeg()

    spec = REPO_ROOT / "echo_gui.spec"
    print(f"\nRunning PyInstaller on {spec.name} …\n")
    result = subprocess.run(
        [sys.executable, "-m", "PyInstaller", str(spec), "--noconfirm", "--clean"],
        cwd=REPO_ROOT,
    )
    if result.returncode != 0:
        print("\n❌ Build failed. Check the traceback and build/echo_gui/warn-echo_gui.txt "
              "for missing imports (add them to hiddenimports in echo_gui.spec).")
        return result.returncode

    dist = REPO_ROOT / "dist"
    artifact = dist / ("Echo.app" if sys.platform == "darwin" else "Echo")
    print(f"\n✅ Built: {artifact}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
