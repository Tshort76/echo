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

**Two virtualenvs already exist in this checkout, and which one you use matters:**

| | Python | State |
| --- | --- | --- |
| `.venv` | 3.14.0 | day-to-day. Has every extra **except a working Kokoro** — `misaki` is installed but `import misaki.en` raises `ModuleNotFoundError: spacy`, so `--engine mlx` reports itself unavailable (correctly, with the right message). |
| `.venv-build` | 3.13.7 | packaging, and the only place **Kokoro actually runs**. Use it for anything touching mlx. |

So `pytest` in `.venv` exercises 3.14 with mlx unavailable; run it in `.venv-build`
too when changing the mlx engine. Neither is the *lite* tier — to test that, make a
throwaway venv with `requirements.txt` + `pytest` (about a minute; see BACKLOG §1).

**The core install is deliberately model-free** — ~100 MB, no ML runtime, no weights,
no local LLM; every voice is an API call. Tiers, with measured `site-packages` sizes:

| File | Size | Adds |
| --- | --- | --- |
| `requirements.txt` | 100 MB | core + `--engine edge` |
| `requirements-api.txt` | 194 MB | + Gemini / Cloud TTS, research, LLM normalization |
| `requirements-pdf-layout.txt` | +180 MB | + `pymupdf4llm` for PDF heading detection |
| `requirements-local-llm.txt` | ~2 GB | + mlx-audio on-device synthesis |

The last name is about the *tier* — "things that run on your machine" — not its
contents: what it installs is a local TTS model (Kokoro), not a chat LLM. The `local`
text normalizer talks HTTP to a server you run and needs nothing from that file.

`pymupdf4llm` is **not** in the core install: it depends on `pymupdf-layout`, which
pulls `onnxruntime` (~75 MB) plus `networkx` and `numpy`. An earlier note here called
it "near-zero added weight" — that was true of an older release and is now wrong by
about 180 MB. When it is absent, `extractors/pdfs.py::layout_markdown()` returns None
and extraction falls back to PyMuPDF's own text layer, recording
`provenance["backend"] == "pymupdf"` instead of `"pymupdf4llm"`. The book still
converts; chapters are inferred rather than detected, and tables are narrated rather
than skipped. Adding a hard dependency back into the core tier needs a real reason.

**It is not strictly better than the fallback, though.** On a *scanned* PDF
(`resources/demo_data/ocr_3_pages.pdf`) `pymupdf-layout` does its own picture-text
recovery instead of deferring to OCR, and returns
`<!, Start of picture text, > IIGroups and StatisticalAt about…` — sentinel markers
around text with the spaces lost. Sixteen of those markers currently survive into the
Script and would be spoken. PyMuPDF's Tesseract OCR handles the same file cleanly, so
the lite tier is *better* here. `--force-ocr` is the workaround; stripping the
sentinels in `extractors/markdown.py` is the fix (BACKLOG §5). Judge extraction
quality per-document, not by which backend cost more to install.

Other extras: `requirements-gui.txt` (GUI), `requirements-build.txt` (PyInstaller),
`pip install docling` (hard PDFs), `brew install tesseract` (OCR for scanned PDFs,
via PyMuPDF's built-in support).

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
  core.py          # Public API: file_to_audio(), extract_document(), build_script(),
                   #   convert_to_text(), preview_voice()
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
      mlx.py       # mlx-audio on Apple Silicon; Kokoro voice decoding + espeak wiring
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
  jobs.py          # ConversionJob/ConversionQueue: the (serial) queue behind "Create audiobook"
  voices.py        # Adapter over echo.audio.engines for the dropdowns
  workers.py       # QThread workers; capture backend logs -> progress bar/log panel
  style.py         # QSS theme: warm-light + Nord-dark Palettes, light/dark/system mode
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

### The mlx engine and Kokoro's phonemizer chain

Verified working on Python 3.13.7 at **RTF 0.053** (≈19× faster than playback on an
M4 Pro). Two traps, both of which cost real debugging time:

**`pip install 'misaki[en]'` does not work.** The extra pulls in
`spacy-curated-transformers`, which constrains spaCy; pip backtracks to a spaCy with
no wheel for the interpreter, builds from source, and fails because that spaCy pins
`cython<3.0` while modern numpy's Cython headers need ≥3.0. Install a modern spaCy
directly instead — see `requirements-local-llm.txt`, which documents the whole set.

**Kokoro requires a working espeak fallback, and doesn't say so.** misaki returns
`phonemes=None` for out-of-dictionary words; Kokoro then raises
`unsupported operand type(s) for +: 'NoneType' and 'str'` on the first unusual word
("ebook" suffices). misaki merely logs "espeak not installed on your system" and
continues, so it surfaces during synthesis rather than at startup — and mlx-audio
re-raises the underlying ImportError as a generic "install misaki", which points at
the wrong thing.

`_wire_espeak()` fixes this without a system install: `espeakng-loader` ships
espeak-ng as a wheel, and phonemizer's `EspeakWrapper.set_library()` can be pointed at
it. `check_available()` calls it, so a missing piece is reported up front instead of
after three failed retries — which is what happened before, because the check only
probed `misaki.en` and declared the engine ready.

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
readable pages. Verified end-to-end on Tesseract 5.5.3 against
`resources/demo_data/ocr_3_pages.pdf`: 3 pages, 7,294 characters, clean prose, both
as the automatic no-text-layer fallback and under `force_ocr` (which reports
`provenance["backend"] == "ocr"`).

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
| `budget_exceeded` | its own message — quota exhausted, not a code fault |
| `requires_action` | the collaborative-planning pause; refused clearly rather than polled forever |
| `failed`, `incomplete`, `cancelled` | `ResearchError` naming the status and any detail |

A run takes several minutes (measured: 8.9 min for a focused topic on the standard
agent), so `run()` takes an `on_progress` callback (the CLI logs it, the GUI dialog
shows it) and enforces a timeout that **cancels** the interaction rather than
abandoning a running job.

**The API exposes no search progress mid-run.** `steps` on a polled in-progress
interaction contains only the `user_input` step — the `GoogleSearchCallStep` types
exist in the SDK but are not populated while the agent works. So `_count_searches()`
returns 0 throughout a real run, and progress is reported on a **time** cadence
(`_PROGRESS_EVERY_S`) rather than when the count changes. A count-driven line printed
once and then went silent for nine minutes, which reads as a hung process.

Two live-verified facts worth keeping: a **free-tier key runs these agents** (an
earlier note here claimed paid-tier only — that was inherited from a third-party
answer and was wrong), and the report's own markdown legitimately keeps inline links
and tables. Do not "fix" that: `extractors/markdown.py` unwraps links to their text
and drops tables, so the narrated output is clean while `<name>.notes.md` keeps the
citations. Verify narration cleanliness on the **Script**, not on the `.md`.

The report arrives as cited markdown, which is not narratable. `to_narration_source()`
trims the trailing references section and bracketed citation markers, then the existing
markdown extractor handles the rest — rather than the deleted version's mistake of
asking for markdown and then stripping it. Citations survive in `<name>.notes.md`.

Note the `None`-not-`or` defaults in `__post_init__`: `poll_seconds or default` made
`poll_seconds=0` silently become 15, which is both an un-tunable knob and a 90-second
test suite.

There is a key-free alternative in `.claude/commands/research.md`: a `/research`
command that does the searching and writes the same two files. It needs no echo code
because a `.md` file on disk is already the interface between a researcher and the
pipeline — keep it that way rather than adding a second research backend.

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

**Voice previews live in `core.preview_voice()`, and only there.** There were three
copies (this, the GUI worker, a dead edge-only helper) with three different sample
texts and two destinations; `PreviewWorker` now only moves the call off the UI thread.
Two things it has to get right: the filename is a *slug* of engine and voice, because
`abs(hash(voice))` is per-process and so cached nothing across launches; and when
`supports_speed` is False the speed is applied by ffmpeg into a **separate staged
file** — `out.with_suffix(".mp3")` is `out` itself for an mp3 engine, and ffmpeg's
`-y` truncates its output before reading, which silently yields a preview ~30% short
instead of an error.

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

**"Create audiobook" enqueues; the window drains one job at a time.** The model is
`gui/jobs.py` (`ConversionQueue`, pure state + a `changed` signal); the button stays
enabled while a job runs so the next click queues another book. Serial is a
decision, not a limitation — see BACKLOG §6: within a book the synthesizer already
saturates `engine.max_concurrency`, so parallel books would double connections
against the same endpoint, not throughput. The status line describes only the
current job; the count of waiting jobs lives on the `≡` button beside the play
button, which opens `QueueDialog` (now-converting + removable waiting list, kept
live by `changed`). Mid-batch there are no per-job dialogs — results accumulate in
`MainWindow._batch` and one summary appears when the queue drains; a single-job
batch keeps the original success/error dialogs. A second job writing to the same
output path is refused up front (`holds_output`), since it would clobber the first.

**Theming: two `Palette`s behind one stylesheet.** `gui/style.py` defines
`MATERIAL_LIGHT` (cool greys, deep teal accent — the qt-material tradition) and
`NORD_DARK` (nordtheme.com); both are cool blue-greys, so the two modes read as one
app in two lights rather than two apps. `_stylesheet(p)`
interpolates whichever is active — no hex codes live outside the two dataclasses.
The *appearance mode* (`light` | `dark` | `system`) persists in `QSettings`
("echo"/"echo", key `appearance`), is chosen from the settings dialog's Appearance
row (applied immediately via `set_theme_mode`), and `watch_system_theme()` re-themes
live when the OS flips while in system mode. Two dark-specific traps: Nord's accent
is *light*, so `on_accent` text is dark there (a hardcoded white-on-accent would
vanish); and the pixel tests parameterize their ink check on the field background —
`apply_theme(app, mode="light")` in fixtures, never bare `apply_theme(app)`, which
reads the developer's own persisted setting and makes tests flaky across machines.

**You can see the UI without a display, and you should.** Qt's offscreen platform
renders the real widgets, and `QWidget.grab()` returns a `QPixmap` you can save and
look at — so a visual change can be checked from a terminal or a background session:

```python
import os; os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtWidgets import QApplication
from gui.style import apply_theme
from gui.app import MainWindow
app = QApplication([]); apply_theme(app)
w = MainWindow(); w.resize(880, 720); w.show(); app.processEvents()
w.grab().save("/tmp/echo-ui.png")          # then open or Read the PNG
```

`SettingsDialog()`, `GutenbergDialog()` and `ResearchDialog()` render the same way.
This is worth reaching for before *and* after a styling change: the combo-box bug
below was invisible in the stylesheet and obvious in a screenshot, and a pixel count
alone was not enough — a first fix scored "arrow present" while actually drawing a
grey blob. Count pixels to catch regressions, but look at the image to judge design.

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

**Styling `QComboBox::drop-down` deletes the arrow.** The theme once set
`QComboBox::drop-down { border: none; width: 22px }`, which is enough to stop Qt
painting its own indicator — and since a stylesheet cannot describe a glyph, the
arrow was simply gone. Every dropdown in the app rendered identically to a
`QLineEdit`. So: style that sub-control only when also supplying an image, which is
why `style.chevron_asset()` paints one with `QPainter` into the temp directory
(nothing to bundle or resolve in a frozen build) and `_combo_rules()` returns **""**
when it can't — half-styling is worse than none.

Two smaller Qt facts found alongside it. A *state-dependent* arrow image
(`QComboBox:hover::down-arrow { image: … }`) is positioned against the widget rect
rather than the drop-down rect, so it paints a second chevron in the middle of the
field; use one image and put hover feedback on the border instead. And the CSS
zero-size-plus-borders triangle trick does **not** work here — Qt renders it as a
small filled rectangle.

`test/test_gui.py::TestDropdownsLookLikeDropdowns` guards this **in pixels**
(`widget.grab()`, then count non-background pixels in the drop-down strip, and assert
a `QLineEdit` has none). It has to be pixels: the original bug left a perfectly valid
stylesheet, so any assertion about the QSS text would have passed. Verified to fail
against the old rule before being relied on.

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
