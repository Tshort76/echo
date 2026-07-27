"""Gemini Deep Research as a source of text to narrate.

Deep Research is a real agent, not a prompt. It plans, runs many Google searches,
reads pages and writes a cited report, which takes minutes rather than seconds — so
it is not reachable through ``generate_content``. It is invoked through the
**Interactions API**::

    client.interactions.create(body={"agent": ..., "input": ..., "background": True})
    client.interactions.get(interaction_id)     # poll until terminal

Two details are easy to get wrong, and both fail at runtime:

* Deep Research variants are **agents**, not models. The SDK has separate
  ``CreateAgentInteraction`` (``agent=``) and ``CreateModelInteraction`` (``model=``)
  shapes; passing ``model="deep-research-…"`` does not work.
* Statuses are **lowercase** (``completed``, not ``COMPLETED``), the field is
  ``status``, and the result is ``output_text`` — there is no ``outputs`` list.

The report comes back as cited markdown, which is *not* narration-ready.
:func:`to_narration_source` trims the citation furniture; the full cited report is
kept in the notes file instead of being read aloud.
"""

from __future__ import annotations

import logging
import re
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import echo.constants as ec

log = logging.getLogger(__name__)

#: Deep Research agent ids. All are dated previews and will age out; this dict and
#: the RESEARCH_AGENT_ID env override are the only places to change when they do.
AGENTS: dict[str, str] = {
    "standard": "deep-research-preview-04-2026",
    "max": "deep-research-max-preview-04-2026",
    "pro": "deep-research-pro-preview-12-2025",
}
DEFAULT_AGENT = "standard"

#: Statuses that mean "still working".
_PENDING = {"queued", "in_progress"}
#: Everything else is terminal, with per-status handling in :meth:`DeepResearcher.run`.
_SUCCESS = "completed"

_SOURCES_HEADING = re.compile(
    r"^#{1,6}\s*(references|sources|citations|works cited|bibliography|further reading)\b.*$",
    re.IGNORECASE | re.MULTILINE,
)
#: Bracketed numeric citation markers — "as Harrison showed [12]." The markdown
#: parser strips [^1] footnote refs but not these.
_BRACKET_CITATION = re.compile(r"\s*\[\d{1,3}(?:\s*,\s*\d{1,3})*\]")


class ResearchError(RuntimeError):
    """A research run could not be completed."""


class ResearchUnavailable(ResearchError):
    """Credentials or the SDK are missing. Carries an actionable message."""


@dataclass(slots=True)
class ResearchResult:
    """A finished report, on disk and ready for the pipeline."""

    name: str
    topic: str
    agent: str
    text: str
    #: Narration source: what the pipeline reads.
    path: Path
    #: Full cited report plus metadata; never narrated. None when not kept.
    notes_path: Path | None = None
    searches: int = 0
    elapsed_s: float = 0.0
    interaction_id: str | None = None

    def as_meta(self) -> dict:
        """Metadata for :func:`echo.core.file_to_audio`."""
        return {"title": self.name.replace("_", " ").strip() or self.topic[:60],
                "author": "Gemini Deep Research"}


def resolve_agent(agent: str = None) -> str:
    """Map a friendly name (``standard``/``max``/``pro``) to an agent id.

    An id passed straight through is respected, so a newer preview can be used
    without a code change.
    """
    choice = (agent or ec.RESEARCH_AGENT or DEFAULT_AGENT).strip()
    if ec.RESEARCH_AGENT_ID and choice == DEFAULT_AGENT:
        return ec.RESEARCH_AGENT_ID
    if choice in AGENTS:
        return AGENTS[choice]
    if choice.startswith("deep-research"):
        return choice  # an explicit id
    raise ValueError(f"Unknown research agent '{agent}'. Choose from: {', '.join(AGENTS)}")


def to_narration_source(report: str) -> str:
    """Strip citation furniture from a Deep Research report.

    Removes a trailing references/sources section and bracketed citation markers.
    Everything else — headings, prose — is left for
    :mod:`echo.extractors.markdown`, which already drops tables, code and figures.
    """
    text = report or ""
    if not text.strip():
        return ""
    # Cut at the *last* sources-style heading, so a body mention of "further
    # reading" earlier on does not truncate the report.
    matches = list(_SOURCES_HEADING.finditer(text))
    if matches:
        cut = matches[-1].start()
        # Only trust it if it really is trailing material, not a mid-report aside.
        if cut > len(text) * 0.4:
            text = text[:cut]
    text = _BRACKET_CITATION.sub("", text)
    return text.strip() + "\n"


def _count_searches(interaction) -> int:
    """How many web searches the agent has run so far.

    Defensive about the SDK's step union: a shape change should cost us a progress
    number, not the run.
    """
    steps = getattr(interaction, "steps", None) or []
    total = 0
    for step in steps:
        kind = str(getattr(step, "type", "") or "")
        if "search" in kind and "result" not in kind:
            total += 1
    return total


@dataclass(slots=True)
class DeepResearcher:
    """Runs Deep Research and lands the report on disk."""

    api_key: str | None = None
    poll_seconds: float | None = None
    timeout_seconds: float | None = None
    _client: object | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        # `None` rather than `or`: a caller passing 0 means "don't wait", and
        # `0 or default` would silently substitute the default instead.
        self.api_key = self.api_key if self.api_key is not None else ec.GEMINI_API_KEY
        if self.poll_seconds is None:
            self.poll_seconds = ec.RESEARCH_POLL_SECONDS
        if self.timeout_seconds is None:
            self.timeout_seconds = ec.RESEARCH_TIMEOUT_SECONDS

    # ── availability ────────────────────────────────────────────────────────
    def check_available(self) -> None:
        """Raise :class:`ResearchUnavailable` with a fix-it message, or return."""
        if not self.api_key:
            raise ResearchUnavailable(
                "Deep Research needs a Gemini API key. Set GEMINI_API_KEY in your "
                ".env (create one at https://aistudio.google.com/apikey). Note that "
                "the Deep Research agents require a paid-tier key."
            )
        try:
            import google.genai  # noqa: F401, PLC0415
        except ImportError as ex:
            raise ResearchUnavailable("Deep Research needs `pip install google-genai`") from ex

    def is_available(self) -> tuple[bool, str]:
        """Convenience for UIs: ``(ok, reason)`` instead of an exception."""
        try:
            self.check_available()
            return True, ""
        except Exception as ex:
            return False, str(ex)

    def _client_or_load(self):
        if self._client is None:
            self.check_available()
            from google import genai  # noqa: PLC0415

            self._client = genai.Client(api_key=self.api_key)
        return self._client

    # ── the run ─────────────────────────────────────────────────────────────
    def run(
        self,
        topic: str,
        name: str,
        agent: str = None,
        keep_dir: str | Path = None,
        on_progress: Callable[[str], None] = None,
        client=None,
    ) -> ResearchResult:
        """Research ``topic`` and write the report as ``<name>.md``.

        Args:
            topic: the question to research.
            name: used for the filename, and downstream for the output name and
                metadata title. Deep Research has no filename to infer one from.
            agent: ``standard`` (default), ``max``, ``pro``, or an explicit agent id.
            keep_dir: keep the artefacts here instead of a temp directory. The
                caller passes this when "save intermediate files" is on.
            on_progress: called with human-readable progress lines.
            client: inject a client (used by the tests).
        """
        if not (topic or "").strip():
            raise ValueError("Please provide a topic to research.")
        if not (name or "").strip():
            raise ValueError("Please provide a name — it is used to name the audio file.")

        agent_id = resolve_agent(agent)
        report = lambda message: (on_progress(message) if on_progress else log.info(message))  # noqa: E731

        api = client if client is not None else self._client_or_load()
        report(f"Starting Deep Research with {agent_id}. This usually takes 2–15 minutes.")

        interaction = api.interactions.create(
            body={"agent": agent_id, "input": topic, "background": True}
        )
        interaction_id = getattr(interaction, "id", None)
        if not interaction_id:
            raise ResearchError("Deep Research did not return an interaction id")
        log.info(f"Interaction {interaction_id} created")

        started = time.perf_counter()
        text, searches = self._poll(api, interaction_id, report, started)
        elapsed = time.perf_counter() - started
        report(f"Research finished in {elapsed / 60:.1f} minutes after {searches} search(es).")

        narration = to_narration_source(text)
        if not narration.strip():
            raise ResearchError("Deep Research returned an empty report")

        path, notes_path = self._write(
            name=name, topic=topic, agent_id=agent_id, report_md=text,
            narration=narration, searches=searches, keep_dir=keep_dir,
        )

        return ResearchResult(
            name=name, topic=topic, agent=agent_id, text=narration, path=path,
            notes_path=notes_path, searches=searches, elapsed_s=elapsed,
            interaction_id=interaction_id,
        )

    def _poll(self, api, interaction_id: str, report, started: float) -> tuple[str, int]:
        """Poll until terminal, translating each status into a clear outcome."""
        last_reported = -1
        while True:
            if (waited := time.perf_counter() - started) > self.timeout_seconds:
                # Cancel rather than abandon a job that is being billed.
                try:
                    api.interactions.cancel(interaction_id)
                    log.warning(f"Cancelled interaction {interaction_id} after timeout")
                except Exception as ex:  # pragma: no cover - best effort
                    log.warning(f"Could not cancel interaction {interaction_id}: {ex}")
                raise ResearchError(
                    f"Deep Research did not finish within {self.timeout_seconds / 60:.0f} minutes "
                    f"and was cancelled. Try a narrower topic, or raise "
                    f"RESEARCH_TIMEOUT_SECONDS."
                )

            current = api.interactions.get(interaction_id)
            status = str(getattr(current, "status", "") or "").lower()
            searches = _count_searches(current)

            if status in _PENDING:
                if searches != last_reported:
                    report(f"Researching… {searches} search(es) so far, {waited / 60:.1f} min elapsed.")
                    last_reported = searches
                time.sleep(self.poll_seconds)
                continue

            if status == _SUCCESS:
                return (getattr(current, "output_text", None) or ""), searches

            raise self._failure(status, current, interaction_id)

    @staticmethod
    def _failure(status: str, interaction, interaction_id: str) -> ResearchError:
        """Turn a terminal non-success status into an actionable error."""
        detail = getattr(interaction, "error", None) or ""
        match status:
            case "budget_exceeded":
                return ResearchError(
                    "Deep Research stopped: the account's budget was exceeded. The "
                    "Deep Research agents require a paid-tier Gemini API key; a "
                    "free-tier key cannot run them."
                )
            case "requires_action":
                return ResearchError(
                    "Deep Research is waiting for input on its proposed plan "
                    "(collaborative planning). echo does not drive that conversation "
                    "yet — it requests plan-free runs, so this should not happen; "
                    f"interaction {interaction_id} is left open for inspection."
                )
            case "cancelled":
                return ResearchError(f"Deep Research interaction {interaction_id} was cancelled.")
            case "incomplete":
                return ResearchError(
                    f"Deep Research finished incomplete{f': {detail}' if detail else ''}. "
                    "This usually means the agent hit an internal limit; try a narrower topic."
                )
            case "failed":
                return ResearchError(f"Deep Research failed{f': {detail}' if detail else ''}.")
            case other:
                return ResearchError(f"Deep Research returned an unexpected status '{other}'.")

    @staticmethod
    def _write(
        name: str, topic: str, agent_id: str, report_md: str, narration: str,
        searches: int, keep_dir: str | Path | None,
    ) -> tuple[Path, Path | None]:
        """Write the narration source, plus notes when we're keeping artefacts."""
        if keep_dir:
            directory = Path(keep_dir).expanduser()
            directory.mkdir(parents=True, exist_ok=True)
            keeping = True
        else:
            directory = Path(tempfile.mkdtemp(prefix="echo-research-"))
            keeping = False

        path = directory / f"{name}.md"
        path.write_text(narration, encoding="utf-8")
        log.info(f"Wrote the narration source to {path}")

        notes_path = None
        if keeping:
            notes_path = directory / f"{name}.notes.md"
            notes_path.write_text(
                "\n".join(
                    [
                        f"# Research notes: {name}",
                        "",
                        f"- **Topic:** {topic}",
                        f"- **Agent:** {agent_id}",
                        f"- **Web searches:** {searches}",
                        "",
                        "The full report below keeps its citations. The narrated version "
                        f"(`{path.name}`) has them stripped.",
                        "",
                        "---",
                        "",
                        report_md.strip(),
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            log.info(f"Wrote the cited report to {notes_path}")
        return path, notes_path


def research(
    topic: str,
    name: str,
    agent: str = None,
    keep: bool = False,
    on_progress: Callable[[str], None] = None,
) -> ResearchResult:
    """Convenience wrapper: research ``topic`` and return the result.

    ``keep=True`` persists the artefacts under :data:`echo.constants.RESEARCH_DIR`
    (gitignored) instead of a temp directory.
    """
    researcher = DeepResearcher()
    return researcher.run(
        topic,
        name,
        agent=agent,
        keep_dir=ec.RESEARCH_DIR if keep else None,
        on_progress=on_progress,
    )
