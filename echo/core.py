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


def convert_to_text(input_path: Path, configs: dict = {}) -> str:
    """Converts files from various formats (pdf, )

    Args:
        input_path (str): path to the file that is to be converted
        configs (dict, optional): format specific parsing configs (e.g. first_page)

    Returns:
        str: text contents of the input file
    """

    match input_path.suffix:
        case ".txt":
            with open(input_path, "r", encoding="utf-8") as fp:
                text = fp.read()

            if txt.is_gutenberg_text(text):
                text = txt.strip_gutenberg_bloat(text)
                chunks = txt.to_chunks(text, 20000)
                text = "\n".join(map(cln.format_for_audio, chunks))
                return cln.remove_repeat_lines(text)
            else:
                return text
        case ".pdf":
            log.info(f"Converting PDF {input_path} to text")
            p0 = configs.get("first_page", 0)
            p1 = configs.get("last_page", 9999)
            pages = pdfz.extract_page_contents(input_path, first_page=p0, last_page=p1, content_types=["text"])
            return cln.simplify_pdf_for_audio(pages)
        case ".epub":
            log.info(f"Converting EPUB {input_path} to text")
            text = eem.extract_epub_text(input_path)
            if txt.is_gutenberg_text(text):
                text = txt.strip_gutenberg_bloat(text)
                chunks = txt.to_chunks(text, 20000)
                text = "\n".join(map(cln.format_for_audio, chunks))
            return cln.remove_repeat_lines(text)
        case other_suffix:
            raise NotImplementedError(f"Echo does not support {other_suffix} files!")


def file_to_mp3(
    file_path: str,
    mp3_path: str = None,
    mp3_meta: dict = {},
    voice: str = None,
    speed: float = None,
    write_text_file: bool = False,
    parser_configs: dict = {},
) -> Path:
    """Generate an audio file from a text file

    Args:
        file_path (str): path to text/pdf/epub file
        mp3_path (str, optional): path for the resulting mp3 file
        mp3_meta (dict, optional): meta data to attach to the mp3
        voice (str, optional): Voice for the narrator
        speed (float, optional): playback speed multiplier
        write_text_file (bool, optional): write intermediate text to a txt file. Defaults to False
        parser_configs (dict, optional): configurations for parsing

    Returns:
        Path: File path to the resulting audio file
    """
    file_path = Path(file_path)
    if mp3_path is None:
        _mp3_path = file_path.with_suffix(".mp3")
    else:
        _mp3_path = Path(mp3_path)

    _text = convert_to_text(file_path, parser_configs)
    if write_text_file:
        with open(_mp3_path.with_suffix(".txt"), "w", encoding="utf-8") as fp:
            fp.write(_text)
    tts.text_to_mp3(_text, _mp3_path, voice=voice, speed=speed)

    if mp3_meta:
        mp3z.add_meta_fields(_mp3_path, **mp3_meta)

    return _mp3_path
