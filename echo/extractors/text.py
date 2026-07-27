import logging
import re
from pathlib import Path

import echo.constants as ec
from echo.document import Block, BlockKind, Document
from echo.extractors.markdown import blocks_from_markdown

log = logging.getLogger(__name__)

ALPHANUMERICS = re.compile(r"[\W]+", re.UNICODE)
#: A run of lines that are all short enough to be hard-wrapped prose.
_WRAP_WIDTH = 90


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


def unwrap_paragraph(paragraph: str) -> str:
    """Join hard-wrapped lines within one paragraph into a single run.

    Plain-text books wrap at a fixed column; a narrator should not hear a pause
    at every line ending. Lines longer than the wrap width are left alone, since
    they are already logical lines.
    """
    lines = [ln.strip() for ln in paragraph.splitlines() if ln.strip()]
    if not lines:
        return ""
    if all(len(ln) <= _WRAP_WIDTH for ln in lines[:-1]) and len(lines) > 1:
        return " ".join(lines)
    return " ".join(lines)


#: Words that start a division in a plain-text book. Used only for plain text,
#: which carries no markup at all — every other format tells us its structure.
_DIVISION = re.compile(
    r"^(chapter|part|book|volume|canto|act|scene|eclogue|section|prologue|epilogue|"
    r"introduction|preface|foreword|appendix)\b",
    re.IGNORECASE,
)


def _looks_like_heading(paragraph: str) -> bool:
    """Conservatively decide whether a lone short line is a division heading.

    Plain text has no markup, so some inference is unavoidable here. The tests
    are deliberately strict — one line, short, no sentence-ending punctuation,
    and either shouted or starting with a division word — so ordinary prose is
    never mistaken for a heading.
    """
    if "\n" in paragraph.strip():
        return False
    line = paragraph.strip()
    if not (3 < len(line) <= 60) or line[-1] in ".!?,;:":
        return False
    letters = [c for c in line if c.isalpha()]
    if not letters:
        return False
    shouted = all(c.isupper() for c in letters)
    return shouted or bool(_DIVISION.match(line))


def blocks_from_plain_text(text: str, detect_headings: bool = True) -> list[Block]:
    """Split plain text into blocks on blank lines, spotting division headings."""
    text = ec.EMPTY_LINES.sub("\n\n", text)
    blocks: list[Block] = []
    for para in text.split("\n\n"):
        if detect_headings and _looks_like_heading(para):
            blocks.append(Block(kind=BlockKind.HEADING, text=para.strip(), level=2))
            continue
        body = unwrap_paragraph(para)
        body = ec.REDUNDANT_SPACES.sub(" ", body).strip()
        if body:
            blocks.append(Block(kind=BlockKind.PARAGRAPH, text=body))
    return blocks


GUTENBERG_START = "*** START OF"
GUTENBERG_END = "*** END OF"
#: Gutenberg's HTML/EPUB editions open with a "The Project Gutenberg eBook of X"
#: banner followed by "Label : value" lines instead of the plain-text asterisk
#: markers, and close with the licence under its own heading.
_GUTENBERG_BANNER = re.compile(r"^\s*The Project Gutenberg eBook of\b", re.IGNORECASE)
_GUTENBERG_FIELD = re.compile(
    r"^\s*(title|author|translator|illustrator|editor|contributor|release date|language|"
    r"credits|original publication|most recently updated)\s*:",
    re.IGNORECASE,
)
_GUTENBERG_LICENCE = re.compile(
    r"(full project gutenberg licen[sc]e|end of (the )?project gutenberg|"
    r"start:? full licen[sc]e)",
    re.IGNORECASE,
)


def strip_gutenberg_blocks(blocks: list[Block]) -> tuple[list[Block], bool]:
    """Drop Project Gutenberg front and back matter from an extracted block list.

    Works on blocks rather than raw text so it applies to EPUB and HTML editions,
    where the boilerplate arrives as its own paragraphs rather than between the
    plain-text ``*** START OF`` markers.
    """
    first = 0
    last = len(blocks)

    explicit_start = next((i for i, b in enumerate(blocks) if GUTENBERG_START in b.text), None)
    if explicit_start is not None:
        first = explicit_start + 1
    elif blocks and _GUTENBERG_BANNER.match(blocks[0].text):
        # Skip the banner plus the run of bibliographic "Label : value" lines.
        first = 1
        while first < len(blocks) and _GUTENBERG_FIELD.match(blocks[first].text):
            first += 1

    explicit_end = next((i for i, b in enumerate(blocks) if GUTENBERG_END in b.text), None)
    if explicit_end is not None:
        last = explicit_end
    else:
        licence = next(
            (i for i, b in enumerate(blocks) if b.kind == BlockKind.HEADING and _GUTENBERG_LICENCE.search(b.text)),
            None,
        )
        if licence is not None:
            last = licence

    if first == 0 and last == len(blocks):
        return blocks, False
    kept = blocks[first:last]
    if not kept:
        return blocks, False
    log.info(f"Stripped {len(blocks) - len(kept)} block(s) of Project Gutenberg front/back matter")
    return kept, True


def extract_txt(path: Path) -> Document:
    text = Path(path).read_text(encoding="utf-8")
    provenance = {"backend": "plain-text"}
    if is_gutenberg_text(text):
        text = strip_gutenberg_bloat(text)
        provenance["gutenberg_stripped"] = True
    return Document(blocks=blocks_from_plain_text(text), source_path=Path(path), provenance=provenance)


def extract_markdown(path: Path) -> Document:
    md = Path(path).read_text(encoding="utf-8")
    blocks = blocks_from_markdown(md)
    title = next((b.text for b in blocks if b.kind == BlockKind.HEADING and b.level == 1), None)
    return Document(
        blocks=blocks,
        title=title,
        source_path=Path(path),
        provenance={"backend": "markdown"},
    )


def to_chunks(text: str, max_chars: int = None) -> list[str]:
    """Split text into chunks of at most ``max_chars``, preferring paragraph then
    sentence boundaries so chunk seams land where speech naturally pauses."""
    max_chars = max_chars or ec.CHUNK_SIZE

    # Note: re.sub returns a new string — the results have to be assigned. The
    # original code called these and discarded them, so normalization never ran.
    text = ec.EMPTY_LINES.sub("\n\n", text)
    text = ec.REDUNDANT_SPACES.sub(" ", text)

    chunks: list[str] = []
    current_chunk = ""

    for para in text.split("\n\n"):
        para = para.strip()
        if not para:
            continue

        if len(current_chunk) + len(para) + 2 > max_chars and current_chunk:
            chunks.append(current_chunk.strip())
            current_chunk = ""

        if len(para) > max_chars:
            for sentence in ec.SENTENCES.split(para):
                if len(current_chunk) + len(sentence) + 1 > max_chars and current_chunk:
                    chunks.append(current_chunk.strip())
                    current_chunk = ""
                current_chunk += sentence + " "
        else:
            current_chunk += para + "\n\n"

    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    return chunks
