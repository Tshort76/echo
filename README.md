# echo

Turn PDFs, EPUBs, Markdown and text files into **chaptered audiobooks** using
your choice of text-to-speech engine — Microsoft Edge's free voices, Google's
cloud voices, or a model running locally on your own Mac.

```bash
python create_audio.py my_book.epub
# -> my_book.m4b, with chapter marks, title and author

python create_audio.py -g "Meditations" --author "Marcus Aurelius"
# searches Project Gutenberg, downloads it, and narrates it — cover art included
```

- **Bring your own book, or find one.** Point it at a file, or search Project
  Gutenberg's 75,000 free public-domain books and convert one in a single command.
- **Structure-aware.** Headings become chapters; tables, figures, code blocks,
  footnote markers, running headers and Project Gutenberg boilerplate are left
  out of the narration.
- **Four engines behind one interface.** Switch with `--engine`; add one without
  touching the pipeline.
- **Safe to leave running.** Every chunk is retried, and an interrupted run
  resumes from the chunks already on disk instead of starting the book again.
- **CLI or desktop app.** The GUI is an optional layer; the CLI never depends on it.

# Installation

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

**ffmpeg is required** to join audio and write M4B chapters:

```bash
brew install ffmpeg                  # macOS
# Windows: download from https://ffmpeg.org and put it on PATH
```

## Optional extras

| Extra | Install | What it adds |
| --- | --- | --- |
| Google engines | `pip install -r requirements-google.txt` | `--engine gemini`, `--engine google-cloud`, `--normalize gemini` |
| Local synthesis | `pip install -r requirements-local.txt` | `--engine mlx` (Apple Silicon, offline) |
| Desktop GUI | `pip install -r requirements-gui.txt` | `python echo_gui.py` |
| Hard documents | `pip install docling` | `--docling` for PDFs the fast path mangles |
| Scanned PDFs | `brew install tesseract` | OCR for pages with no text layer |

Scanned-PDF OCR goes through PyMuPDF's built-in Tesseract support, so Poppler,
`pdf2image` and OpenCV are no longer needed.

## `.env` configuration

Every setting has a sensible default; this file only overrides them.

```ini
# Output
DEFAULT_OUTPUT_FOLDER="/Users/you/Audiobooks"
DEFAULT_FORMAT="m4b"            # m4b (chaptered) | mp3
M4B_BITRATE="64k"               # AAC/MP3 bitrate when re-encoding
WRITE_TRANSCRIPT="false"        # also write .srt when the engine reports timings

# Synthesis
DEFAULT_ENGINE="edge"           # edge | gemini | google-cloud | mlx
DEFAULT_VOICE="en-GB-SoniaNeural"
DEFAULT_SPEED="1.25"            # baked into the audio; 1.0 keeps the file re-usable
DEFAULT_CHUNK_SIZE="8000"       # characters per request, capped by the engine's own limit
DEFAULT_MAX_THREADS="4"
DEFAULT_MAX_RETRIES="3"
DEFAULT_RETRY_BACKOFF="2.0"     # seconds before the first retry, doubling after that

# Structure
CHAPTER_HEADING_LEVEL="2"       # headings at or above this level start a chapter
MIN_CHAPTER_CHARS="400"         # fold shorter sections into a neighbour; 0 keeps all

# Project Gutenberg
GUTENBERG_DIR="~/.cache/echo/gutenberg"   # where downloaded books are cached

# Google engines
GEMINI_API_KEY="..."            # for --engine gemini and --normalize gemini
                                # (GOOGLE_API_KEY works too)
GEMINI_TTS_MODEL="gemini-2.5-flash-preview-tts"
GOOGLE_CLOUD_VOICE="en-GB-Neural2-C"

# Local synthesis (Apple Silicon)
MLX_TTS_MODEL="prince-canuma/Kokoro-82M"
MLX_TTS_VOICE="bf_emma"
MLX_LANG_CODE=""                # blank infers the language from the voice name

# Optional LLM text normalization
NORMALIZER="off"                # off | local | gemini
LOCAL_LLM_BASE_URL="http://localhost:1234/v1"
LOCAL_LLM_MODEL="qwen3"
LOCAL_LLM_API_KEY="not-needed"  # most local servers ignore this
GEMINI_TEXT_MODEL="gemini-2.5-flash"      # used by --normalize gemini
NORMALIZER_LENGTH_TOLERANCE="0.25"        # reject a rewrite that drifts this much in length
```

# Speech engines

```bash
python create_audio.py --list-engines     # shows which are ready, and why not
```

### `edge` — Microsoft Edge voices (default)

Free, no account, 322 voices, nothing to install. It reaches an unofficial
endpoint, so it occasionally returns a websocket 403 — echo retries, and a
failed run resumes. It is also the only engine that reports word timings, so
`--transcript` produces an `.srt`.

### `gemini` — Gemini TTS

Needs only `GEMINI_API_KEY`. Thirty expressive prebuilt voices. The TTS models
take no rate parameter, so `--speed` is applied by ffmpeg when the audio is
joined — the result is exact either way.

### `google-cloud` — Google Cloud Text-to-Speech

The best free allowance: **4M Standard / 1M WaveNet characters a month,
permanently** (a 300-page book is roughly 500k characters). The REST API does
**not** accept API keys, so authenticate with Application Default Credentials:

```bash
gcloud auth application-default login
# or: export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
```

### `mlx` — local, on-device (Apple Silicon)

Offline, private, unmetered, Metal-accelerated. `MLX_TTS_MODEL` picks the model
from mlx-audio's catalogue.

> **Kokoro needs Python ≤ 3.13.** Kokoro's `misaki` phonemizer depends on spaCy,
> which has no Python 3.14 wheels. On 3.13 or earlier, `pip install 'misaki[en]'`
> and use the default model. On 3.14, choose a model that needs no phonemizer:
> `MLX_TTS_MODEL=mlx-community/chatterbox-turbo-4bit`. `--list-engines` tells you
> which case you're in.

# Getting a book from Project Gutenberg

Project Gutenberg hosts tens of thousands of public-domain books. echo can search
the catalogue, download one, and narrate it in a single command — no account, no
API key.

```bash
# See what matches before committing
python create_audio.py -g "art of war" --list-matches

     id   downloads  formats            title — author
    132      13,426  epub,text,html     The Art of War — Sunzi, active 6th century B.C.
  17405       7,795  epub,text,html     The Art of War — Sunzi, active 6th century B.C.
  ...                                   (download counts change, so will the order)

# Convert the best match, or pin an exact edition
python create_audio.py -g "art of war"
python create_audio.py --gutenberg-id 132 -e mlx -s 1.5
```

Results are ranked by how well the **title** matches, then by whether an EPUB
edition exists, then by popularity — so the canonical edition wins rather than an
obscure reprint that happens to have an exact title.

Three things happen automatically:

- **EPUB is preferred over plain text.** Gutenberg's EPUBs carry heading markup,
  so you get real chapter marks. The text editions are one long stream.
- **Title, author and cover art** come from the catalogue and are embedded in the
  finished file, so it looks right in a library.
- **Downloads are cached** in `~/.cache/echo/gutenberg`, so trying a second voice
  doesn't re-fetch the book.

Front matter, the licence appendix, and title-page fragments are stripped, and a
byline heading never becomes a chapter name. `Meditations` (#2680) comes out as 17
chapters — the introduction, the twelve books, and the appendices.

In the desktop app, the **Gutenberg…** button beside the input file picker opens
the same search, and fills in the metadata fields for you.

# Usage

## Command line

```bash
# Defaults: edge engine, M4B with chapters
python create_audio.py book.epub

# Pick an engine, voice and speed
python create_audio.py book.pdf -e mlx -v bf_emma -s 1.5

# Plain MP3, with metadata and cover art
python create_audio.py book.txt -f mp3 \
  -m '{"title": "A Great Book", "author": "An Author", "image_path": "cover.jpg"}'

# A page range from a PDF, plus the narrated text and a transcript
python create_audio.py book.pdf --first-page 30 --last-page 120 --save --transcript

# Optional LLM normalization ("Dr." -> "Doctor", "§4.2" -> "section four point two")
python create_audio.py book.pdf --normalize local

# Browse voices
python create_audio.py --list-voices -e gemini
```

| Flag | Meaning |
| --- | --- |
| `-o, --output` | where to write the audio (default: beside the source) |
| `-e, --engine` | `edge`, `gemini`, `google-cloud`, `mlx` |
| `-v, --voice` | voice id for that engine (default: the engine's own) |
| `-s, --speed` | playback multiplier, 0.5–3.0 |
| `-f, --format` | `m4b` (chapters) or `mp3` |
| `-n, --normalize` | `off`, `local`, `gemini` |
| `-m, --meta` | JSON with `title`, `author`, `image_path` |
| `--first-page`, `--last-page` | PDF page range (1-indexed, inclusive) |
| `--force-ocr`, `--docling` | override how a PDF is read |
| `--save`, `--transcript` | also write `.txt` / `.srt` |
| `--no-resume` | ignore chunks left by an interrupted run |
| `--list-engines`, `--list-voices` | inspect what's available |
| `--debug` | verbose logging |
| `-g, --gutenberg` | search Project Gutenberg for this title instead of using a file |
| `--author` | narrow the Gutenberg search |
| `--gutenberg-id` | convert an exact Gutenberg book id |
| `--language` | catalogue language to search (default: `en`) |
| `--list-matches` | show Gutenberg matches with ids, then exit |
| `--prefer` | `epub` (default, keeps chapters) or `text` |

Convert a whole folder with `python bulk_generate.py /path/to/books`.

## Desktop app

```bash
pip install -r requirements-gui.txt
python echo_gui.py
```

A cross-platform PySide6 UI: file pickers plus a **Gutenberg…** search button, an
engine dropdown (engines needing setup are greyed out with the reason), a
filterable voice picker with preview, speed slider, format choice, metadata and
normalization settings behind the gear, live progress and a play button for the
result.

The GUI imports `echo`; the backend never imports the GUI, so the CLI keeps
working without PySide6 installed.

## Build a standalone app (PyInstaller)

Package the GUI into a self-contained, double-clickable app that needs **no
Python install** for end users — `Echo.app` on macOS, an `Echo/` folder with
`Echo.exe` on Windows. PyInstaller cannot cross-compile, so build on each target OS.

### Prerequisites
- Build on the OS you're targeting.
- A dedicated build virtual environment. Python **3.11–3.13** is the safest
  choice for PyInstaller + PySide6.

### Steps
```bash
# 1. Create and activate a build venv
python -m venv .venv-build
source .venv-build/bin/activate          # Windows: .venv-build\Scripts\activate

# 2. Install build dependencies, plus any optional engines you want bundled
pip install -r requirements-build.txt
pip install -r requirements-google.txt   # optional
pip install -r requirements-local.txt    # optional (macOS)

# 3. Vendor a static ffmpeg into vendor/ (bundled into the app)
python packaging/fetch_ffmpeg.py

# 4. Build
python packaging/build_app.py
```

Artifacts land in `dist/`:
- **macOS:** `dist/Echo.app` — double-click to run (or `open dist/Echo.app`).
- **Windows:** `dist/Echo/` — run `Echo.exe`; distribute the whole folder (zip it).

The spec file bundles whichever optional engines are installed in the build venv
and excludes the rest, so the app ships exactly the engines you asked for. To
build manually: `pyinstaller echo_gui.spec --noconfirm --clean`.

### Notes / runtime requirements
- **ffmpeg** is bundled and required. If `fetch_ffmpeg.py` can't download a
  static build (its source URLs can drift), install ffmpeg yourself — the app
  falls back to one on `PATH`. Bundled ffmpeg is GPL/LGPL; keep its `LICENSE.txt`.
- **Internet** is needed at runtime for the `edge`, `gemini` and `google-cloud`
  engines. `mlx` works offline once its model has been downloaded.
- **Scanned PDFs** still need Tesseract installed separately.
- Unsigned apps trip **Gatekeeper** (macOS: right-click → Open, or
  `xattr -dr com.apple.quarantine Echo.app`) and **SmartScreen** (Windows:
  More info → Run anyway).
- Icons are optional: drop `packaging/icons/echo.icns` / `echo.ico` to brand the app.

# Python API

```python
import echo.core as core

# The whole pipeline
core.file_to_audio(
    "resources/your_book.pdf",          # .pdf | .epub | .txt | .md
    output_path="your_book.m4b",
    mp3_meta={"title": "A Great Book", "author": "An Author", "image_path": "cover.jpg"},
    engine="edge",
    voice="en-GB-SoniaNeural",
    speed=1.5,
    fmt="m4b",
)
# -> PosixPath('your_book.m4b')
```

## The stages, individually

```python
import echo.core as core

# 1. Parse into a structured Document (headings, tables, figures, page numbers)
doc = core.extract_document("resources/your_book.pdf")
doc.title, doc.author, doc.char_count
[(b.kind.value, b.text[:40]) for b in doc.blocks[:5]]

# 2. Group into chapters and engine-sized utterances
script = core.build_script(doc, engine_name="edge")
[c.title for c in script.chapters]
len(script.utterances())

# 3. Read the narratable text as a plain string
core.convert_to_text("resources/your_book.epub")[:200]
```

## Choosing a voice

```python
from echo.audio.engines import all_voices, available_engines, get_engine

# Which engines can run right now, and why not if they can't
for engine, ok, reason in available_engines():
    print(engine.name, ok, reason)

# Find British English female voices on the default engine
# (filter on language too — locale "GB" also covers cy-GB Welsh)
[
    v.id
    for v in get_engine("edge").voices()
    if v.language == "en" and v.locale == "GB" and v.gender == "Female"
]
# ['en-GB-LibbyNeural', 'en-GB-MaisieNeural', 'en-GB-SoniaNeural']

# Every voice across every ready engine
len(all_voices())

# Audition one — synthesizes a short sample and opens it
import echo.core as core
core.play_mp3_clip("en-GB-SoniaNeural", speed=1.0)
```

Refresh the bundled edge voice cache (`resources/voices.csv`):

```python
import asyncio
from echo.audio.voices import update_voice_cache_file

asyncio.run(update_voice_cache_file())
```

## Project Gutenberg

```python
import echo.gutenberg as gutenberg
import echo.core as core

for book in gutenberg.search("frankenstein", limit=3):
    print(book.id, book.label, book.available_formats())

# Search, download and narrate in two steps
downloaded = gutenberg.fetch("Meditations", author="Marcus Aurelius")
core.file_to_audio(downloaded.path, mp3_meta=downloaded.as_meta())

# Or pin an exact edition
gutenberg.fetch(book_id=2680, prefer="epub")
```

## Text to audio directly

```python
import echo.core as core

core.text_to_mp3("Hello friend, you look excellent today!", "affirmation.mp3")
# -> PosixPath('affirmation.mp3')
```

## Extracting text only

```python
from echo.extractors.misc import extract_epub
from echo.extractors.pdfs import extract_annotations, extract_pdf

# Highlights and notes from a marked-up PDF
extract_annotations("samples/marked_up.pdf")
# -> [{'type': 'Highlight', 'text': '...', 'color': {...}, 'note': None, 'page': 4}]

extract_pdf("samples/cybernetics.pdf", first_page=30, last_page=30).as_text()
extract_epub("samples/critique_pure_reason-kant.epub").title
```

# Development

```bash
pip install pytest
pytest                  # works from the repo root or from inside test/
```
