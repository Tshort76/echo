import re
import logging
from collections import Counter

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


def _format_page_for_audio(page_text: str) -> str:
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
        page_text = _format_page_for_audio(page["text"])
        _smooth += page_text + ("\n" if SENTENCE_END.match(page_text[-10:]) else " ")
    return _smooth


def format_for_audio(text: str) -> str:
    x = ITALICS_START.sub(lambda x: x.group(1), text)
    x = ITALICS_END.sub(lambda x: x.group(1), x)
    x = PAGE_NUM.sub("", x)
    x = x.replace("—", " ").replace("--", " ")
    x = x.replace("\n\n", "\r")
    x = x.replace("\n", " ")
    x = x.replace("\r", "\n\n")
    return x


def remove_repeat_lines(text: str) -> str:
    counts = Counter([l.strip()[0:120] for l in text.splitlines() if l.strip()])
    redundant_lines = [k for (k, cnt) in counts.most_common(10) if cnt > 5]
    log.info(f"Removing the following repeated lines: {'\n'.join(redundant_lines)}")

    for rline in redundant_lines:
        text = text.replace(rline, "")
    return text
