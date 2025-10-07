import re
import logging

FIGURE = re.compile(r"^Figure\s+\d")
FOOTNOTE_REF = re.compile(r"([^\d][;,.?!)])\d{1,2}(\s)")
FOOTNOTE = re.compile(r"^\d{1,2}\s.{40,200}$")
MAX_LINE_WIDTH = 80
SENTENCE_END = re.compile(r".+[.!?]\s*$")
ITALICS_START = re.compile(r"_(\w)")
ITALICS_END = re.compile(r"(\w)_")
PAGE_NUM = re.compile(r"\n\d{1,3}\.?\n")


log = logging.getLogger(__name__)


def _line_category(line: str, prev_line: str) -> str:
    # I already joined lines where the word was bro-\nken like this, so fix width of those
    # with min(MAX_LINE_WIDTH,...)
    _prev_len, _len = len(prev_line), min(MAX_LINE_WIDTH, len(line))
    if _len == 1 and line[0].isalpha():
        return ":big-letter"
    if _len < 40 and line[-1].isalnum():
        return ":header"
    if _prev_len == 1:
        return ":block-mid"
    if _len > (_prev_len + 10):
        return ":block-start"
    if _len < (_prev_len + 10):
        return ":block-mid"
    return ":block-end"


def _delimited_line(line: str, category: str) -> str:
    match category:
        case ":header":
            return "\n" + line + "\n"
        case ":big-letter":
            return line
        case ":block-mid":
            return line + " "
        case ":block-start":
            return "\n" + line + " "
        case ":block-end":
            return line + "\n"
    return line + " "


def skip_headers(lines: list[str]) -> list[str]:
    return lines[1:]


def format_for_audio(page_text: str) -> str:
    if not page_text:
        return ""
    page_text = page_text.replace(" . . . ", " ")
    page_text = FOOTNOTE_REF.sub(lambda x: x.group(1) + x.group(2), page_text)
    raw_lines = skip_headers(page_text.splitlines())

    cleaned, _prev = "", raw_lines[0] if raw_lines else None
    for raw_line in raw_lines:  # first line is a page header
        if line := raw_line.strip():
            if FIGURE.match(line) or FOOTNOTE.match(line):
                break  # Figure Captions or Footnotes at bottom of page, no content below
            # elif line.startswith("Open Access") or line.startswith("Originally published"):
            #     break  # Open access journal ... very specific to Asia in the 21st century ... TODO remove
            elif line.isdigit():
                continue  # ignore lines with a single (page) number

            _type = _line_category(line, _prev)
            log.debug(
                f"Line '{line[0:20]}' ... categorized as: {_type}, where len = {len(line)} and prev_len {len(_prev)}"
            )
            _prev = line
            cleaned += _delimited_line(line, _type)

    return cleaned


def smooth_pdf_for_audio(pages: list[dict]) -> str:
    _smooth = ""
    for page in pages:
        page_text = format_for_audio(page["text"])
        _smooth += page_text + ("\n" if SENTENCE_END.match(page_text[-10:]) else " ")
    return _smooth


def smooth_epub_for_audio(epub_content: list[str]) -> str:
    _smooth = ""
    for _content in epub_content:
        text = format_for_audio(_content)
        _smooth += text + ("\n" if SENTENCE_END.match(text[-10:]) else " ")
    return _smooth
