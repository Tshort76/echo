import re
import logging

log = logging.getLogger(__name__)

ALPHANUMERICS = re.compile(r"[\W]+", re.UNICODE)


def strip_gutenberg_bloat(text: str) -> str:
    x00 = text.index("*** START OF")
    x0 = text.index("\n\n", x00)
    x1 = text.rindex("*** END OF")
    log.info(f"Stripped {x0+(len(text)-x1)} characters of Project Gutenberg legalese")
    return text[x0:x1]


def is_gutenberg_text(text: str) -> bool:
    return text.count("Project Gutenberg") > 5


def _fmt_str(raw_title: str) -> str:
    s = raw_title.lower()
    words_to_replace = r"\band\b|\bthe\b"
    x = re.sub(words_to_replace, "", s)
    x = re.sub(r"\s+", "_", x.strip())
    return ALPHANUMERICS.sub("", x)


def name_for_file(contents: dict, ext: str = "mp3") -> str:
    return f"{_fmt_str(contents['title'])}-{_fmt_str(contents['author'])}.{ext}"
