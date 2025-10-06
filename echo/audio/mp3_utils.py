import logging
import mimetypes

from pathlib import Path
import subprocess
import shutil

from mutagen.id3 import APIC, ID3, error
from mutagen.mp3 import MP3
from mutagen.easyid3 import EasyID3

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


def add_meta_fields(mp3_path: Path, image_path: Path = None, title: str = None, author: str = None) -> None:
    "Embeds an image into an MP3 file as album art."

    if title or author:
        add_common_meta(mp3_path, title, author)

    try:
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
    except error as e:
        log.error(f"An error occurred when attaching album art: {e}")


def _merge_with_ffmpeg(mp3_files: list[str], output_path: str):
    input_files = "|".join(mp3_files)
    command = f'ffmpeg -i "concat:{input_files}" -acodec copy {output_path}'

    subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, shell=True, check=True)


def merge_mp3s(mp3s_path: Path, output_path: Path, delete_after: bool = True):

    def _merge_mp3s(files: list[str], i: int, _prev: str) -> str:
        _out = str((mp3s_path / f"temp_{str(i).zfill(4)}.mp3").absolute())
        if _prev:
            files = [_prev] + files
        _merge_with_ffmpeg(files, _out)
        return _out

    files, i, _prev = [], 0, None
    for file in sorted(mp3s_path.glob("*.mp3")):
        files.append(str(file.absolute()))
        if len(files) == 8:
            _temp_out = _merge_mp3s(files, i, _prev)
            files, i, _prev = [], i + 1, _temp_out

    if files:
        _temp_out = _merge_mp3s(files, i, _prev)

    shutil.move(_temp_out, output_path)
    if delete_after:
        shutil.rmtree(mp3s_path)
