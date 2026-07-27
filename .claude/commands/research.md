---
description: Research a topic and write a narration-ready report for echo to convert
argument-hint: <topic to research>
allowed-tools: WebSearch, WebFetch, Write, Bash(mkdir:*), Bash(ls:*)
---

Research this topic and write it up as an audiobook script: **$ARGUMENTS**

This is the no-API-key path into echo's pipeline. echo narrates any `.md` file, so a
report written to `resources/research/` is a first-class source — nothing in the
backend needs to know it came from here rather than from Gemini Deep Research.

## Do the research

Search the web properly before writing. Aim for **6–10 distinct searches** covering
different angles of the topic, not rephrasings of one query — background, key
figures or mechanisms, chronology, disputes and counterarguments, consequences,
current state. Fetch the substantive pages rather than working from search snippets.

Keep a note of every source you actually used, with its title and URL.

## Pick a name

Derive a short `snake_case` name from the topic — a few meaningful words, stopwords
dropped. "the history of the marine chronometer" becomes `marine_chronometer`. This
name becomes the audio filename and the title, so keep it clean and filesystem-safe.

## Write two files

Create the directory if needed (`mkdir -p resources/research`). It is gitignored, so
nothing here will be committed.

### `resources/research/<name>.md` — what gets read aloud

This is spoken by a text-to-speech engine, so it must contain **only words a narrator
would say**. echo splits chapters on `##` headings and drops tables, code and
figures, so:

- **Do** use `# Title` once, then `## Section` headings — each becomes a chapter mark
  in the audiobook, so give them real names ("The longitude problem"), not labels
  ("Section 2").
- **Do** write flowing prose in full sentences. This is the one hard rule: it will be
  *heard*, not skimmed.
- **Do** spell out anything that reads badly aloud — "Dr." as "Doctor", "1714" as
  "seventeen fourteen", "£20,000" as "twenty thousand pounds", "e.g." as "for
  example". Expand abbreviations and units on first use.
- **Don't** include URLs, bare links, bullet lists, tables, footnote or bracketed
  citation markers (`[1]`), parenthetical source attributions, or a references
  section. All of that either gets read out as noise or silently dropped.
- **Don't** address the reader about the document ("as outlined below", "see the
  table") — there is no below and no table.

Length: aim for 1,500–4,000 words unless the topic clearly wants more. At typical
narration speed that is roughly 10–30 minutes of audio.

### `resources/research/<name>.notes.md` — the citations

Everything the narration file cannot carry: the topic as given, the searches you ran,
and a numbered list of sources with titles and URLs. This file is never narrated, so
normal markdown is fine here.

## Then tell me how to listen to it

Report the two paths, the approximate word count, and the ready-to-run command:

```
python create_audio.py resources/research/<name>.md
```

Mention that `-e google-cloud` uses the free-tier cloud voices and `-e edge` needs no
credentials at all, and that the chapter marks come from the `##` headings you chose.
