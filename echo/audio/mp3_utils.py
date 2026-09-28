"""Locating ffmpeg, and writing tags, cover art and MP3 chapters onto a finished file.

Joining audio lives in :mod:`echo.audio.assemble`; what remains here is ffmpeg
discovery and metadata, which mutagen does better than ffmpeg for both MP3 and
MP4/M4B containers.
"""

from __future__ import annotations

import logging
import mimetypes
import os
import shutil
from pathlib import Path

from mutagen.easyid3 import EasyID3
from mutagen.id3 import APIC, CHAP, CTOC, ID3, TIT2, CTOCFlags
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4, MP4Cover

from echo.paths import frozen_path

log = logging.getLogger(__name__)

_MP4_SUFFIXES = {".m4b", ".m4a", ".mp4"}


def configure_ffmpeg() -> str | None:
    """Return a usable ffmpeg path, or None.

    In order: the ffmpeg bundled into a frozen build (``bin/ffmpeg[.exe]``); the
    static build that the ``imageio-ffmpeg`` wheel ships, which is a core
    dependency so that a pip install needs no separate system install; and
    finally ffmpeg on PATH. The wheel's build comes before PATH because it is a
    known quantity — it carries both the MP3 and AAC encoders — where a system
    ffmpeg may be built without them.
    """
    exe = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    bundled = frozen_path(f"bin/{exe}")
    if bundled is not None and bundled.exists():
        return str(bundled)
    try:
        import imageio_ffmpeg  # noqa: PLC0415

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as ex:  # not installed, or no binary for this platform
        log.debug(f"imageio-ffmpeg has no ffmpeg here: {ex}")
    return shutil.which("ffmpeg")


def _chronological_ids(titles: list[str]) -> list[str]:
    """Element ids padded so the CHAP frames are *stored* in chronological order.

    mutagen writes frames of equal priority sorted by encoded size, so shorter
    titles would come first — and readers that ignore the CTOC (ffmpeg, and the
    players built on it) list chapters in stored order. Each frame's size is its
    id plus its title (UTF-16 under ID3v2.3) plus a constant, so padding the id
    makes sizes strictly increase.
    """
    ids: list[str] = []
    previous = -1
    for i, title in enumerate(titles):
        base = f"chp{i}"
        size = len(base) + len(title.encode("utf-16-le"))
        pad = max(0, previous + 1 - size)
        ids.append(base + "_" * pad)
        previous = size + pad
    return ids


def write_mp3_chapters(path: Path, chapters: list, toc_title: str = "Chapters") -> None:
    """Write ID3 ``CHAP`` frames plus a top-level ``CTOC`` onto an MP3.

    ``chapters`` are anything with ``title``, ``start_ms`` and ``end_ms``. This
    is the ID3 chapter addendum that podcast apps and VLC read. Saved as ID3v2.3,
    which more players understand than v2.4.
    """
    if not chapters:
        return
    mp3 = MP3(path, ID3=ID3)
    if mp3.tags is None:
        mp3.add_tags()
    mp3.tags.delall("CHAP")
    mp3.tags.delall("CTOC")
    ids = _chronological_ids([mark.title for mark in chapters])
    mp3.tags.add(
        CTOC(
            element_id="toc",
            flags=CTOCFlags.TOP_LEVEL | CTOCFlags.ORDERED,
            child_element_ids=ids,
            sub_frames=[TIT2(encoding=3, text=[toc_title])],
        )
    )
    for element_id, mark in zip(ids, chapters, strict=True):
        mp3.tags.add(
            CHAP(
                element_id=element_id,
                start_time=max(0, int(mark.start_ms)),
                end_time=max(int(mark.start_ms) + 1, int(mark.end_ms)),
                # 0xFFFFFFFF = "use the times, not byte offsets" (ID3 chapter spec).
                start_offset=0xFFFFFFFF,
                end_offset=0xFFFFFFFF,
                sub_frames=[TIT2(encoding=3, text=[mark.title])],
            )
        )
    mp3.save(v2_version=3)


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
        audio.save(path, v2_version=3)

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
        mp3.save(v2_version=3)


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
