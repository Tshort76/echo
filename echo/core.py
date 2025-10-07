import os
import logging
from pathlib import Path

import echo.extractors.pdfs as pdfz
import echo.extractors.text as txt
import echo.extractors.misc as eem
import echo.audio.mp3_utils as mp3z
import echo.audio.tts as tts
import echo.clean as cln

log = logging.getLogger(__name__)


def play_mp3_clip(voice: str, speed: float = 1):
    mp3_path = "resources/outputs/sample.mp3"
    if os.path.exists(mp3_path):
        os.remove(mp3_path)
    mp3_path = file_to_mp3("resources/demo_data/sample.txt", mp3_path, voice=voice, speed=speed)
    os.startfile(str(mp3_path.absolute()))


def _convert_to_text(input_path: Path, configs: dict = {}) -> Path:
    """Converts files from various formats (pdf, )

    Args:
        input_path (str): path to the file that is to be converted
        configs (dict, optional): format specific parsing configs (e.g. first_page)

    Returns:
        str: text contents of the input file
    """

    # TODO do I need to lower case the suffix?  TXT vs txt
    match input_path.suffix:
        case ".txt":  # | .TXT ... etc.
            source = None  # TODO txt.text_source(input_path)
            if source == "gutenberg":
                log.info(f"Cleaning gutenberg file: {input_path}")
                x = txt.extract_gutenberg_data(input_path)
                cln.smooth_gutenburg_for_audio(x["contents"])
                return x["contents"]
            else:
                with open(input_path, "r", encoding="utf-8") as fp:
                    return fp.read()
        case ".pdf":  # TODO is the '.' in the suffix?
            log.info(f"Converting PDF {input_path} to text")
            p0 = configs.get("first_page", 0)
            p1 = configs.get("last_page", 9999)
            pages = pdfz.extract_page_contents(input_path, first_page=p0, last_page=p1, content_types=["text"])
            return cln.smooth_pdf_for_audio(pages)
        case ".epub":
            log.info(f"Converting EPUB {input_path} to text")
            return eem.extract_epub_texts(input_path)
        case other_suffix:
            raise NotImplementedError(f"Echo does not support {other_suffix} files!")


def file_to_mp3(
    file_path: str,
    mp3_path: str = None,
    mp3_meta: dict = {},
    voice: str = None,
    speed: float = None,
    parser_configs: dict = {},
) -> Path:
    """Generate an audio file from a text file

    Args:
        file_path (str): path to text/pdf/epub file
        mp3_path (str, optional): path for the resulting mp3 file
        mp3_meta (dict, optional): meta data to attach to the mp3
        voice (str, optional): Voice for the narrator
        speed (float, optional): playback speed multiplier
        parser_configs (dict, optional): configurations for parsing

    Returns:
        str: File path to the resulting audio file
    """
    file_path = Path(file_path)
    if mp3_path is None:
        mp3_path = file_path.with_suffix(".mp3")
    else:
        mp3_path = Path(mp3_path)

    _text = _convert_to_text(file_path, parser_configs)
    tts.text_to_mp3(_text, mp3_path, voice=voice, speed=speed)

    if mp3_meta:
        mp3z.add_meta_fields(mp3_path, **mp3_meta)

    return mp3_path
