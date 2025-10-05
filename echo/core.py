import os
from pathlib import Path
import logging

import echo.constants as cn
import echo.extractors.text as bt
import echo.extractors.pdfs as pdfz
import echo.mp3z as mp3z
import echo.formatters.books as efb

log = logging.getLogger(__name__)


def _write_file(file_path: str, contents: str):
    with open(file_path, "w", encoding="utf-8") as fp:
        fp.write(contents)


def _play_mp3_clip(voice: str, speed: str = "+0%"):
    file_path = "resources/output/sample.mp3"
    if os.path.exists(file_path):
        os.remove(file_path)
    mp3_path = mp3z.file_to_mp3("samples/sample.txt", voice=voice, speed=speed, output_dir=cn.OUTPUT_DIRECTORY)
    os.startfile(mp3_path)


def open_parent_dir(file_path: str):
    if os.path.exists(file_path):
        p = Path(file_path)
        os.startfile(p.parent)


def _in_outputs_dir(file_path: str) -> str:
    p = Path(file_path)
    return os.path.join(cn.OUTPUT_DIRECTORY, p.name)


def convert(
    process: cn.Process,
    input_path: str,
    voice: str = cn.DEFAULT_VOICE,
    icon_path: str = None,
    save_steps: bool = False,
    starting_page: int = 0,
    ending_page: int = 9999,
    speed: str = None,
) -> str:
    """Convert a text-based file into another form

    Args:
        process (cn.Process): <gutenberg|pdf>_to_<text|mp3>, "text_to_mp3", "sample_voice"
        input_path (str): path to the input data file
        voice (str, optional): narration voice, if converting to MP3. Defaults to env.DEFAULT_VOICE
        icon_path (str, optional): path to album front cover, if converting to MP3. Defaults to None.
        save_steps (bool, optional): whether to save the output of intermediate steps. Defaults to False
        starting_page (int, optional): starting page for pdf extraction. Defaults to 0.
        ending_page (int, optional): ending page for pdf extraction. Defaults to 9999.

    Returns:
        str: File path for the generated file
    """

    if process == cn.Process.SAMPLE_VOICE:
        _play_mp3_clip(voice)
        return

    assert input_path, "An input file is required"

    output_file = None
    match process:
        case cn.Process.GUTENBURG_MP3:
            x = bt.extract_gutenberg_data(input_path)
            output_file = _in_outputs_dir(bt.name_for_file(x, ext="mp3"))
            mp3z.text_to_mp3(x["contents"], output_file, voice=voice)
        case cn.Process.GUTENBURG_TEXT:
            x = bt.extract_gutenberg_data(input_path)
            output_file = _in_outputs_dir(bt.name_for_file(x, ext="txt"))
            _write_file(output_file, x["contents"])
        case cn.Process.PDF_TO_TEXT:
            pages = pdfz.extract_text_pages(
                input_path,
                start_page_num=starting_page,
                end_page_num=ending_page,
            )
            output_file = _in_outputs_dir(pdfz.name_for_file(input_path, "txt"))
            _write_file(output_file, "\n".join(pages))
        case cn.Process.PDF_TO_MP3:
            pages = pdfz.extract_page_contents(
                input_path,
                start_page_num=starting_page,
                end_page_num=ending_page,
            )
            output_file = _in_outputs_dir(pdfz.name_for_file(input_path, "mp3"))
            if save_steps:
                txt_file = output_file.replace("mp3", "txt")
                _write_file(txt_file, "\n".join(pages))
                log.info(f"Wrote intermediate text file: {txt_file}")
            mp3z.text_to_mp3(
                "\n".join(pages),
                output_file,
                voice=voice,
            )
        case cn.Process.TEXT_TO_MP3:
            output_file = mp3z.file_to_mp3(input_path, voice=voice, speed=speed, output_dir=cn.OUTPUT_DIRECTORY)

    if "mp3" in process and icon_path:
        mp3z.add_meta_fields(output_file, icon_path)

    return output_file


def convert_chapter(
    pdf_path: str,
    mp3_path: str,
    first_page: int,
    last_page: int,
    mp3_meta: dict = {},
    voice: str = "Sonia_GB",
    opts: dict = {},
) -> str:
    pages = pdfz.extract_page_contents(pdf_path, first_page=first_page, last_page=last_page, content_types=["text"])
    audio_text = efb.smooth_pdf_for_audio(pages)

    txt_path = mp3_path.replace("mp3", "txt")
    with open(txt_path, "w", encoding="utf-8") as file:
        file.write(audio_text)
        log.info(f"Wrote intermediate text file: {txt_path}")

    if opts.get("text_file_only"):
        return txt_path

    mp3z.text_to_mp3(audio_text, mp3_path, voice=voice)
    mp3z.add_meta_fields(mp3_path, **mp3_meta)
    return mp3_path
