"""Convert every supported document in a folder.

Takes the folder as an argument. The previous version defaulted to ``Path("")``
— the current directory — and renamed every entry it found in place before
converting, which was a footgun waiting to be pointed at a source tree. Renaming
is now opt-in via ``--rename``.
"""

import argparse
import logging
import re
import shutil
import sys
from pathlib import Path

import echo.constants as ec
import echo.core as core
from echo.audio.assemble import FORMATS
from echo.extractors import SUPPORTED_SUFFIXES

log = logging.getLogger(__name__)


def _clean_filename(filename: str) -> str:
    stem = Path(filename).stem.lower().replace(" ", "_")
    stem = re.sub(r"[^a-z0-9_]", "", stem)
    return stem + Path(filename).suffix.lower()


def _output_path(input_file: Path, fmt: str) -> Path:
    directory = Path(ec.OUTPUT_FOLDER) if ec.OUTPUT_FOLDER else input_file.parent
    return (directory / input_file.name).with_suffix(f".{fmt}")


def main(argv: list[str] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", help="Directory of documents to convert.")
    parser.add_argument("-e", "--engine", default=ec.DEFAULT_ENGINE)
    parser.add_argument("-v", "--voice", default=None)
    parser.add_argument("-s", "--speed", type=float, default=ec.DEFAULT_SPEED)
    parser.add_argument("-f", "--format", dest="fmt", choices=FORMATS, default=ec.DEFAULT_FORMAT)
    parser.add_argument("--rename", action="store_true", help="Normalize source filenames in place first.")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format=ec.LOG_FORMAT, datefmt=ec.LOG_DATE_FORMAT, stream=sys.stdout)

    folder = Path(args.folder).expanduser().resolve()
    if not folder.is_dir():
        parser.error(f"{folder} is not a directory")

    sources = sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES)
    if not sources:
        log.warning(f"No {', '.join(SUPPORTED_SUFFIXES)} files found in {folder}")
        return 1

    log.info(f"Converting {len(sources)} file(s) from {folder}")
    failures = []
    for source in sources:
        if args.rename:
            cleaned = folder / _clean_filename(source.name)
            if cleaned != source:
                source = Path(shutil.move(str(source), str(cleaned)))
                log.info(f"Renamed to {source.name}")
        try:
            output = core.file_to_audio(
                source,
                output_path=_output_path(source, args.fmt),
                voice=args.voice,
                speed=args.speed,
                engine=args.engine,
                fmt=args.fmt,
            )
            log.info(f"Wrote {output}")
        except Exception as ex:
            log.error(f"Failed on {source.name}: {ex}")
            failures.append(source.name)

    if failures:
        log.error(f"{len(failures)} file(s) failed: {', '.join(failures)}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
