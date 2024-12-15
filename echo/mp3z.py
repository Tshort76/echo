import logging
import mimetypes
import os
import pprint
import subprocess
import time
from pathlib import Path

import edge_tts  # https://github.com/rany2/edge-tts/tree/master
from mutagen.id3 import APIC, ID3, error
from mutagen.mp3 import MP3
from mutagen.easyid3 import EasyID3

import echo.constants as cn

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


def _merge_mp3s(mp3_files: list[str], output_file: str):
    # Create the ffmpeg command
    input_files = "|".join(mp3_files)  # Concatenate file paths with '|'
    command = f'ffmpeg -i "concat:{input_files}" -acodec copy {output_file}'

    subprocess.run(command, shell=True, check=True)
    log.info(f"Files merged into {output_file}")


def merge_mp3s(mp3_dir: str, name_prefix: str, batch_size: int = 8):
    mp3_path = Path(mp3_dir)
    files, idx = [], 1
    get_file = lambda x: f"resources/output/{name_prefix}_{str(x).zfill(2)}.mp3"
    for file in mp3_path.glob("*.mp3"):
        if len(files) == batch_size:
            _merge_mp3s(files, get_file(idx))
            idx += 1
            files = []
        else:
            files.append(str(file.absolute()))

    if files:
        _merge_mp3s(files, get_file(idx))


def text_to_mp3(text: str, mp3_path: str, voice: str = "Sonia_GB", rate: str = cn.DEFAULT_SPEED) -> str:
    """Generate an MP3 audio file from a string of text

    Args:
        text (str): The text to be converted into audio data
        mp3_path (str): file path to which the resulting audio data will be written
        voice (str): voice to use for the dictation (see echo.constants)
        rate (str, optional): playback speed adjustment. Defaults to "+0%".

    Returns:
        str: path of the mp3 file
    """
    t0 = time.time()
    x = edge_tts.Communicate(text, cn.voice_lookups[voice], rate=rate)
    x.save_sync(mp3_path)
    log.info(f"{mp3_path} creation complete!")
    t1 = time.time()
    log.debug(
        pprint.pformat(
            {
                "mp3_path": mp3_path,
                "voice": voice,
                "rate": rate,
                "mp3_size": f"{os.path.getsize(mp3_path) / 1e6:.3f} MB",
                "cpu_time": f"{(t1 - t0)/60:.2f} minutes",
            }
        )
    )
    return mp3_path


def file_to_mp3(file_path: str, voice: str = "Sonia_GB", output_dir: str = None) -> str:
    """Generate an audio file from a text file

    Args:
        file_path (str): path to text file
        voice (str): Voice for the narrator
        output_dir (str, optional): output directory for the audio file. Defaults to None.

    Returns:
        str: File path of the resulting audio file
    """
    p = Path(file_path)
    mp3_path = p.name.replace(p.suffix, ".mp3")
    if output_dir:
        mp3_path = os.path.join(output_dir, mp3_path)
    with open(p, mode="r", encoding="utf-8") as fp:
        text_to_mp3(fp.read(), mp3_path, voice=voice)
    return mp3_path
