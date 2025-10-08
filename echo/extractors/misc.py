from ebooklib import epub, ITEM_DOCUMENT
from bs4 import BeautifulSoup


def extract_epub_text(epub_path: str) -> str:
    """Extract documents of text from the epub file

    Args:
        epub_path (str): path to the epub file

    Returns:
        str: text from the epub, embedded documents are concatenated
    """
    book = epub.read_epub(epub_path)
    text_content = []
    for item in book.get_items():
        if item.get_type() == ITEM_DOCUMENT:
            soup = BeautifulSoup(item.content, "html.parser")
            text_content.append(soup.get_text())
    return "".join(text_content)
