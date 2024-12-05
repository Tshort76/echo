import re
import logging

log = logging.getLogger(__name__)

ALPHANUMERICS = re.compile(r"[\W]+", re.UNICODE)


def extract_gutenberg_data(file_path: str) -> dict:
    """
    Parses a Project Gutenberg text file to extract the title, author, and book contents.

    Args:
        file_path (str): Path to the Gutenberg text file.

    Returns:
        dict: A dictionary with keys 'title', 'author', and 'contents'.
    """
    title = None
    author = None
    contents = []

    with open(file_path, "r", encoding="utf-8") as file:
        lines = file.readlines()

    # Flags to track the start and end of the book contents
    in_contents = False
    contents_start = "*** START OF"
    contents_end = "*** END OF"

    for line in lines:
        stripped_line = line.strip()

        if not in_contents:
            # Try to extract the title
            if not title and stripped_line.startswith("Title:"):
                title = stripped_line[6:].strip()

            # Try to extract the author
            if not author and stripped_line.startswith("Author:"):
                author = stripped_line[7:].strip()

            # Check for the start of the contents
            if contents_start in stripped_line:
                in_contents = True

        else:
            if contents_end in stripped_line:
                break

            # Append lines to contents
            contents.append(line)

    # Join contents into a single string
    log.debug(f"Parsed {len(contents)} lines of text from {file_path}")
    book_contents = "".join(contents).strip()

    return {"title": title, "author": author, "contents": book_contents}


def _fmt_str(raw_title: str) -> str:
    s = raw_title.lower()
    words_to_replace = r"\band\b|\bthe\b"
    x = re.sub(words_to_replace, "", s)
    x = re.sub(r"\s+", "_", x.strip())
    return ALPHANUMERICS.sub("", x)


def name_for_file(contents: dict, ext: str = "mp3") -> str:
    return f"{_fmt_str(contents['title'])}-{_fmt_str(contents['author'])}.{ext}"
