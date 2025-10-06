import logging
import argparse

import echo.constants as ec
import echo.core as core

_log_level = logging.WARNING

logging.basicConfig(level=_log_level, format=ec.LOG_FORMAT, datefmt=ec.LOG_DATE_FORMAT)


def _coerce_playback_speed(arg: str) -> str:
    "Convert a multiplier fraction such as 1.5 to the tts lib equivalent of '(+|-)X%'"
    try:
        _rate = float(arg)
    except ValueError:
        raise argparse.ArgumentTypeError(f"Invalid value: '{arg}' is not a valid number.")

    if _rate < 0.5 or _rate > 3:
        raise argparse.ArgumentTypeError(f"Invalid value: '{arg}' must be between 0.5 and 3")
    return _rate


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generating audio files from EPUB, PDF, or TXT files")

    parser.add_argument("file_path", type=str, help="The file path to the book content (required).")

    parser.add_argument(
        "--voice",
        type=str,
        default=ec.DEFAULT_VOICE,
        choices=ec.VOICES,
        help=f"The name of the TTS voice to use. (Default: {ec.DEFAULT_VOICE})",
    )

    parser.add_argument(
        "--speed",
        type=_coerce_playback_speed,
        default=ec.DEFAULT_SPEED,
        help=f"The playback speed multiplier. (Default: {ec.DEFAULT_SPEED})",
    )

    parser.add_argument(
        "--out_dir",
        type=str,
        default="",
        help=f"The directory in which the generated MP3 will be stored",
    )

    args = parser.parse_args()

    print(
        f"FilePath: {args.file_path}\nVoice: {args.voice}\nSpeed: {args.speed}\nOutDir: {args.out_dir}\n--------------------\n"
    )

    output_path = core.file_to_mp3(
        args.file_path,
        voice=args.voice,
        speed=args.speed,
        parser_configs={},
    )

    print(f"Wrote MP3 to {output_path}")
