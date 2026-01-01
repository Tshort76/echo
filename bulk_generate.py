from pathlib import Path
import shutil
import re

import echo.constants as ec
import echo.core as core


def _output_path(input_file: str) -> str:
    p = Path(ec.OUTPUT_FOLDER) / Path(input_file).with_suffix(".mp3").name
    return str(p.absolute())


def _clean_filename(filename: str) -> str:
    cleaned_name = filename.lower()
    cleaned_name = cleaned_name.replace(" ", "_")
    cleaned_name = re.sub(r"[^a-z0-9_]", "", cleaned_name)

    return cleaned_name + ".txt"


if __name__ == "__main__":

    folder = Path("")

    for _path in folder.iterdir():
        _new_path = shutil.move(_path, folder / _clean_filename(_path.name))
        print(f"Renamed {_path.name} to {_new_path.name}")
        mp3_path = _output_path(_new_path)
        print(f"Converting {_new_path} to MP3")
        core.file_to_mp3(str(_new_path.absolute()), mp3_path=mp3_path, voice="en-US-ChristopherNeural", speed=1.25)
        print(f"Wrote {mp3_path}")
