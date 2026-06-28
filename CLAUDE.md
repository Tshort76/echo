# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project does

**echo** converts text-based files (PDF, EPUB, TXT, MD) into MP3 audio files using Microsoft's Edge TTS engine. The pipeline is: parse file → clean text → chunk text → TTS via edge-tts → merge chunks → embed MP3 metadata.

## Setup

```bash
python -m venv .venv
./.venv/Scripts/Activate.ps1
pip install -r requirements.txt
```

**External dependencies for scanned/image PDFs (optional):**
- Poppler (add `bin/` to PATH)
- Tesseract OCR: `winget install --id=UB-Mannheim.TesseractOCR -e` (add install dir to PATH)

**`.env` file configuration:**
```
DEFAULT_VOICE="en-GB-SoniaNeural"
DEFAULT_SPEED="1.1"
DEFAULT_OUTPUT_FOLDER="path/to/output"
POPPLER_PATH="C:/Program Files/poppler-24.08.0/Library/bin"
GEMINI_API_KEY="..."   # only needed for deep_research_cli.py
```

## Running

```bash
# CLI entry point
python create_audio.py my_file.txt
python create_audio.py my_file.pdf -o output.mp3 -v en-GB-SoniaNeural -s 1.5
python create_audio.py my_file.epub --meta '{"author": "Author", "title": "Title", "image_path": "cover.jpg"}'
python create_audio.py my_file.txt --save   # also writes intermediate .txt

# Gemini Deep Research → audio (requires google-generativeai installed separately)
python deep_research_cli.py topic_config.json   # JSON with "name" and "topic" keys
python deep_research_cli.py existing_research.txt  # convert existing text to audio
```

## Architecture

```
echo/
  core.py          # Public API: convert_to_text(), file_to_mp3()
  clean.py         # Text normalization for audio (PDF, EPUB, Markdown, Gemini output)
  constants.py     # Env-driven config: DEFAULT_VOICE, DEFAULT_SPEED, CHUNK_SIZE, MAX_THREADS
  extractors/
    text.py        # Gutenberg stripping, to_chunks() for splitting text
    pdfs.py        # PDF text + OCR extraction via pymupdf / pytesseract
    misc.py        # EPUB extraction via EbookLib + BeautifulSoup
  audio/
    tts.py         # edge-tts integration; distributed async chunked TTS
    mp3_utils.py   # MP3 merging (pydub), metadata/cover art embedding (mutagen)
    voices.py      # Voice discovery and caching
create_audio.py    # CLI wrapper around core.file_to_mp3()
deep_research_cli.py  # Gemini Deep Research → clean → audio pipeline
```

### Key data flow

1. `core.convert_to_text()` dispatches on file extension to the appropriate extractor
2. `clean.py` normalizes the text for audio (removes footnotes, page numbers, markdown symbols, repeated lines, etc.)
3. `extractors/text.to_chunks()` splits text into chunks ≤ `CHUNK_SIZE` characters (default 8000) at paragraph/sentence boundaries
4. `audio/tts._distributed_text_to_mp3()` converts each chunk concurrently (up to `MAX_THREADS`, default 4) using edge-tts, writing temp files to a `<name>_chunks/` directory
5. `audio/mp3_utils.merge_audio_files()` concatenates chunks via pydub and deletes the temp directory
6. `audio/mp3_utils.add_meta_fields()` embeds ID3 tags and cover art via mutagen

### TTS behavior

- Short texts (< `CHUNK_SIZE` chars) or IPython environments use a single synchronous TTS call
- Longer texts use `asyncio.gather()` with a semaphore to limit concurrency
- Speed is expressed as a multiplier (e.g. `1.5`) and converted to edge-tts `rate` format (`+50%`)
- Progress is logged as a percentage after each chunk completes

### Gemini Deep Research workflow

`deep_research_cli.py` accepts either a JSON config (`{"name": "...", "topic": "..."}`) or an existing `.txt` file. It writes raw and cleaned outputs to `resources/outputs/geminiDR/` before generating audio. The `clean.clean_gemini_contents()` function strips markdown symbols, roman numerals, subsection headers, footnote refs, tables, and sources blocks.
