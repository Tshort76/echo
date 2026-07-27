# echo — backlog

Working list for this project. Drawn from the [July 2026 architecture
review](https://claude.ai/code/artifact/eb774d6e-2e37-4e7e-8d6a-f16a894d467d)
plus verification gaps found while implementing it.

Effort tags are rough: **S** = a sitting, **M** = a day or so, **L** = a project.
Tick items off in place; move anything substantial into a commit message so the
reasoning outlives the checkbox.

---

## Where we stand — 26 July 2026

Phases P0–P3 of the review are done, plus two things that were later phases:

| | Shipped in |
| --- | --- |
| P0 correctness pass (9 findings, retry, resume, pinned deps, `pyproject.toml`) | `d15511f` |
| P1 pydub retired — ffmpeg concat, M4B chapters, SRT | `d15511f` |
| P2 `SpeechEngine` seam — `edge`, `gemini`, `google-cloud`, `mlx` | `d15511f` |
| P3 `Document`/`Script` model, structured extraction, PyMuPDF OCR | `d15511f` |
| Deep Research removed; optional guarded LLM normalization added | `d15511f` |
| Project Gutenberg search + download | `5976efa` |
| README/code audit | `4df3599` |
| `BACKLOG.md`; GUI tests checked in | `e007719` |
| Full CLI/UI parity; normalizer availability checks | this commit |

254 tests pass. `edge` is verified end-to-end on markdown, PDF, EPUB and two real
Gutenberg books. The gaps below are mostly *unverified* work rather than unwritten
work — see §1.

---

## 1. Verification gaps

The highest-value items on this list. Three of the four engines are code-complete
but have never spoken to their actual service, and the packaged build has not been
run since the refactor.

- [ ] **Convert a full-length book you actually want to listen to.** (S)
      Nothing else substitutes. It's where the real questions surface: do chapter
      marks land where you expect, is 1.25× right, does the M4B behave in your player.
- [x] ~~**Check the offscreen GUI smoke test into `test/`.**~~ Done — `test/test_gui.py`,
      23 tests. It had been living in a throwaway temp directory. Covers the engine
      dropdown against the backend registry, per-engine voice lists, format/suffix
      syncing, every `gather()` validation path, and the Gutenberg dialog. Notably it
      asserts that `gather()`'s keys stay assignable to `core.file_to_audio`'s
      signature, which is how the GUI and backend drift apart silently.
- [ ] **Exercise `--engine gemini` against the real API.** (S)
      Written, unit-tested, never made a call. Needs `GEMINI_API_KEY`.
- [x] ~~**Exercise `--engine google-cloud` end-to-end.**~~ Works — the free-tier path
      is real, via the ADC credentials already on this machine.
- [x] ~~**Run `--engine mlx` through echo's own wrapper.**~~ Works with
      `MLX_TTS_MODEL=mlx-community/chatterbox-turbo-4bit` on Python 3.14.
- [x] ~~**Rebuild the packaged app.**~~ Built on Python 3.13 (`.venv-build`) →
      `dist/Echo.app`, 357 MB. Launches cleanly, finds its bundled ffmpeg and
      `voices.csv`. The spec's engine probing works: `google.genai` (311 modules) and
      `google.cloud.texttospeech` (26) are compiled into the PYZ archive, `mlx_audio`
      correctly excluded since it wasn't in the build venv.
      **Note:** they live *inside* the archive, not as directories on disk — check
      the PYZ, not the filesystem, when verifying a future build.
- [ ] **Exercise the OCR path.** (S) Needs `brew install tesseract`.
      `pdfs.ocr_page()` has only ever been seen failing with its "not installed"
      message. `resources/demo_data/ocr_3_pages.pdf` is the fixture.
- [ ] **Exercise the Docling escalation.** (S) Needs `pip install docling`.
      `_try_docling()` has only been seen degrading gracefully, never succeeding.
- [x] ~~**Run `bulk_generate.py` once.**~~ Works, including `--rename`.
- [x] ~~**Verify `pip install -e .` and the `echo-audio` console script.**~~ This found
      a real bug: `pyproject.toml` listed only *packages*, so the top-level
      `create_audio` module was never installed and `echo-audio` died with
      `ModuleNotFoundError`. Fixed with `py-modules`; verified from an unrelated cwd.
- [ ] **Build a second app bundle with `mlx-audio` included.** (M) The current
      bundle has the three cloud engines only. On Python 3.13 `misaki[en]` installs
      (spaCy has 3.13 wheels), so a build venv with `requirements-local.txt` +
      `misaki[en]` should give a packaged app that runs **Kokoro** locally. Untested,
      and the riskiest bundling job so far — mlx and transformers bring hidden
      imports and data files.

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

## 2. Engines

- [ ] **sherpa-onnx + Kokoro-82M offline engine.** (M) Deferred by decision, still
      wanted. Beyond being offline and unmetered, it is the path to **Kokoro on
      Python 3.14**: sherpa-onnx does its own ONNX grapheme-to-phoneme, so it needs
      neither `misaki` nor spaCy. Apache-2.0, no PyTorch.
- [ ] **Or: Kokoro via mlx in a Python 3.13 environment.** (S) The cheaper route to
      the same voices — just an interpreter change plus `pip install 'misaki[en]'`.

## 3. Features

From the review's phase 5, plus one thing the review asked for that shipped without it.

- [ ] **Diff preview before LLM normalization is applied.** (M)
      The review said ship the preview *before* the feature; the feature shipped
      first. The guardrails are real (length drift, preamble, refusal, exceptions)
      but there is currently no way to *see* what a model changed in your book.
- [ ] **Per-chapter or per-speaker voices.** (M) `Utterance.voice` already exists and
      the orchestrator already honours it — nothing sets it yet. Cheapest real
      feature on this list.
- [ ] **Pronunciation lexicon per book,** carried across runs. (M) Proper nouns and
      jargon are where narration most often goes wrong.
- [ ] **GUI library view** over past conversions. (M)
- [ ] **Two-narrator / dialogue output** via VibeVoice or similar. (L)

## 4. Cleanups and smaller fixes

- [ ] **Turn the README's examples into doctests.** (S) Two of them silently rotted
      *within a single session* — a README example is a test that nothing runs.
- [ ] **Decide the default speed.** (S) `DEFAULT_SPEED=1.25` is baked into the audio
      by the engine. 1.0 leaves the file re-usable at any playback speed, which
      matters if you keep a library. Left unchanged to avoid surprising you.
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
- [ ] **A broken `misaki` sits in `.venv`.** (S) Installed with
      `--ignore-requires-python` while diagnosing the Kokoro/3.14 problem. It
      imports but fails on spaCy. `pip uninstall misaki num2words` for a clean env.
- [ ] **Tune `MIN_CHAPTER_CHARS` and `_STUB_FRACTION` against more books.** (S)
      The stub-folding heuristic is calibrated on two.
- [ ] **PDF chapter detection is only verified on a 2-page sample.** (S) A real
      book-length PDF with genuine chapter headings has not been through it.

## 5. Decisions already made

Recorded so they don't get re-litigated. Change them deliberately, not by drift.

- **macOS only.** Windows parity is not required, which is why `mlx` is in and
  cross-platform `sherpa-onnx` was deprioritised.
- **No bundle-size ceiling.**
- **M4B is the default output**, with chapters; MP3 stays available.
- **LLM normalization is optional and off by default.** Used mostly on
  well-edited books, so the rules pass is usually enough.
- **Deep Research is gone for good.** Google is kept for TTS only.
- **Google Cloud TTS needs ADC, not an API key** — its REST API rejects API keys.
  The Gemini API path is the key-based one.
- **Gutenberg ranking does not privilege exact title matches** — canonical editions
  usually carry a subtitle, so exact-match ranking promotes obscure reprints.

## 6. Non-goals

From the review, still deliberate:

- **No PyTorch in the shipped bundle.** It's the difference between a ~200 MB app
  and a multi-gigabyte one.
- **No mandatory LLM** anywhere on the default path.
- **No voice cloning.** The flashiest capability on offer and the least useful for
  reading books to yourself.
- **No GUI rewrite.** It's the healthiest part of the codebase.
- **Don't drop edge-tts.** Still the best zero-setup default; it just shouldn't be
  the only engine.
