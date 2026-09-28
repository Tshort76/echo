# Workflows

One trace per way in. Each diagram's participants are modules, and each message is a real call read from the source.

## Speak chapters from another program

**In plain language:** a program that already has its text, such as a weekly news digest, hands echo a list of titled chapters and a filename. It gets back one audio file with a chapter mark per chapter, and the start and end time of each.

```mermaid
%%{init: {"theme": "base", "themeVariables": {"fontSize": "14px", "lineColor": "#0B3C5D", "primaryColor": "#1F6F8B", "primaryTextColor": "#FFFFFF", "primaryBorderColor": "#0B3C5D", "clusterBkg": "transparent", "clusterBorder": "#7A8B99", "edgeLabelBackground": "transparent", "actorBkg": "#E06D14", "actorTextColor": "#1A1A1A", "actorBorder": "#A64F0E", "signalColor": "#0B3C5D", "signalTextColor": "#0B3C5D", "labelBoxBkgColor": "#1F6F8B", "labelTextColor": "#FFFFFF"}, "flowchart": {"curve": "basis", "padding": 12}} }%%
sequenceDiagram
  actor Caller
  participant SP as speech.py
  participant TX as text.py
  participant TTS as tts.py
  participant EN as engines
  participant AS as assemble.py
  participant MP as mp3_utils.py
  Caller->>SP: speak_chapters(chapters, "digest.mp3", engine="edge")
  SP->>TX: split_text(chapter.text, max_chars), per chapter
  SP->>TTS: synthesize_script(script, chunks_dir=scratch)
  TTS->>EN: check_available() and check_voice(voice)
  TTS->>EN: synthesize(text, voice, speed, path), bounded and retried
  EN-->>TTS: SynthOutput
  TTS-->>SP: list of Segment
  SP->>AS: assemble(paths, out, chapters=marks, speed=tempo)
  AS->>MP: write_mp3_chapters(out, marks)
  SP->>MP: add_meta_fields(out, title, author, cover)
  SP-->>Caller: SpeechResult with path and chapter marks
```

- **The blocking call wraps an async one.** `speak_chapters` (`echo/speech.py:223`) calls `asyncio.run(aspeak_chapters(...))`, so a caller already in an event loop awaits `aspeak_chapters` (`echo/speech.py:207`) instead. The blocking steps (ffmpeg, tagging) run on a thread with `asyncio.to_thread`.
- **Scratch is private and always removed.** `aspeak_script` (`echo/speech.py:86`) makes an `echo-` folder under `work_dir` or the system temp directory and removes it in a `finally`. Chunks go there unless the caller passed `resume_dir`.
- **An unusable engine or voice fails before any audio is made.** `synthesize_script` (`echo/audio/tts.py:103`) calls `check_available()`, then `check_voice()` for every voice in the script.
- **Progress goes to both a callback and the log.** `on_progress(done, total)` counts utterances. The log line `Progress Report: NN%` counts characters, and the GUI parses that line.

## Make an audiobook from a file

**In plain language:** you point the command at a book file. echo reads its structure, decides what is spoken and where the chapters fall, then has the library read it aloud into one file beside the original.

```mermaid
%%{init: {"theme": "base", "themeVariables": {"fontSize": "14px", "lineColor": "#0B3C5D", "primaryColor": "#1F6F8B", "primaryTextColor": "#FFFFFF", "primaryBorderColor": "#0B3C5D", "clusterBkg": "transparent", "clusterBorder": "#7A8B99", "edgeLabelBackground": "transparent", "actorBkg": "#E06D14", "actorTextColor": "#1A1A1A", "actorBorder": "#A64F0E", "signalColor": "#0B3C5D", "signalTextColor": "#0B3C5D", "labelBoxBkgColor": "#1F6F8B", "labelTextColor": "#FFFFFF"}, "flowchart": {"curve": "basis", "padding": 12}} }%%
sequenceDiagram
  actor You
  participant CLI as create_audio.py
  participant CO as core.py
  participant EX as extractors
  participant NO as normalize.py
  participant SP as speech.py
  You->>CLI: create_audio.py book.epub -e edge
  CLI->>CO: file_to_audio(path, engine, fmt, resume=True)
  CO->>EX: extract(path)
  EX-->>CO: Document
  CO->>NO: apply_rules(doc)
  CO->>NO: build_script(doc, chunk_size, normalizer)
  NO-->>CO: Script
  CO->>SP: speak_script(script, out, resume_dir=book_chunks)
  SP-->>CO: SpeechResult
  CO-->>CLI: output path
  CLI-->>You: exit 0
```

- **The app's settings enter here as arguments.** `file_to_audio` (`echo_app/core.py:183`) passes `.env` values (bitrate, retries, backoff) into `speak_script` at `echo_app/core.py:247`, and asks for a resume folder named `<name>_chunks` beside the output.
- **An LLM normalizer is checked before any audio is made.** `build_script` in `echo_app/core.py:162` calls `check_available()` on the chosen normalizer before building the Script, so a missing model server fails the command rather than falling back for every chunk.
- **A setup problem is an exit code, not a crash.** `create_audio.py` catches `EngineUnavailable` and `NormalizerUnavailable` and returns 1. Other failures propagate and also exit non-zero.

## Find a book on Project Gutenberg and convert it

**In plain language:** you give a title instead of a file. echo searches the free catalogue, picks the best match, downloads it with its cover, and then makes the audiobook exactly as for a file.

```mermaid
%%{init: {"theme": "base", "themeVariables": {"fontSize": "14px", "lineColor": "#0B3C5D", "primaryColor": "#1F6F8B", "primaryTextColor": "#FFFFFF", "primaryBorderColor": "#0B3C5D", "clusterBkg": "transparent", "clusterBorder": "#7A8B99", "edgeLabelBackground": "transparent", "actorBkg": "#E06D14", "actorTextColor": "#1A1A1A", "actorBorder": "#A64F0E", "signalColor": "#0B3C5D", "signalTextColor": "#0B3C5D", "labelBoxBkgColor": "#1F6F8B", "labelTextColor": "#FFFFFF"}, "flowchart": {"curve": "basis", "padding": 12}} }%%
sequenceDiagram
  actor You
  participant CLI as create_audio.py
  participant GB as gutenberg.py
  participant GX as Gutendex
  participant PG as gutenberg.org
  participant CO as core.py
  You->>CLI: create_audio.py -g "Meditations"
  CLI->>GB: fetch(title, author, language, prefer="epub")
  GB->>GX: GET /books/?search=Meditations&languages=en
  GX-->>GB: results
  GB->>GB: rank by title match, then EPUB, then downloads
  GB->>PG: GET the EPUB and the cover, unless cached
  GB-->>CLI: DownloadedBook with path and cover
  CLI->>CO: file_to_audio(path, mp3_meta=title, author, cover)
```

- **Ranking is title relevance, then EPUB availability, then popularity** (`echo_app/gutenberg.py:212`). An exact title match earns nothing extra, because Gutenberg's canonical editions usually carry a subtitle.
- **Downloads are cached by book id** in `~/.cache/echo/gutenberg`, so trying a second voice does not fetch the book again (`echo_app/gutenberg.py:263`).
- **A missing cover never fails a book** (`echo_app/gutenberg.py:313`).
- `--list-matches` stops after the search and prints ids; `--gutenberg-id` skips the search.

## Research a topic and narrate the report

**In plain language:** you give a topic and a name. Gemini Deep Research spends several minutes searching the web and writing a cited report. echo strips the citations out of the spoken version, keeps them in a notes file if you asked, and reads the report aloud.

```mermaid
%%{init: {"theme": "base", "themeVariables": {"fontSize": "14px", "lineColor": "#0B3C5D", "primaryColor": "#1F6F8B", "primaryTextColor": "#FFFFFF", "primaryBorderColor": "#0B3C5D", "clusterBkg": "transparent", "clusterBorder": "#7A8B99", "edgeLabelBackground": "transparent", "actorBkg": "#E06D14", "actorTextColor": "#1A1A1A", "actorBorder": "#A64F0E", "signalColor": "#0B3C5D", "signalTextColor": "#0B3C5D", "labelBoxBkgColor": "#1F6F8B", "labelTextColor": "#FFFFFF"}, "flowchart": {"curve": "basis", "padding": 12}} }%%
sequenceDiagram
  actor You
  participant CLI as create_audio.py
  participant RE as research.py
  participant GM as Gemini API
  participant CO as core.py
  You->>CLI: create_audio.py --research TOPIC --name NAME
  CLI->>RE: research(topic, name, agent, keep)
  RE->>GM: interactions.create(agent, input, background=True)
  RE->>GM: interactions.get(id), every 15 s until done
  GM-->>RE: output_text
  RE->>RE: to_narration_source(report)
  RE-->>CLI: ResearchResult with the Markdown path
  CLI->>CO: file_to_audio(path, mp3_meta=name)
```

- **A run that times out is cancelled, not abandoned** (`echo_app/research.py:269`), since the service bills while it works.
- **Progress is reported on a clock, not on search counts.** The API exposes no search steps mid-run, so a line prints at least every 45 seconds.

## Queue books in the desktop app

**In plain language:** you choose a book and press Create audiobook. If another book is already being made, the new one waits in a queue, and the window works through the queue one book at a time, showing progress and a log.

```mermaid
%%{init: {"theme": "base", "themeVariables": {"fontSize": "14px", "lineColor": "#0B3C5D", "primaryColor": "#1F6F8B", "primaryTextColor": "#FFFFFF", "primaryBorderColor": "#0B3C5D", "clusterBkg": "transparent", "clusterBorder": "#7A8B99", "edgeLabelBackground": "transparent", "actorBkg": "#E06D14", "actorTextColor": "#1A1A1A", "actorBorder": "#A64F0E", "signalColor": "#0B3C5D", "signalTextColor": "#0B3C5D", "labelBoxBkgColor": "#1F6F8B", "labelTextColor": "#FFFFFF"}, "flowchart": {"curve": "basis", "padding": 12}} }%%
sequenceDiagram
  actor You
  participant MW as app.py
  participant Q as jobs.py
  participant W as workers.py
  participant CO as core.py
  You->>MW: Create audiobook
  MW->>MW: convert_tab.gather()
  MW->>Q: holds_output(path), then add(job)
  MW->>Q: pop_next(), when no worker is running
  MW->>W: ConversionWorker(params).start()
  W->>CO: file_to_audio(params), on the worker thread
  W-->>MW: progress and log lines, via Qt signals
  W-->>MW: succeeded(path)
  MW->>Q: finish_current(), then the next job
```

- **Enqueueing is `_on_convert`** (`gui/app.py:1463`): it refuses a second job for an output file already queued, adds the job, and starts it if nothing is running.
- **A batch reports once.** Results collect while the queue drains, and one summary appears at the end (`gui/app.py:1438`). A single book keeps its own success or error dialog.

## Preview a voice

**In plain language:** press the play button beside a voice to hear a short sample at the chosen speed.

```mermaid
%%{init: {"theme": "base", "themeVariables": {"fontSize": "14px", "lineColor": "#0B3C5D", "primaryColor": "#1F6F8B", "primaryTextColor": "#FFFFFF", "primaryBorderColor": "#0B3C5D", "clusterBkg": "transparent", "clusterBorder": "#7A8B99", "edgeLabelBackground": "transparent", "actorBkg": "#E06D14", "actorTextColor": "#1A1A1A", "actorBorder": "#A64F0E", "signalColor": "#0B3C5D", "signalTextColor": "#0B3C5D", "labelBoxBkgColor": "#1F6F8B", "labelTextColor": "#FFFFFF"}, "flowchart": {"curve": "basis", "padding": 12}} }%%
sequenceDiagram
  actor You
  participant MW as app.py
  participant W as workers.py
  participant CO as core.py
  participant EN as engine
  You->>MW: play button
  MW->>W: PreviewWorker(voice, speed, engine).start()
  W->>CO: preview_voice(voice, speed, engine)
  CO->>EN: synthesize(sample text, voice, speed, path)
  CO->>CO: assemble with atempo, only if the engine cannot vary speed
  CO-->>W: path in echo-preview
  W->>W: open in the OS audio player
```

- **`preview_voice` is the only preview implementation** (`echo_app/core.py:96`), and the file name is a slug of engine and voice, so one file per voice is overwritten rather than piling up.

## Not traced here

| Workflow | Why not |
|---|---|
| `bulk_generate.py` | it runs "make an audiobook from a file" for every supported file in a folder, and reports the failures at the end |
| `--list-engines`, `--list-voices` | they print from the engine registry and exit |
| `text_to_mp3`, `file_to_mp3` | thin wrappers over the same pipeline, kept for older callers |
| Building `Echo.app` | a manual build step, described in [architecture.md](./architecture.md) |
| The `/research` Claude command | `.claude/commands/research.md` writes a Markdown report that the file workflow then reads; it has no echo code of its own |
| Refreshing the edge voice list | `echo/audio/voices.py`, run by hand to rewrite `echo/data/voices.csv` |

*Generated from 8ed0ecc on 2026-09-28.*
