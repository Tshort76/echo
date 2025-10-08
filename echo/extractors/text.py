import re
import logging
import echo.constants as ec

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


def to_chunks(text: str, max_chars: int = ec.CHUNK_SIZE) -> list[str]:
    # Remove excessive whitespace
    ec.EMPTY_LINES.sub("\n\n", text)
    ec.REDUNDANT_SPACES.sub(" ", text)

    chunks = []
    current_chunk = ""

    # Split by paragraphs first
    paragraphs = text.split("\n\n")

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        # If adding this paragraph exceeds max_chars, process current chunk
        if len(current_chunk) + len(para) + 2 > max_chars and current_chunk:
            chunks.append(current_chunk.strip())
            current_chunk = ""

        # If a single paragraph is too long, split by sentences
        if len(para) > max_chars:
            sentences = ec.SENTENCES.split(para)
            for sentence in sentences:
                if len(current_chunk) + len(sentence) + 1 > max_chars and current_chunk:
                    chunks.append(current_chunk.strip())
                    current_chunk = ""
                current_chunk += sentence + " "
        else:
            current_chunk += para + "\n\n"

    # Add the last chunk
    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    return chunks
