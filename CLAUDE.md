# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project does

**echo** converts text-bearing files (PDF, EPUB, TXT, MD) into chaptered audiobooks
(M4B by default, MP3 optionally). Books can come from disk or be searched for and
downloaded from Project Gutenberg. The pipeline has five stages:

```
extract    -> Document    structured blocks: headings, prose, tables, figures, pages
normalize  -> Script      chapters of engine-sized utterances (rules, optionally + LLM)
synthesize -> Segment[]   one audio file per utterance, retried and resumable
assemble   -> .m4b/.mp3   ffmpeg concat, chapter marks, optional .srt
tag                       ID3/MP4 metadata and cover art via mutagen
```

The key design point is that the thing passed between stages is a **`Document`**,
not a string — that is what makes chapters, skip-lists and timings possible.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
brew install ffmpeg                  # required to join audio / write M4B
```

Optional extras: `requirements-google.txt` (Gemini + Cloud TTS engines),
`requirements-local.txt` (mlx-audio, Apple Silicon), `requirements-gui.txt` (GUI),
`requirements-build.txt` (PyInstaller), `pip install docling` (hard PDFs),
`brew install tesseract` (OCR for scanned PDFs, via PyMuPDF's built-in support).

See the README for the full `.env` reference. The env knobs most likely to matter:
`DEFAULT_ENGINE`, `DEFAULT_VOICE`, `DEFAULT_SPEED`, `DEFAULT_FORMAT`,
`CHAPTER_HEADING_LEVEL`, `NORMALIZER`, `GEMINI_API_KEY`, `MLX_TTS_MODEL`.

## Running

```bash
# CLI
python create_audio.py my_book.epub                       # -> my_book.m4b with chapters
python create_audio.py my_book.pdf -e mlx -v bf_emma -s 1.5
python create_audio.py -g "Meditations" --author "Marcus Aurelius"   # from Gutenberg
python create_audio.py -g "art of war" --list-matches     # inspect matches + ids
python create_audio.py --gutenberg-id 132                 # pin an exact edition
python create_audio.py my_book.txt -f mp3 -m '{"title": "T", "author": "A"}'
python create_audio.py my_book.pdf --first-page 30 --last-page 120 --save --transcript
python create_audio.py --list-engines                     # which engines are ready, and why not
python create_audio.py --list-voices -e gemini

python bulk_generate.py /path/to/books                    # whole folder

# Desktop GUI
python echo_gui.py                                        # needs requirements-gui.txt

# Tests (work from the repo root or from inside test/)
pytest

# Build a standalone app (per-OS; PyInstaller can't cross-compile)
pip install -r requirements-build.txt
python packaging/fetch_ffmpeg.py                          # vendor static ffmpeg -> vendor/
python packaging/build_app.py                             # -> dist/Echo.app | dist/Echo/
```

## Architecture

```
echo/
  core.py          # Public API: file_to_audio(), extract_document(), build_script(), convert_to_text()
  document.py      # The data model: Block/BlockKind, Document, Utterance/Chapter/Script, Timing, Segment
  normalize.py     # Rules normalization, page-artifact detection, Script assembly, optional LLM normalizers
  gutenberg.py     # Project Gutenberg: search via Gutendex, ranked results, cached downloads, cover art
  research.py      # Gemini Deep Research via the interactions agent API (background + polling)
  paths.py         # resource_path(): resolves bundled data in a checkout AND a frozen build
  constants.py     # Env-driven config (separate int/float/bool readers)
  extractors/
    __init__.py    # extract() dispatch on suffix + Docling escalation for sparse PDFs
    markdown.py    # markdown -> Block list (shared by .md files and pymupdf4llm output)
    text.py        # .txt/.md, Gutenberg stripping, plain-text heading detection, to_chunks()
    pdfs.py        # pymupdf4llm -> Document, PyMuPDF built-in OCR, annotation extraction
    misc.py        # EPUB via EbookLib + BeautifulSoup, spine reading order
    docling_ext.py # Optional Docling backend for hard documents
  audio/
    engines/
      base.py      # SpeechEngine protocol, BaseEngine, VoiceInfo, SynthOutput, EngineUnavailable
      __init__.py  # Registry: get_engine(), available_engines(), all_voices(), aliases
      edge.py      # edge-tts (default); rate-string conversion; WordBoundary timings
      google.py    # GeminiEngine (API key) + GoogleCloudEngine (ADC, free tier)
      mlx.py       # mlx-audio on Apple Silicon; Kokoro voice-name decoding
    tts.py         # Orchestration: retry, resume, bounded concurrency, progress logging
    assemble.py    # ffmpeg concat, M4B chapters, atempo speed, SRT, durations
    mp3_utils.py   # configure_ffmpeg(); ID3 + MP4 tags and cover art
    wav.py         # Minimal WAV writing for engines that return raw samples
    voices.py      # edge-tts voice cache maintenance (resources/voices.csv)
create_audio.py    # CLI
bulk_generate.py   # Folder-at-a-time CLI
echo_gui.py        # Launcher for the optional desktop GUI
gui/
  app.py           # PySide6 main window: source split-button, engine/voice/speed/format, settings modal
  sources.py       # SourceSelection: what was chosen, how to describe it, and its name
  voices.py        # Adapter over echo.audio.engines for the dropdowns
  workers.py       # QThread workers; capture backend logs -> progress bar/log panel
  style.py         # QSS theme
echo_gui.spec      # PyInstaller config (bundles whichever optional engines are installed)
packaging/         # build_app.py, fetch_ffmpeg.py, icons/
test/              # pytest suite; conftest.py anchors demo-data paths on __file__
```

### The `SpeechEngine` seam

`echo/audio/engines/` is the extension point. An engine declares `name`, `label`,
`audio_suffix`, `max_concurrency`, `max_chars` and `supports_speed`, then implements
`check_available()`, `voices()`, `default_voice()` and `async synthesize()`.

Two attributes carry real weight:

- **`max_chars`** — Cloud TTS rejects requests over 5,000 bytes, well under echo's
  8,000-character default, so `core.build_script()` chunks to
  `min(CHUNK_SIZE, engine.max_chars)`.
- **`supports_speed`** — Gemini TTS has no rate parameter. Rather than ignoring
  `--speed`, the assembler applies it with ffmpeg's `atempo` filter (chained when
  outside 0.5–2.0). Engines that can do it themselves do.

Engines are constructed lazily and cached per process, so importing the registry
never pulls in mlx or the Google SDKs. `check_available()` must raise
`EngineUnavailable` with a message that says what to install or which variable to
set — the GUI shows that text directly and greys the engine out.

### Extraction

Structure comes from parsers, not heuristics: `pymupdf4llm` renders PDFs as
markdown with real headings and tables, and `markdown.py` labels the blocks. The
same parser handles `.md` files. EPUB tags map directly to block kinds. Only plain
text needs inference — `_looks_like_heading()` in `extractors/text.py` — and it is
deliberately strict (one short line, no terminal punctuation, shouted or starting
with a division word).

`extract()` escalates to Docling when a PDF averages under 200 characters per page
(or when `use_docling` is passed). OCR runs through PyMuPDF's own Tesseract bridge;
a missing Tesseract is reported once and does not abort a document that has other
readable pages.

### Project Gutenberg

`echo/gutenberg.py` searches the catalogue through
[Gutendex](https://gutendex.com) and downloads from gutenberg.org, using only the
standard library for HTTP. Four decisions worth preserving:

- **EPUB is preferred over plain text.** Gutenberg's EPUBs carry heading markup, so
  the EPUB extractor finds real chapters; the text editions are one long stream.
- **Ranking is title-relevance, then EPUB availability, then popularity.** Gutendex
  searches titles *and* authors together, so "art of war" also matches a book from
  the "War Office". Note that `_title_relevance` deliberately does **not** reward an
  exact title match: Gutenberg's canonical editions usually carry a subtitle
  ("Frankenstein; Or, The Modern Prometheus"), so an exact-match tier promotes
  obscure reprints over the edition everyone reads.
- **Downloads are cached** by book id under `GUTENBERG_DIR`
  (default `~/.cache/echo/gutenberg`), which is outside the repo so it also works
  from a frozen app.
- **Author names are normalized conservatively**: "Austen, Jane" becomes "Jane
  Austen", but "Marcus Aurelius, Emperor of Rome" is left alone.

`GutenbergBook.copyrighted` is checked and warned about — Gutendex includes a few
records hosted with permission rather than being public domain.

The GUI runs search and download on `GutenbergSearchWorker` /
`GutenbergDownloadWorker` threads; both are plain `QThread`s rather than
`_BaseWorker`s because their results are records and objects, not a path.

### Gemini Deep Research (`echo/research.py`)

A third source of text, alongside a local file and Project Gutenberg.

**Deep Research is an agent, not a model, and not a `generate_content` tool.** This is
the trap: a first attempt at this concluded no such API existed, because it looked in
`types.Tool` and the type names. It actually lives on the client:

```python
client.interactions.create(body={"agent": "deep-research-preview-04-2026",
                                 "input": topic, "background": True})
client.interactions.get(interaction_id)      # poll until terminal
```

Four things that fail at runtime if you get them wrong: it is `agent=`, not `model=`
(the SDK has separate `CreateAgentInteraction` and `CreateModelInteraction` shapes);
agent ids are date-stamped previews; statuses are **lowercase**; and the result is
`output_text`, not an `outputs` list.

Status handling is most of the module's value:

| Status | Handling |
| --- | --- |
| `queued`, `in_progress` | poll; progress from counting search steps |
| `completed` | take `output_text` |
| `budget_exceeded` | its own message — the agents need a **paid-tier** key |
| `requires_action` | the collaborative-planning pause; refused clearly rather than polled forever |
| `failed`, `incomplete`, `cancelled` | `ResearchError` naming the status and any detail |

A run takes 2–15 minutes, so `run()` takes an `on_progress` callback (the CLI logs it,
the GUI dialog shows it) and enforces a timeout that **cancels** the interaction rather
than abandoning a billed job.

The report arrives as cited markdown, which is not narratable. `to_narration_source()`
trims the trailing references section and bracketed citation markers, then the existing
markdown extractor handles the rest — rather than the deleted version's mistake of
asking for markdown and then stripping it. Citations survive in `<name>.notes.md`.

Note the `None`-not-`or` defaults in `__post_init__`: `poll_seconds or default` made
`poll_seconds=0` silently become 15, which is both an un-tunable knob and a 90-second
test suite.

### Normalization

`apply_rules()` always runs: footnote-marker stripping, dash/ellipsis/quote
handling, and `mark_page_artifacts()`, which finds running headers positionally
(short, first-or-last block on its page, recurring across pages) rather than by
frequency — the old frequency approach deleted recurring prose book-wide.

`build_script()` makes two structural judgements beyond splitting on headings:

- **A byline never names a chapter.** Title-page bylines are marked up as headings,
  so without `_BYLINE` a single-story text files its entire body under "By Charlotte
  Perkins Gilman". The byline stays spoken; it just doesn't create a division.
- **Stub sections fold into a neighbour** (`_coalesce_small_sections`). A section
  must be small in *two* senses — under `MIN_CHAPTER_CHARS` **and** under
  `_STUB_FRACTION` of the document's median section — or a genuinely short book with
  brief real chapters would collapse into one. Folded text becomes the next
  section's *prelude*, so it is spoken before that chapter's heading rather than
  after it. Nothing is ever discarded.

Normalizers mirror the engine availability pattern: `check_available()` raises
`NormalizerUnavailable` with a fix-it message, `is_available()` returns
`(ok, reason)`, and `available_normalizers()` feeds the GUI dropdown.
`core.build_script()` calls `check_available()` **before** any synthesis — if LLM
normalization was explicitly requested, silently falling back for every chunk
produces a book that quietly wasn't normalized. The `local` probe treats any HTTP
response (including 404) as reachable, since some OpenAI-compatible servers only
implement `/chat/completions`.

LLM normalization is **off by default** and guarded by `_GuardedNormalizer`: the
result is rejected and the original kept if the length drifts more than
`NORMALIZER_LENGTH_TOLERANCE` (25%), if the model adds a preamble or refuses, if
the response is empty, or on any exception. `local` talks to an OpenAI-compatible
endpoint through `urllib` (no new dependency); `gemini` uses `google-genai`.

### Synthesis

`tts.synthesize_script()` writes `chunk_%05d{suffix}` files into
`<output>_chunks/`. Each utterance gets `MAX_RETRIES` attempts with exponential
backoff. Chunks already on disk with a readable duration are reused, so an
interrupted run resumes. `asyncio.gather(..., return_exceptions=True)` means every
utterance is attempted, and `SynthesisError` names what failed rather than a
half-finished book being assembled. The chunk directory survives failure and is
only deleted after successful assembly.

Progress is logged as `"Progress Report: NN%"` — the GUI parses that exact string,
so don't change the format.

### Assembly

`assemble.py` shells out to ffmpeg's concat demuxer. MP3-in/MP3-out with no speed
change is a **stream copy** (no re-encode, no quality loss, constant memory); M4B
encodes to AAC and attaches chapter marks via an ffmetadata file. Durations come
from mutagen (MP3/MP4) and the WAV header, so the packaged app needs only the one
ffmpeg binary it already bundles — no ffprobe.

### GUI layer

The `gui/` package (PySide6) is an **optional presentation layer** launched with
`python echo_gui.py`. The dependency direction is strictly one-way: the GUI imports
`echo`; the backend never imports the GUI. GUI-only deps stay out of the base
`requirements.txt`.

**One source picker, three sources.** `ConvertTab` holds a
`gui.sources.SourceSelection` — not the text of the input field, which is read-only
and merely *describes* the choice. This exists because a path is a poor description
(a Gutenberg cache file is `pg2680_meditations.epub`; a research report lives in a
temp directory) and because everything downstream used to derive the audio filename
from the input filename, which Deep Research has none of. Hence
`SourceSelection.name`, set in each source's modal and used for the output name and
the default title. The split button's `defaultAction` is Browse, so the common case
is a single click.

Long-running work runs in `QThread` workers that install a temporary logging
handler to forward backend log lines to the UI and parse the progress string. The
engine and normalizer dropdowns are built from `available_engines()` /
`available_normalizers()`, so choices needing setup are disabled with the reason in
their tooltip, and `ConvertTab.gather()` refuses to start a conversion on one.

**A Qt sizing trap worth knowing, hit twice here.** A `QComboBox` in a
`QFormLayout` row derives its `minimumSizeHint` from its *longest item*. A long
item can therefore consume the whole row and squeeze the label column to **zero
width** — the label is still present and `isVisible()`, it just renders as nothing,
so it looks like a forgotten label rather than a layout bug. The fix is
`setSizeAdjustPolicy(AdjustToMinimumContentsLengthWithIcon)` plus
`setMinimumContentsLength(...)`; the full text still shows in the popup. The
related failure is a `QCheckBox` label a few pixels wider than its column, which
truncates mid-word. `test/test_gui.py::TestLabelsFit` guards both by walking every
form label and comparing width against `sizeHint()` — keep it passing rather than
eyeballing screenshots.

### Packaging

`python packaging/build_app.py` freezes the GUI with PyInstaller (onedir). Two
correctness pieces:

- `echo/paths.py::resource_path()` resolves bundled data from `sys._MEIPASS` when
  frozen and from the repo root otherwise — used by `constants.py` (voices.csv) and
  `mp3_utils.configure_ffmpeg()` (bundled ffmpeg at `bin/ffmpeg`).
- `echo_gui.spec` probes for optional engine packages and adds them to
  `hiddenimports` when installed, `excludes` when not. Engines are imported lazily,
  so static analysis cannot see them; without this the packaged app would silently
  lose Gemini/Cloud/mlx support.

## Backlog and settled decisions

`BACKLOG.md` is the working list: planned work, verification gaps, and a section of
decisions already made (macOS-only, M4B default, LLM normalization optional, Cloud
TTS needs ADC rather than an API key) plus explicit non-goals. **Read it before
proposing direction changes** — several entries exist specifically to stop settled
questions being re-opened. Update it when work lands.

## Conventions

- Line length 118 (see `pyproject.toml`).
- Requirements are **pinned** — the project is frozen into a shipped binary.
- Optional dependencies are imported inside the function that needs them, with an
  `EngineUnavailable`/`ImportError` message naming the install command.
- Prefer failing loudly with an actionable message over degrading silently. A
  finished audiobook must never be missing content without an error.
