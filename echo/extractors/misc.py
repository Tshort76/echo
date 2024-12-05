from ebooklib import epub, ITEM_DOCUMENT
from bs4 import BeautifulSoup


def extract_epub_texts(epub_path: str) -> list[str]:
    """Extract documents of text from the epub file

    Args:
        epub_path (str): path to the epub file

    Returns:
        list[str]: texts from the epub, one text string per embedded document
    """
    book = epub.read_epub(epub_path)
    text_content = []
    for item in book.get_items():
        if item.get_type() == ITEM_DOCUMENT:
            soup = BeautifulSoup(item.content, "html.parser")
            text_content.append(soup.get_text())
    return text_content


# file_path = 'samples/critique_pure_reason-kant.epub'
# contents = extract_epub_texts(file_path)
