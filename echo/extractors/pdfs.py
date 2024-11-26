from PyPDF2 import PdfReader
from pathlib import Path
import logging

log = logging.getLogger(__name__)


def extract_pdf_pages(pdf_path: str, start_page_num: int = 0, end_page_num: int = 9999) -> list[str]:
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
