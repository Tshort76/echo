import logging
import mimetypes
import shutil
from pathlib import Path

from mutagen.easyid3 import EasyID3
from mutagen.id3 import APIC, ID3, error
from mutagen.mp3 import MP3
from pydub import AudioSegment

log = logging.getLogger(__name__)


def add_common_meta(mp3_path: Path, title: str = None, author: str = None) -> None:
    try:
        audio = EasyID3(mp3_path)
    except Exception:
        audio = EasyID3()  # Create ID3 tag if not present
        audio.save(mp3_path)  # Save to attach to file

    # Update metadata
    if title:
        audio["title"] = title
    if author:
        audio["artist"] = author
    audio.save(mp3_path)


def _add_cover_art(mp3_path: Path, image_path: Path) -> None:
    mp3 = MP3(mp3_path, ID3=ID3)

    # Add ID3 tag if it doesn't exist
    if not mp3.tags:
        mp3.add_tags()

    mime_type, _ = mimetypes.guess_type(image_path)

    with open(image_path, "rb") as img:
        mp3.tags.add(
            APIC(
                encoding=3,  # 3 is for UTF-8
                mime=mime_type,
                type=3,  # 3 is for the album front cover
                desc="Cover",  # Description of the image
                data=img.read(),  # Actual image data
            )
        )

    mp3.save()
    log.info(f"Added {image_path} to {mp3_path} as album art!")


def add_meta_fields(mp3_path: Path, image_path: Path = None, title: str = None, author: str = None) -> None:
    "Embeds an image into an MP3 file as album art."

    if title or author:
        add_common_meta(mp3_path, title, author)
    if image_path:
        _add_cover_art(mp3_path, image_path)


def merge_audio_files(mp3s_dir: Path, output_path: Path, delete_after: bool = True) -> bool:

    paths = sorted(mp3s_dir.glob("*.mp3"))

    log.info(f"Merging {len(paths)} audio file(s)...")

    merged_audio = AudioSegment.empty()
    for path in paths:
        try:
            merged_audio += AudioSegment.from_file(path, format=path.suffix.lstrip("."))
        except Exception as e:
            print(f"Error processing {path}: {str(e)}")

    try:
        log.debug(f"\nExporting to: {output_path}")
        merged_audio.export(output_path, format="mp3")
        log.info(f"Created {output_path}\nTotal duration: {len(merged_audio) / 1000:.2f} seconds")
    except Exception as e:
        log.error(f"Error exporting merged file: {str(e)}")

    if delete_after:
        shutil.rmtree(mp3s_dir)
    return True
