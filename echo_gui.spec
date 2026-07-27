# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the echo desktop GUI (onedir; macOS .app + Windows .exe).

Build:  pyinstaller echo_gui.spec --noconfirm --clean
Artifacts land in dist/ (dist/Echo.app on macOS, dist/Echo/ on Windows).

One spec, branched by platform — the Analysis is identical everywhere; only the
icon, the bundled ffmpeg path, and the macOS BUNDLE differ. Data/binaries are
included conditionally so the spec still builds before ffmpeg/icons are vendored.
"""
import sys
from pathlib import Path

HERE = Path(SPECPATH)  # SPECPATH is injected by PyInstaller = this file's dir
IS_WIN = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"

# --- bundled data (absolute sources so cwd doesn't matter) ---
datas = [(str(HERE / "resources" / "voices.csv"), "resources")]
_demo = HERE / "resources" / "demo_data"
if _demo.is_dir():
    datas.append((str(_demo), "resources/demo_data"))

# --- bundled ffmpeg (fetched into vendor/ by packaging/fetch_ffmpeg.py) ---
binaries = []
_ff_name = "ffmpeg.exe" if IS_WIN else "ffmpeg"
_ff_platform = "windows" if IS_WIN else ("darwin" if IS_MAC else "linux")
_ff = HERE / "vendor" / "ffmpeg" / _ff_platform / _ff_name
if _ff.exists():
    binaries.append((str(_ff), "bin"))
    _lic = _ff.parent / "LICENSE.txt"
    if _lic.exists():
        datas.append((str(_lic), "bin"))
else:
    print(f"[echo_gui.spec] NOTE: no bundled ffmpeg at {_ff}; "
          "the app will rely on a system ffmpeg on PATH. "
          "Run `python packaging/fetch_ffmpeg.py` to bundle one.")

# --- optional speech engines ---
# Engines are imported lazily by echo.audio.engines, so PyInstaller cannot see
# them by static analysis. Bundle whichever are installed in the build
# environment and exclude the rest, so the app ships exactly the engines you
# asked for instead of silently losing one (or bloating with all of them).
import importlib.util  # noqa: E402


def _installed(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


hiddenimports = []
excludes = [
    "tkinter",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.Qt3DCore",
    "PySide6.QtCharts", "PySide6.QtMultimedia", "PySide6.QtNetwork",
]

_OPTIONAL_ENGINES = {
    "google.genai": ["google.genai", "echo.audio.engines.google"],
    "google.cloud.texttospeech": ["google.cloud.texttospeech", "echo.audio.engines.google"],
    "mlx_audio": ["mlx_audio", "mlx_audio.tts.utils", "echo.audio.engines.mlx"],
}
for _probe, _imports in _OPTIONAL_ENGINES.items():
    if _installed(_probe):
        hiddenimports.extend(i for i in _imports if i not in hiddenimports)
        print(f"[echo_gui.spec] bundling optional engine: {_probe}")
    else:
        excludes.append(_probe)
        print(f"[echo_gui.spec] not installed, excluding: {_probe}")

# --- icon (optional; add art under packaging/icons/ later) ---
_ico = HERE / "packaging" / "icons" / ("echo.ico" if IS_WIN else "echo.icns")
icon = str(_ico) if _ico.exists() else None

a = Analysis(
    ["echo_gui.py"],
    pathex=[str(HERE)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Echo",
    debug=False,
    strip=False,
    upx=False,
    console=False,        # windowed app (no console) on both platforms
    icon=icon,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Echo",
)

if IS_MAC:
    app = BUNDLE(
        coll,
        name="Echo.app",
        icon=icon,
        bundle_identifier="com.tlong.echo",
        info_plist={
            "NSHighResolutionCapable": True,
            "CFBundleShortVersionString": "0.1.0",
        },
    )
