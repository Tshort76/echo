# echo — backlog

Working list for this project. Drawn from the [July 2026 architecture
review](https://claude.ai/code/artifact/eb774d6e-2e37-4e7e-8d6a-f16a894d467d)
plus verification gaps found while implementing it.

Effort tags are rough: **S** = a sitting, **M** = a day or so, **L** = a project.
Tick items off in place; move anything substantial into a commit message so the
reasoning outlives the checkbox.

---

## Where we stand — 29 July 2026

Phases P0–P3 of the review are done, plus several things that were later phases or
were not in the review at all.

| | Shipped in |
| --- | --- |
| P0 correctness pass (9 findings, retry, resume, pinned deps, `pyproject.toml`) | `d15511f` |
| P1 pydub retired — ffmpeg concat, M4B chapters, SRT | `d15511f` |
| P2 `SpeechEngine` seam — `edge`, `gemini`, `google-cloud`, `mlx` | `d15511f` |
| P3 `Document`/`Script` model, structured extraction, PyMuPDF OCR | `d15511f` |
| Optional guarded LLM normalization | `d15511f` |
| Project Gutenberg search + download | `5976efa` |
| README/code audit | `4df3599` |
| `BACKLOG.md`; GUI tests checked in | `e007719` |
| Full CLI/UI parity; normalizer availability checks | `244bcfd` |
| Packaged app rebuilt; the `echo-audio` console script fixed | `b59e26b` |
| Deep Research as a third source, behind one split-button source picker | `7713c87` |
| Deep Research call shape corrected; key-free `/research` command | `699e368` |
| Kokoro on mlx working locally at **RTF 0.053** | `b4dc10a` |
| Lite, model-free install tier — 100 MB, no ML runtime | `a3cd780` |
| `requirements-local-llm.txt` rename; README and backlog refresh | `bbe13a7` |
| Dropdowns given a visible chevron — they had rendered as blank text fields | `37a67ff` |
| Voice preview consolidated from three implementations into one | `2bc5966` |
| GUI conversion queue — "Create audiobook" enqueues, jobs drain serially | this commit |
| Dual theme: Material-teal light + Nord dark, light/dark/system picker, follows the OS live | this commit |

**385 tests** pass with every extra installed; **293** on the lite install (the
full figure re-measured with the queue work, the lite figure in a throwaway
virtualenv one session earlier).
**All four engines are now verified live** against their real services, which was the
biggest open risk when this file was written. `edge` is exercised end-to-end on
markdown, PDF, EPUB, two real Gutenberg books and a Deep Research report.

---

## 1. Verification gaps

Still the highest-value items here, but a much shorter list than when this was written.

- [ ] **Convert a full-length book you actually want to listen to.** (S)
      Nothing else substitutes. It's where the real questions surface: do chapter
      marks land where you expect, is 1.25× right, does the M4B behave in your player.
- [x] ~~**Check the offscreen GUI smoke test into `test/`.**~~ Done — `test/test_gui.py`.
      It had been living in a throwaway temp directory. Covers the engine dropdown
      against the backend registry, per-engine voice lists, format/suffix syncing,
      every `gather()` validation path, the source picker and each source dialog.
      Notably it asserts that `gather()`'s keys stay assignable to
      `core.file_to_audio`'s signature, which is how the GUI and backend drift apart
      silently.
- [x] ~~**Exercise `--engine gemini` against the real API.**~~ Works, with a real key.
      Coverage is narrow — one voice, short passages — so a full book on `gemini` is
      still unproven, but the path is no longer theoretical.
- [x] ~~**Exercise `--engine google-cloud` end-to-end.**~~ Works — the free-tier path
      is real, via the ADC credentials already on this machine.
- [x] ~~**Run `--engine mlx` through echo's own wrapper.**~~ Works. Chatterbox Turbo on
      3.14, and **Kokoro on 3.13 at RTF 0.053** — ≈19× faster than playback, so a
      ten-hour book synthesizes in about half an hour, offline and unmetered. Getting
      there needed two fixes: the documented `misaki[en]` install is unbuildable, and
      Kokoro needs an espeak fallback it never asks for (see
      `requirements-local-llm.txt` and `_wire_espeak()`).
- [x] ~~**Exercise Deep Research against the real agent API.**~~ Works, on a
      **free-tier** key: 8.9 minutes, 4 chapters, 14.5 minutes of audio. The first
      call failed, for a reason the tests could not have caught — see §2.
- [x] ~~**Rebuild the packaged app.**~~ Built on Python 3.13 (`.venv-build`) →
      `dist/Echo.app`, 357 MB. Launches cleanly, finds its bundled ffmpeg and
      `voices.csv`. The spec's engine probing works: `google.genai` (311 modules) and
      `google.cloud.texttospeech` (26) are compiled into the PYZ archive, `mlx_audio`
      correctly excluded since it wasn't in the build venv.
      **Note:** they live *inside* the archive, not as directories on disk — check
      the PYZ, not the filesystem, when verifying a future build.
      ~~**Now stale:** that build predates Deep Research, the source picker and the
      lite tier, so it is three features behind.~~ **Rebuilt 2 Aug 2026** from
      current source (queue included): 563 MB, all three optional engine stacks +
      ffmpeg bundled, launches and holds its event loop offscreen. Only *boot* is
      verified — see the mlx-bundle item below for what isn't.
- [x] ~~**Exercise the OCR path.**~~ Works. Tesseract 5.5.3 turns out to be installed
      on this machine already, so no `brew install` was needed:
      `resources/demo_data/ocr_3_pages.pdf` OCRs all three pages to 7,294 characters
      of clean prose, with `provenance["ocr_pages"] == [1, 2, 3]`. Verified twice over
      — as the automatic fallback when a page has no text layer, and under
      `--force-ocr` (`backend == "ocr"`). It also found a defect in the *other*
      backend; see §5.
- [ ] **Exercise the Docling escalation.** (S) Needs `pip install docling`.
      `_try_docling()` has only been seen degrading gracefully, never succeeding.
- [x] ~~**Run `bulk_generate.py` once.**~~ Works, including `--rename`.
- [x] ~~**Verify `pip install -e .` and the `echo-audio` console script.**~~ This found
      a real bug: `pyproject.toml` listed only *packages*, so the top-level
      `create_audio` module was never installed and `echo-audio` died with
      `ModuleNotFoundError`. Fixed with `py-modules`; verified from an unrelated cwd.
- [ ] **Automate the four-tier test run.** (S) The suite is tier-aware now, but
      nothing enforces that: it was proven by hand across four virtualenvs, so the
      next dependency change can quietly re-break the lite install exactly as the
      last one did (§2). A script that builds each tier in a temp venv and runs
      `pytest` would turn a habit into a check.
      **Cheaper than it looks:** `python3 -m venv` + `pip install -r requirements.txt
      pytest` in a throwaway directory took about a minute, and the lite suite runs in
      16 s. The manual version is two commands — worth wrapping rather than repeating.
- [ ] **Verify `mlx-audio` inside the frozen app.** (M) Half done: the 2 Aug 2026
      rebuild *bundles* the mlx stack (the spec probes installed packages, and
      `.venv-build` now has it) and the app boots — but nobody has synthesized with
      the mlx engine *from the frozen app*. The original risk stands: mlx,
      transformers and spaCy bring data files, and `espeakng-loader`'s dylib plus
      spaCy's `en_core_web_sm` model are things PyInstaller will not find by static
      analysis. Expected failure mode is graceful (`check_available()` exercises the
      whole phonemizer chain, so the engine should grey out with a reason rather
      than die mid-book) — but "should" is the word doing the work. Launch the app,
      read the mlx engine's tooltip, and run a short book on it. Expect to add
      `datas` entries to `echo_gui.spec`.
- [ ] **A round-trip integrity test: text → speech → text.** (M) The one thing no
      current test does is check that the audio actually *contains the words*.
      Everything else verifies plumbing — chunk counts, durations, chapter marks —
      so a chunk dropped or assembled out of order would still pass.

      Design matters here, or it will be flaky. Do **not** compute word error rate
      against arbitrary prose: ASR disagrees about numbers, punctuation, homophones
      and proper nouns, so any threshold is a guess that rots. Instead seed the
      passage with distinctive *ordinal* markers — NATO words work well — and assert
      that all of them appear **and in the right order**. That is a decidable check,
      and it is exactly sensitive to the failures that matter (a lost chunk, a
      misordered concat, normalization eating text).

      Prototyped this far: a 6-marker script at `chunk_size=120` produces 12 chunks
      and a correct MP3, so the synthesis half is proven. The ASR half needs a
      Whisper model that ships a HuggingFace processor — `mlx-community/whisper-tiny`
      and `whisper-base-mlx-q4` do **not** (`processor=False`, and `generate()` then
      raises). `mlx-community/whisper-large-v3-turbo-asr-fp16` is mlx-audio's own
      default and probably does, but it is ~1.6 GB to fetch.

      Keep it out of the default suite — mark it `integration` and let `pytest -m
      integration` opt in. It needs a model download, a network round trip for
      `edge`, and tens of seconds.

## 2. Issues found

Kept because the *class* of each mistake is likely to recur — and because four of
them were wrong claims in documentation written here, which is cheaper to record than
to rediscover. All are fixed; the two open consequences follow the table.

| What went wrong | The general lesson |
| --- | --- |
| `pymupdf4llm` was described as "near-zero added weight". It pulls `pymupdf-layout` → `onnxruntime`: **180 MB**, and 64% of the whole install. | A transitive dependency's cost is invisible in a requirements file. Measure `site-packages`; don't reason about it. It was also assumed to be strictly better than the fallback, which turned out to be false on scanned pages (§5) — "heavier" is not "better". |
| The `interactions.create(body={…})` call shape was invented, and the unit tests passed anyway — because the *fake* accepted `body=` too. | **A fake that accepts more than the real client tests nothing.** The fake now mirrors the real signature and its key whitelist, and a test asserts it rejects the old shape. |
| Deep Research was documented as paid-tier only. A free-tier key runs it. | The claim came from a third-party answer, corroborated only circumstantially by the existence of a `budget_exceeded` status. Circumstantial support for a borrowed claim is not verification. |
| Kokoro's real-time factor was quoted as 0.34 from a blog post. Measured here: **0.053**. | Same shape as above, and wrong by 6×. Measure on the machine that will run it. |
| `misaki[en]`'s install failure was diagnosed as "spaCy has no 3.13 wheels". The real cause is pip backtracking to an old spaCy that pins `cython<3.0` against numpy 2.x headers. | A plausible diagnosis that predicts the same symptom is still the wrong diagnosis — and this one pointed the fix in the wrong direction (change interpreter, rather than pin spaCy forward). |
| The mlx engine's `check_available()` probed only `misaki.en`, reported **ready**, then died three retries deep into synthesis on the first out-of-dictionary word. | An availability check that doesn't exercise the whole chain is worse than none: it converts a startup error into a mid-book one. |
| `poll_seconds or default` turned an explicit `0` into 15 — an un-tunable knob and a 90-second test suite. The same `or`-versus-`None` bug sat in `GeminiEngine` and `GeminiNormalizer`, where `api_key=""` fell through to the environment. | `or` is not a default; it means "falsy is absent". Use a `None` sentinel. The Gemini variant passed its tests only because the machine had no key at all. |
| Deep Research progress was reported by counting search steps. The API never populates `steps` mid-run, so it printed once and went silent for nine minutes. | A progress indicator driven by a field that stays empty reads exactly like a hung process. Fall back to a time cadence. |
| Six tests assumed optional dependencies were installed — asserting a specific PDF backend, or that Gemini is available with a key when the SDK is absent. | Nothing had ever run the suite on a minimal install, so the tests encoded the developer's machine. Hence the four-tier item in §1. |
| `wav.py` said a WAV header was "not worth a dependency" — directly above an unconditional `import numpy`. | Comments are not enforced. This one was load-bearing for the lite tier, and wrong. |
| Every dropdown in the GUI rendered as a blank text field. `QComboBox::drop-down` was styled with `border: none`, which stops Qt drawing its own indicator — and a stylesheet cannot supply a glyph, so the arrow was simply absent. | A half-styled sub-control is worse than an unstyled one, and the stylesheet still *looked* correct. Guard rendering in pixels, and look at a screenshot: the replacement's first attempt passed a pixel count while drawing a grey blob. |
| The voice preview cached its temp file under `abs(hash(voice))`. Python randomizes string hashing per process, so "repeated previews reuse the file" was never true across launches, and each run left another file behind. | `hash()` is not a stable identifier — not across processes, not on disk, not in a URL. Use a slug. |
| Consolidating the three preview implementations, the ffmpeg speed fallback passed `out` as both input and output — and since `-y` truncates the output before reading, the preview came out ~30% short rather than failing. | The mocked test passed straight through it; a single live run caught it. Same lesson as the Deep Research fake: a test double will not tell you what the real tool does with your arguments. |

Two open risks from the same work:

- [ ] **The Deep Research agent ids are date-stamped previews** and will age out. (S)
      `AGENTS` is one dict in `echo/research.py` and `RESEARCH_AGENT_ID` overrides it
      outright, so a rename is a one-line fix — but nothing detects the rename except
      a failed run. A clearer error when the agent id is rejected would help.
- [ ] **Lite-tier PDFs lose their chapter *names*.** (S) Measured today on
      `america_against_america_sample.pdf`: with `pymupdf4llm` the chapter is
      `"Preface"`, a genuinely detected heading; on the text-layer fallback the plain
      text heuristic finds no heading at all, so the whole document files under a
      chapter named after the file. Acceptable, documented and logged — but that
      heuristic is now the only structure a lite install gets from a PDF, and it has
      never been tuned against a book-length one (see §5).
      **Correction:** an earlier note here said this cost "2 chapters, down to 1".
      The count is 1 either way; what changes is whether the chapter has a real name.

## 3. Engines

- [ ] **sherpa-onnx + Kokoro-82M offline engine.** (M) Deferred by decision, still
      wanted — though less urgent now that Kokoro runs on mlx. The remaining argument
      is **Python 3.14**: sherpa-onnx does its own ONNX grapheme-to-phoneme, so it
      needs neither `misaki` nor spaCy, which is the entire 3.14 blocker. Apache-2.0,
      no PyTorch.
- [x] ~~**Kokoro via mlx in a Python 3.13 environment.**~~ Done — and it was not the
      "just an interpreter change" this entry predicted; see `b4dc10a` and §2.

## 4. Features

From the review's phase 5, plus one thing the review asked for that shipped without it.

- [ ] **Diff preview before LLM normalization is applied.** (M)
      The review said ship the preview *before* the feature; the feature shipped
      first. The guardrails are real (length drift, preamble, refusal, exceptions)
      but there is currently no way to *see* what a model changed in your book.
- [ ] **No way to audition a voice from the CLI.** (S) `--list-voices` prints names
      only; hearing one means calling `core.preview_voice()` in Python. A
      `--preview VOICE` flag is now a two-line addition, since the GUI and the Python
      API already share that one function.
- [ ] **Per-chapter or per-speaker voices.** (M) `Utterance.voice` already exists and
      the orchestrator already honours it — nothing sets it yet. Cheapest real
      feature on this list.
- [ ] **Pronunciation lexicon per book,** carried across runs. (M) Proper nouns and
      jargon are where narration most often goes wrong.
- [ ] **GUI library view** over past conversions. (M)
- [ ] **Two-narrator / dialogue output** via VibeVoice or similar. (L)
- [ ] **Overlap assembly with the next queued book's synthesis.** (S–M) The queue
      is deliberately serial (parallel books just multiply pressure on the same
      TTS endpoint — see §6), but while a finished book's M4B re-encodes to AAC
      the network sits idle. Starting the next job's synthesis during assembly is
      the only real overlap available, worth maybe 5–10% on a batch. Only bother
      if queues of long books become routine.

## 5. Cleanups and smaller fixes

- [ ] **`pymupdf4llm` mangles scanned PDFs, and its markers reach the narration.**
      (S–M) The one item here that produces *audibly wrong output*, found while
      exercising OCR. On `ocr_3_pages.pdf` the layout backend does its own
      picture-text recovery rather than deferring to OCR, and returns sentinel
      markers with the words glued together:

          <!, Start of picture text, > IIGroups and StatisticalAt about the beginning…

      **16 of those markers survive into the Script**, so they would be read aloud.
      The lite path's OCR handles the same file cleanly ("II Groups and Statistical
      Mechanics At about the beginning of the present century, two scientists…").
      Two things to fix: strip the `<!, … picture text, >` sentinels in
      `extractors/markdown.py`, and decide whether a page whose layout text arrives
      wrapped in them should fall through to OCR automatically. `--force-ocr` is the
      workaround today.

      Worth noting for §2's sake: this inverts the assumption that the 180 MB backend
      is strictly better. On scanned pages it is strictly *worse*.
- [ ] **Turn the README's examples into doctests.** (S) Two of them silently rotted
      *within a single session* — a README example is a test that nothing runs. The
      prose rots the same way: the README still described a **Gutenberg…** button
      days after the source picker replaced it.
- [ ] **`requirements-google.txt` is now identical to `requirements-api.txt`.** (S)
      It survives only to document that the two Google engines authenticate
      differently. That belongs in the README; a duplicate file invites installing
      the wrong one.
- [ ] **`requirements-local-llm.txt` installs a local *TTS* model, not an LLM.** (S)
      The name describes the tier — "things that run on your machine" — rather than
      its contents, and the `local` text normalizer needs nothing from it (it speaks
      HTTP to a server you run). The file header now says so. Rename again or leave
      it, but decide rather than drift.
- [x] ~~**Decide the default speed.**~~ Decided 2 Aug 2026: `DEFAULT_SPEED=1.0`.
      Speed is baked into the audio by the engine, so a neutral default keeps the
      file re-usable at any playback speed — players can speed a 1.0× file up, but
      a 1.25× file is 1.25× forever. Override per-run with `-s` or per-machine in
      `.env`.
- [ ] **`--transcript` is a no-op on three of four engines.** (S) Only `edge` reports
      word timings. The GUI checkbox now says so in its tooltip and the backend logs
      it, but the CLI still accepts the flag silently. Consider warning up front when
      the chosen engine cannot honour it.
- [ ] **Nothing prunes stale `*_chunks/` directories.** (S) Failed runs leave them
      deliberately, so a re-run can resume. Add a `--clean` or a sweep on success.
- [ ] **Gutendex is an unmitigated third-party dependency.** (S–M) If it goes away,
      search stops. Project Gutenberg publishes its own catalogue as a fallback.
- [ ] **Gutenberg cover art is 200×290.** (S) Fine for a tag, small for a library
      view; larger sizes may be available in the catalogue.
- [ ] **Decide what to do with the Windows branches.** (S) `echo_gui.spec` and
      `mp3_utils.configure_ffmpeg()` still branch for Windows, but Mac-only was the
      decision. Keeping them is defensible; deciding beats drifting.
- [ ] **A broken `misaki` sits in `.venv`.** (S) Still true, re-checked today: `.venv`
      is Python 3.14 and `import misaki.en` raises `ModuleNotFoundError: spacy`. It
      was installed with `--ignore-requires-python` while diagnosing the Kokoro/3.14
      problem. Harmless — the engine reports itself unavailable with the right
      message, which is itself worth knowing — but `pip uninstall misaki num2words`
      gives a clean environment. Kokoro lives in `.venv-build` (3.13).
- [ ] **Tune `MIN_CHAPTER_CHARS` and `_STUB_FRACTION` against more books.** (S)
      The stub-folding heuristic is calibrated on two.
- [ ] **PDF chapter detection is only verified on a 2-page sample.** (S) A real
      book-length PDF with genuine chapter headings has not been through it — on
      either backend, which now matters twice over (§2).

## 6. Decisions already made

Recorded so they don't get re-litigated. Change them deliberately, not by drift.

- **macOS only.** Windows parity is not required, which is why `mlx` is in and
  cross-platform `sherpa-onnx` was deprioritised.
- **The default install runs no models.** ~100 MB, no ML runtime, no weights, no
  local LLM — every voice is an API call, and `--engine edge` needs no credentials.
  Local synthesis, the cloud SDKs and PDF layout detection are each their own tier.
  This narrows the earlier "no bundle-size ceiling": there is no limit on what you
  *can* install, but the default is deliberately small, because reading EPUBs with
  cloud voices is the common case and it had been paying 180 MB for an ONNX runtime
  it never loaded.
- **M4B is the default output**, with chapters; MP3 stays available.
- **LLM normalization is optional and off by default.** Used mostly on
  well-edited books, so the rules pass is usually enough.
- **Deep Research is back** (reversing an earlier "gone for good" entry). What was
  deleted in `d15511f` deserved to go — it was a single `generate_content` call with
  "conduct a comprehensive deep research" in the prompt. The replacement calls the
  real thing: `client.interactions.create(agent="deep-research-…", background=True)`,
  polled to completion. Deep Research is an **agent**, not a model and not a
  `generate_content` tool — which is why a first pass at this concluded, wrongly,
  that no such API existed.
- **A `.md` file on disk is the interface to any researcher.** The key-free
  `/research` command writes the same two files as `echo/research.py` and needed no
  backend code at all. A second research *backend* would be the wrong shape.
- **Google Cloud TTS needs ADC, not an API key** — its REST API rejects API keys.
  The Gemini API path is the key-based one.
- **Gutenberg ranking does not privilege exact title matches** — canonical editions
  usually carry a subtitle, so exact-match ranking promotes obscure reprints.
- **One source button, not three.** File, Gutenberg and research each get a dialog
  behind a split button whose default action is Browse; the field beside it is a
  read-only *description* of the choice, not the choice itself. This is why
  `SourceSelection.name` exists — research has no filename to derive an output name
  from.
- **The conversion queue is serial, not parallel.** Within one book the
  synthesizer already keeps `engine.max_concurrency` requests in flight, so a
  second simultaneous book doubles the connection count against the same
  endpoint — identical to raising `DEFAULT_MAX_THREADS`, minus the coordination.
  edge-tts already throws transient 403s at the default concurrency; more
  in-flight requests buy retries, not throughput. The honest speed knob is
  `DEFAULT_MAX_THREADS`, and the only real overlap is assembly-vs-synthesis (§4).

## 7. Non-goals

From the review, still deliberate:

- **No PyTorch in the shipped bundle.** It's the difference between a ~200 MB app
  and a multi-gigabyte one.
- **No mandatory LLM** anywhere on the default path.
- **No voice cloning.** The flashiest capability on offer and the least useful for
  reading books to yourself.
- **No GUI rewrite.** It's the healthiest part of the codebase.
- **Don't drop edge-tts.** Still the best zero-setup default; it just shouldn't be
  the only engine.
