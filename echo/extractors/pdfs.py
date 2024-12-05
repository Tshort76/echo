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
from PyPDF2 import PdfReader

load_dotenv()
log = logging.getLogger(__name__)


def extract_embedded_text(pdf_path: str, start_page_num: int = 0, end_page_num: int = 9999) -> list[str]:
    """Extract text from a pdf as a sequence of strings representing page text

    Args:
        pdf_path (str): file path to the pdf
        start_page_num (int, optional): Starting page for extraction. Defaults to 0.
        end_page_num (int, optional): Ending page for extraction. Defaults to 9999.

    Returns:
        list[str]: sequence of page contents (each page is one string)
    """
    reader = PdfReader(pdf_path)
    pages = []
    for page_num, page in enumerate(reader.pages):
        if page_num > end_page_num:
            break
        if page_num >= start_page_num:
            if page_num % 10 == 0:
                log.info(f"Processed {page_num - start_page_num} pages ...")
            pages.append(page.extract_text())
    return pages


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


def _greyscale_image(image: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]
    return gray


def _crop_page_edges(image: np.ndarray, edge_crop_percent: float = 0.05) -> np.ndarray:
    h, w = image.shape[:2]
    crop_h = int(h * edge_crop_percent)
    crop_w = int(w * edge_crop_percent)

    return image[crop_h:-crop_h, crop_w:-crop_w]


def extract_text_from_scanned_pdf(pdf_path: str) -> str:
    # Convert PDF to images
    poppler_path = os.environ.get("POPPLER_PATH")
    if not poppler_path:
        log.warning(f"Could not find poppler lib.  Did you specify the path in your env?")

    images = convert_from_path(pdf_path, poppler_path=poppler_path)

    # Extract text from each page
    full_text = []
    for image in images:
        x = np.array(image)
        x = _greyscale_image(x)
        # x = _rotate_image(x)
        # x = _crop_page_edges(x, 0.01)
        # cv2.imwrite("output_image.png", x)  # write cleaned image to temp file ... debug
        page_text = pytesseract.image_to_string(x)
        full_text.append(page_text)

    return "\n".join(full_text)


def correct_text_with_llm(text: str) -> str:
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


def _clean_up_text(text: str) -> str:
    # Remove non-printable characters
    text = re.sub(r"[^\x20-\x7E\n]", "", text)
    return text


def extract_text_pages(pdf_path: str, output_path: str, correct_with_llm: bool = False) -> None:
    "Extract text from PDF, clean and correct it, then write to a file."

    raw_text = None
    try:
        raw_pages = extract_embedded_text(pdf_path)
        raw_text = "\n".join(raw_pages).strip()
    except Exception as ex:
        log.error(ex)

    if not raw_text:
        log.debug("No Embedded text was found, parsing as scanned pdf")
        raw_text = extract_text_from_scanned_pdf(pdf_path)

    clean_text = _clean_up_text(raw_text)

    if correct_with_llm:
        clean_text = correct_text_with_llm(clean_text)

    # Write to output file
    with open(output_path, "w", encoding="utf-8") as file:
        file.write(clean_text)

    log.info(f"Processed {pdf_path}, text saved to {output_path}")
