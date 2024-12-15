import logging
import os
import re
from pathlib import Path

import cv2
import numpy as np
import pytesseract
import requests
from dotenv import load_dotenv
from pdf2image import convert_from_path
import pymupdf as pp

from typing import Union, Optional

load_dotenv()
log = logging.getLogger(__name__)

UNPRINTABLES = re.compile(r"[^\x20-\x7E\n]")
EXTRA_SPACE = re.compile(r"\s{2,}")
MAX_PAGE = 999999


def name_for_file(pdf_path: str, ext: str = "mp3") -> str:
    p = Path(pdf_path)
    return p.name.replace(p.suffix, "." + ext)


def _rotate_image(img: np.ndarray) -> np.ndarray:
    coords = np.column_stack(np.where(img > 0))
    angle = int(cv2.minAreaRect(coords)[-1])
    # angle = 0
    log.debug(f"Image angle found to be {angle}")

    # # The cv2.minAreaRect returns values in the range [- 90 to 0)
    # if angle < -45:
    #     angle = -(90 + angle)
    # else:
    #     angle = -angle

    # Rotate the image to deskew
    (h, w) = img.shape[:2]
    center = (w // 2, h // 2)
    M = cv2.getRotationMatrix2D(center, angle, 1.0)
    rotated = cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)

    return rotated


def _correct_text_with_llm(text: str) -> str:
    "Perform error correction on text using OpenAI's API."
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        log.warning("No API key provided, skipping LLM error correction.")
        return text

    # OpenAI API endpoint for text correction
    url = "https://api.openai.com/v1/chat/completions"

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    payload = {
        "model": "gpt-3.5-turbo",
        "messages": [
            {
                "role": "system",
                "content": "You are a text error correction assistant. Fix spelling, grammar, and formatting issues.",
            },
            {"role": "user", "content": f"Correct the following text, preserving its original meaning:\n\n{text}"},
        ],
    }

    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        corrected_text = response.json()["choices"][0]["message"]["content"]
        return corrected_text
    except Exception as e:
        log.warning(f"Error during LLM correction: {e}")
        return text


def _crop_page_edges(image: np.ndarray, edge_crop_percent: float = 0.05) -> np.ndarray:
    h, w = image.shape[:2]
    crop_h = int(h * edge_crop_percent)
    crop_w = int(w * edge_crop_percent)

    return image[crop_h:-crop_h, crop_w:-crop_w]


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
        # x = _rotate_image(x)
        # x = _crop_page_edges(x, 0.01)
        # cv2.imwrite("output_image.png", x)  # write cleaned image to temp file ... debug
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
            _out_of = "" if last_page == MAX_PAGE else f" of {_last}"
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
