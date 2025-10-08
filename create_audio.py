import logging
import sys
import argparse
import json
from pathlib import Path

import echo.constants as ec
import echo.core as core

logging.basicConfig(
    level=logging.INFO,
    format=ec.LOG_FORMAT,
    datefmt=ec.LOG_DATE_FORMAT,
    stream=sys.stdout,
)


def _coerce_playback_speed(arg: str) -> str:
    "Convert a multiplier fraction such as 1.5 to the tts lib equivalent of '(+|-)X%'"
    try:
        _rate = float(arg)
    except ValueError:
        raise argparse.ArgumentTypeError(f"Invalid value: '{arg}' is not a valid number.")

    if _rate < 0.5 or _rate > 3:
        raise argparse.ArgumentTypeError(f"Invalid value: '{arg}' must be between 0.5 and 3")
    return _rate


def _json_type(s: str) -> dict:
    """Custom type function for argparse to convert a ~JSON string to a Python object."""
    try:
        s = s.replace('"', "").replace("'", '"').replace("\\\\", "/")
        return json.loads(s)
    except json.JSONDecodeError as e:
        raise argparse.ArgumentTypeError(f"Invalid JSON string: {e}")


def _output_path(input_file: str) -> str:
    p = Path(ec.OUTPUT_FOLDER) / Path(input_file).with_suffix(".mp3").name
    return str(p.absolute())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generating audio files from EPUB, PDF, or TXT files")

    parser.add_argument("file_path", type=str, help="The file path to the book content (required).")

    parser.add_argument(
        "-o",
        "--output",
        dest="output",
        type=str,
        default=None,
        help=f"The filepath for the resulting audio file",
    )

    parser.add_argument(
        "-v",
        "--voice",
        dest="voice",
        type=str,
        default=ec.DEFAULT_VOICE,
        help=f"The name of the TTS voice to use. (Default: {ec.DEFAULT_VOICE})",
    )

    parser.add_argument(
        "-s",
        "--speed",
        dest="speed",
        type=_coerce_playback_speed,
        default=ec.DEFAULT_SPEED,
        help=f"The playback speed multiplier. (Default: {ec.DEFAULT_SPEED})",
    )

    parser.add_argument(
        "-m",
        "--meta",
        dest="mp3_meta",
        type=_json_type,
        default={},
        help="Meta data for the mp3 file. (Default: {})",
    )

    parser.add_argument("--save", action="store_true", help="Save intermediate text file")

    args = parser.parse_args()

    _mp3_path = args.output or _output_path(args.file_path)

    print(
        f"FilePath: {args.file_path}\nVoice: {args.voice}\nSpeed: {args.speed}\nOut: {_mp3_path}\nSave: {args.save}\nMeta:{args.mp3_meta}\n--------------------\n"
    )

    output_path = core.file_to_mp3(
        args.file_path,
        mp3_path=_mp3_path,
        mp3_meta=args.mp3_meta,
        voice=args.voice,
        speed=args.speed,
        write_text_file=args.save,
        parser_configs={},
    )

    print("Wrote MP3" + (" and txt file" if args.save else "") + f" to {output_path}")
