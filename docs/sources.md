# External services and data sources

Everything echo reaches that is not on the machine running it, read from the client code rather than from the README.

## At a glance

```mermaid
%%{init: {"theme": "base", "themeVariables": {"fontSize": "14px", "lineColor": "#0B3C5D", "primaryColor": "#1F6F8B", "primaryTextColor": "#FFFFFF", "primaryBorderColor": "#0B3C5D", "clusterBkg": "transparent", "clusterBorder": "#7A8B99", "edgeLabelBackground": "transparent", "actorBkg": "#E06D14", "actorTextColor": "#1A1A1A", "actorBorder": "#A64F0E", "signalColor": "#0B3C5D", "signalTextColor": "#0B3C5D", "labelBoxBkgColor": "#1F6F8B", "labelTextColor": "#FFFFFF"}, "flowchart": {"curve": "basis", "padding": 12}} }%%
flowchart LR
  EDGE["edge · echo/audio/engines/edge.py"]
  LOCAL["kokoro, qwen, mlx · echo/audio/engines/"]
  GB["Gutenberg · echo_app/gutenberg.py"]
  RE["Research · echo_app/research.py"]
  NO["Normalizers · echo_app/normalize.py"]
  PK["Packaging · packaging/fetch_ffmpeg.py"]
  MS{{"Microsoft Edge speech"}}
  GA{{"Google Gemini API"}}
  HF{{"Hugging Face"}}
  GX{{"Gutendex and gutenberg.org"}}
  LL{{"Your local LLM server"}}
  FB{{"ffmpeg build hosts"}}
  EDGE -.-> MS
  LOCAL -. "first use" .-> HF
  GB -.-> GX
  RE -.-> GA
  NO -.-> GA
  NO -.-> LL
  PK -. "build time" .-> FB
  class EDGE,LOCAL,GB,RE,NO stage
  class PK entry
  class MS,GA,HF,GX,LL,FB ext
  classDef entry fill:#E06D14,stroke:#A64F0E,stroke-width:2px,color:#1A1A1A
  classDef stage fill:#1F6F8B,stroke:#0B3C5D,stroke-width:2px,color:#ffffff
  classDef store fill:#387B5B,stroke:#255740,stroke-width:2px,color:#ffffff
  classDef ext   fill:#D9381E,stroke:#9E2815,stroke-width:2px,color:#ffffff
  classDef focus fill:#5C3D67,stroke:#3D2845,stroke-width:2px,color:#ffffff
```

With no key at all, the edge engine and Project Gutenberg work, and Kokoro and Qwen work offline once their assets are downloaded.

## The services

| Service | What is sent | What comes back | Key | When it is down |
|---|---|---|---|---|
| Microsoft Edge speech, `speech.platform.bing.com` over a websocket, through the `edge-tts` package | each chunk's text, the voice and a rate such as `+25%` | MP3 audio and sentence timings | none; the client sends the Edge browser's public token | each chunk is retried with backoff, then the run fails with `SynthesisError` and keeps its chunks for resume |
| Hugging Face | a download request for a local speech model | model files, cached locally | none | the first chunk with a new voice fails; cached voices keep working offline |
| Gutendex, `gutendex.com` | the search terms and language, or a book id | catalogue records with download URLs | none | 3 attempts, then `GutenbergError`; the CLI exits 1 |
| gutenberg.org | a download request for the book and its cover | the EPUB or text, and a cover image | none | the book fails; a failed cover is logged and skipped |
| Google Gemini API, Deep Research | the topic, as an agent interaction | a cited Markdown report, after minutes | `GEMINI_API_KEY` | a terminal status becomes `ResearchError` naming it; a timeout cancels the interaction |
| Google Gemini API, normalization | each chunk's text and a fixed instruction | the rewritten chunk | `GEMINI_API_KEY` | the chunk keeps its original text and a warning is logged |
| Your local LLM server | each chunk's text and the instruction, to `/chat/completions` | the rewritten chunk | whatever the server expects | checked before the run starts; mid-run failures keep the original text |
| evermeet.cx and gyan.dev | a download of a static ffmpeg build, only when building `Echo.app` | a zip holding ffmpeg | none | the build script stops and prints where to get one |

**Edge is an unofficial endpoint.** It is the endpoint Microsoft Edge's Read Aloud feature uses, reached through the community `edge-tts` package. It needs no account, and it occasionally rejects a request with a websocket 403, which is why every chunk is retried.

**Gemini research and normalization use the key's quota.** When Deep Research runs out, it reports `budget_exceeded`, which echo turns into its own message rather than a code error.


**The book text goes to whichever engine you pick.** With Edge, the text is sent to Microsoft. With Kokoro, Qwen or generic mlx, synthesis stays on the machine after the model download. Optional Gemini normalization separately sends text to Google.

## Attribution

The root README carries no attribution section, so it is recorded here in full.

| Source | Used for | Terms |
|---|---|---|
| Project Gutenberg | the books downloaded by `-g` and the GUI's Gutenberg dialog | public domain in the US for most titles; the Project Gutenberg licence applies to their files, and some records are hosted with permission, which echo warns about |
| Gutendex | catalogue search | a free public API over Project Gutenberg's catalogue |
| Microsoft Edge neural voices, through `edge-tts` | optional online voices | Microsoft's service terms; `edge-tts` is GPL-3.0 |
| Google Gemini | optional normalization and research | Google's API terms |
| Kokoro-82M | default local voices | Apache-2.0 |
| ffmpeg, through `imageio-ffmpeg` or a vendored build | joining audio and encoding | LGPL or GPL, depending on the build; the vendored build's licence is bundled beside it |

**A book made from a copyrighted Gutenberg record is not free to redistribute.** `download()` logs a warning for records the catalogue marks as copyrighted (`echo_app/gutenberg.py:277`).

*Generated from 8ed0ecc on 2026-09-28.*
