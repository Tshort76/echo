"""Locating ffmpeg, and writing tags/cover art onto a finished file.

Joining audio moved to :mod:`echo.audio.assemble` when pydub was retired; what
remains here is ffmpeg discovery (still needed by both) and metadata, which
mutagen does better than ffmpeg for both MP3 and MP4/M4B containers.
"""

from __future__ import annotations

import logging
import mimetypes
import os
import shutil
from pathlib import Path

from mutagen.easyid3 import EasyID3
from mutagen.id3 import APIC, ID3
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4, MP4Cover

from echo.paths import resource_path

log = logging.getLogger(__name__)

_MP4_SUFFIXES = {".m4b", ".m4a", ".mp4"}


def configure_ffmpeg() -> str | None:
    """Return a usable ffmpeg path, or None.

    Prefers an ffmpeg bundled with a frozen build (``bin/ffmpeg[.exe]``) — a GUI
    launched from Finder/Explorer has a minimal PATH and won't otherwise find a
    system install — then falls back to ffmpeg on PATH.
    """
    exe = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    bundled = resource_path(f"bin/{exe}")
    if bundled.exists():
        return str(bundled)
    return shutil.which("ffmpeg")


def _add_mp3_meta(path: Path, title: str | None, author: str | None, image_path: Path | None) -> None:
    if title or author:
        try:
            audio = EasyID3(path)
        except Exception:
            audio = EasyID3()  # no ID3 header yet
            audio.save(path)
            audio = EasyID3(path)
        if title:
            audio["title"] = title
            audio["album"] = title
        if author:
            audio["artist"] = author
        audio.save(path)

    if image_path:
        mp3 = MP3(path, ID3=ID3)
        if not mp3.tags:
            mp3.add_tags()
        mime_type, _ = mimetypes.guess_type(str(image_path))
        mp3.tags.add(
            APIC(
                encoding=3,  # UTF-8
                mime=mime_type or "image/jpeg",
                type=3,  # album front cover
                desc="Cover",
                data=Path(image_path).read_bytes(),
            )
        )
        mp3.save()


def _add_mp4_meta(path: Path, title: str | None, author: str | None, image_path: Path | None) -> None:
    audio = MP4(path)
    if title:
        audio["\xa9nam"] = [title]
        audio["\xa9alb"] = [title]
    if author:
        audio["\xa9ART"] = [author]
        audio["aART"] = [author]
    # Media kind 2 = audiobook, which makes players treat chapters properly.
    audio["stik"] = [2]
    if image_path:
        image_path = Path(image_path)
        mime_type, _ = mimetypes.guess_type(str(image_path))
        image_format = MP4Cover.FORMAT_PNG if (mime_type or "").endswith("png") else MP4Cover.FORMAT_JPEG
        audio["covr"] = [MP4Cover(image_path.read_bytes(), imageformat=image_format)]
    audio.save()


def add_meta_fields(
    audio_path: Path,
    image_path: Path | None = None,
    title: str | None = None,
    author: str | None = None,
) -> None:
    """Write title/author/cover art onto an MP3 or M4B file."""
    audio_path = Path(audio_path)
    if not (title or author or image_path):
        return
    if image_path and not Path(image_path).exists():
        log.warning(f"Cover image {image_path} does not exist; skipping album art")
        image_path = None

    suffix = audio_path.suffix.lower()
    try:
        if suffix in _MP4_SUFFIXES:
            _add_mp4_meta(audio_path, title, author, image_path)
        elif suffix == ".mp3":
            _add_mp3_meta(audio_path, title, author, image_path)
        else:
            log.warning(f"Don't know how to tag a {suffix} file; skipping metadata")
            return
    except Exception as ex:
        # Tagging is cosmetic: a finished audiobook should not be thrown away
        # because a cover image was the wrong shape.
        log.warning(f"Could not write metadata to {audio_path.name}: {ex}")
        return

    written = [name for name, value in (("title", title), ("author", author), ("cover", image_path)) if value]
    log.info(f"Wrote metadata ({', '.join(written)}) to {audio_path.name}")
