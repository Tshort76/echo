import logging
import os
import re
from pathlib import Path

import cv2
import numpy as np
import pytesseract
from dotenv import load_dotenv
from pdf2image import convert_from_path
import pymupdf as pp

from typing import Optional

load_dotenv()
log = logging.getLogger(__name__)

UNPRINTABLES = re.compile(r"[^\x20-\x7E\n]")
EXTRA_SPACE = re.compile(r"\s{2,}")  # TODO pull into constants
MAX_PAGE = 999999


def name_for_file(pdf_path: str, ext: str = "mp3") -> str:
    p = Path(pdf_path)
    return p.name.replace(p.suffix, "." + ext)


def _greyscale_image(image: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]
    return gray


def run_ocr_on_page(pdf_path: str, page_num: int) -> str:
    # Convert PDF to images
    poppler_path = os.environ.get("POPPLER_PATH")
    if not poppler_path:
        log.warning(f"Could not find poppler lib.  Did you specify the path in your env?")

    images = convert_from_path(pdf_path, first_page=page_num, last_page=page_num, poppler_path=poppler_path)

    # Extract text from each page
    page_texts = []
    for image in images:
        x = np.array(image)
        x = _greyscale_image(x)
        page_texts.append(pytesseract.image_to_string(x))

    return " ".join(page_texts)


def _clean_up_text(text: str) -> Optional[str]:
    if text is None:
        return None
    # Remove non-printable characters
    text = text.replace("—", " ").replace("–", " ")
    text = text.replace("\xad\n", "")
    text = text.replace("-\n", "")  # fails for three-year across lines ...
    text = text.replace("\xa0", " ")
    text = UNPRINTABLES.sub("", text)
    return text


def _contents_by_type(page: pp.Page, ann: pp.Annot) -> dict:
    # https://pymupdf.readthedocs.io/en/latest/vars.html#annotationtypes
    _type = ann.type  # tuple of form (id, desc1, desc2)
    content = {}

    match _type[0]:
        case 8 | 9:  # HIGHLIGHT or UNDERLINE
            content = _get_highlighted_content(page, ann)
        case _:
            content = {"note": ann.info.get("content")}

    return {"type": _type[-1], **content}


def _get_highlighted_content(page: pp.Page, ann: pp.Annot) -> dict:
    _text = []

    # annotation.vertices contains vertices of a polygon.  For highlights, the shapes are
    # rectangular, with one rectangle corresponding to one line of highlights.  Vertices
    # does not assume a rectangle, so we are given 4 vertices per rectangle but only need
    # 2 (adjacent corners).

    # Process the quad points in sets of four (two pairs for each rectangle)
    for i in range(0, len(ann.vertices), 4):
        rect = pp.Rect(ann.vertices[i], ann.vertices[i + 3])
        _text.append(page.get_text("text", clip=rect).strip())
    return {"text": " ".join(_text), "color": ann.colors, "note": ann.info.get("content")}


def extract_page_contents(
    pdf_path: str,
    first_page: int = None,  # 1 indexed
    last_page: int = None,
    parse_text_as: str = "text",
    force_OCR: bool = False,
    content_types: list[str] = None,
) -> list[dict]:
    """Extracts the contents of each page from a pdf

    Args:
        pdf_path (str): Path to the target pdf
        parse_text_as (str, optional): 'text', 'dict', 'blocks', 'json'. Defaults to "text".
    Returns:
        dict: keys include text, page_number, and annotations
    """
    _first = first_page or 1
    _last = last_page or MAX_PAGE
    log.info(f"Extracting up to {1+(_last - _first)} pages of content from {pdf_path}")
    with pp.open(pdf_path) as document:
        pages = []
        for page_number, page in enumerate(document, start=1):
            if page_number < _first:
                continue
            if page_number > _last:
                return pages

            _text = None
            if content_types is None or "text" in content_types:
                try:
                    if not force_OCR:
                        _text = page.get_text(parse_text_as)
                    if not _text:
                        _text = run_ocr_on_page(pdf_path, page_number)
                except Exception as ex:
                    log.error(f"Exception caught processing page {page_number}.\n{ex}")

            _annotations = None
            if content_types is None or "annotations" in content_types:
                _annotations = [
                    {
                        **_contents_by_type(page, a),
                        # "bounding_box": a.rect,
                        "page": page_number,
                    }
                    for a in page.annots()
                ]

            page = {
                "text": _clean_up_text(_text),
                "page": page_number,
                "annotations": _annotations,
            }
            _out_of = "" if last_page == MAX_PAGE else f" of {_last if _last < 999 else '--'}"
            log.debug(f"Parsed page {page_number}{_out_of} from {pdf_path}")
            pages.append(page)

    return pages


def convert_to_text(
    pdf_path: str,
    output_path: str,
    first_page: int = None,
    last_page: int = None,
) -> None:
    "Extract text from PDF, clean and correct it, then write to a file."

    pages = extract_page_contents(pdf_path, first_page=first_page, last_page=last_page)

    # Write to output file
    with open(output_path, "w", encoding="utf-8") as file:
        file.write("\n".join([p["text"] for p in pages]))

    log.info(f"Processed {pdf_path}, text saved to {output_path}")
