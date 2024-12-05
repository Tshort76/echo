from mutagen.id3 import APIC, ID3, error
from mutagen.mp3 import MP3
import mimetypes
import logging
from pathlib import Path
import subprocess

log = logging.getLogger(__name__)


def add_front_cover(mp3_path: Path, image_path: Path) -> None:
    "Embeds an image into an MP3 file as album art."
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
        log.error(f"An error occurred: {e}")


def merge_mp3s(mp3_files: list[str], output_file: str):
    # Create the ffmpeg command
    input_files = "|".join(mp3_files)  # Concatenate file paths with '|'
    command = f'ffmpeg -i "concat:{input_files}" -acodec copy {output_file}'

    subprocess.run(command, shell=True, check=True)
    log.info(f"Files merged into {output_file}")


def merge_batches(mp3_dir: str, name_prefix: str, batch_size: int = 8):
    mp3_path = Path(mp3_dir)
    files, idx = [], 1
    get_file = lambda x: f"resources/output/{name_prefix}_{str(x).zfill(2)}.mp3"
    for file in mp3_path.glob("*.mp3"):
        if len(files) == batch_size:
            merge_mp3s(files, get_file(idx))
            idx += 1
            files = []
        else:
            files.append(str(file.absolute()))

    if files:
        merge_mp3s(files, get_file(idx))
