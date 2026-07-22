"""Download a static ffmpeg binary into vendor/ffmpeg/<platform>/ for bundling.

pydub shells out to ffmpeg to merge/encode MP3 chunks, and a GUI launched from
Finder/Explorer has a minimal PATH — so we bundle a *static* ffmpeg with the app.
(A Homebrew/apt ffmpeg is dynamically linked and can't just be copied into a
bundle, hence downloading a static build.)

Usage:
    python packaging/fetch_ffmpeg.py            # fetch for the current OS
    python packaging/fetch_ffmpeg.py --force    # re-download even if present

The download URLs point at community static builds and DO drift over time; if a
URL 404s, update it below (or pass --url). The script verifies the binary runs
`ffmpeg -version` before declaring success.
"""

from __future__ import annotations

import argparse
import io
import os
import stat
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Static-build sources (zip archives). Update if they move.
DEFAULT_URLS = {
    "darwin": "https://evermeet.cx/ffmpeg/getrelease/ffmpeg/zip",
    "windows": "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
    # Linux static builds: https://johnvansickle.com/ffmpeg/ (tar.xz, not handled here)
}


def _platform_key() -> str:
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "darwin"
    return "linux"


def _target(platform_key: str) -> Path:
    name = "ffmpeg.exe" if platform_key == "windows" else "ffmpeg"
    return REPO_ROOT / "vendor" / "ffmpeg" / platform_key / name


def _extract_ffmpeg_from_zip(data: bytes, dest: Path) -> None:
    """Find the ffmpeg binary inside a zip archive and write it to dest."""
    wanted = dest.name.lower()
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        member = next(
            (m for m in zf.namelist() if Path(m).name.lower() == wanted and not m.endswith("/")),
            None,
        )
        if member is None:
            raise RuntimeError(f"Could not find {dest.name} inside the downloaded archive.")
        dest.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(member) as src, open(dest, "wb") as out:
            out.write(src.read())


def _verify(binary: Path) -> None:
    result = subprocess.run([str(binary), "-version"], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"{binary} did not run cleanly:\n{result.stderr}")
    print(result.stdout.splitlines()[0] if result.stdout else "ffmpeg OK")


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch a static ffmpeg for bundling.")
    parser.add_argument("--force", action="store_true", help="re-download even if present")
    parser.add_argument("--url", help="override the download URL (a .zip archive)")
    args = parser.parse_args()

    key = _platform_key()
    dest = _target(key)

    if key == "linux":
        print("Linux static builds aren't automated here — grab one from "
              "https://johnvansickle.com/ffmpeg/ and place it at "
              f"{dest} (chmod +x).")
        return 1

    if dest.exists() and not args.force:
        print(f"ffmpeg already present: {dest}")
        _verify(dest)
        return 0

    url = args.url or DEFAULT_URLS[key]
    print(f"Downloading ffmpeg for {key} from:\n  {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "echo-build/1.0"})
    with urllib.request.urlopen(req) as resp:  # noqa: S310 (trusted, user-run build step)
        data = resp.read()

    _extract_ffmpeg_from_zip(data, dest)
    if key != "windows":
        dest.chmod(dest.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    print(f"Wrote {dest} ({dest.stat().st_size // (1024 * 1024)} MB)")
    _verify(dest)
    print("\nRemember to also drop the ffmpeg LICENSE text at "
          f"{dest.parent / 'LICENSE.txt'} for redistribution.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
