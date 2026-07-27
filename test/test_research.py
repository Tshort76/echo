"""Gemini Deep Research, against a fake interactions client.

No network and no API key: what is under test is our handling of the agent API —
the call shape, the polling loop, and every terminal status — not Google's service.
"""

import pytest

import echo.research as research
from echo.research import AGENTS, DeepResearcher, ResearchError, ResearchUnavailable

REPORT = """# The Marine Chronometer

## Background

Longitude was the problem [1], and the prize was substantial [2, 3].

## Findings

Harrison's work changed navigation. This section runs on for a while so that the
references heading below sits comfortably past the point where a trailing sources
block can be told apart from a passing mention in the body of the report itself.

## References

1. [A page](https://example.com/a)
2. [Another](https://example.com/b)
"""


class FakeStep:
    def __init__(self, kind):
        self.type = kind


class FakeInteraction:
    def __init__(self, id="int_1", status="queued", output_text=None, steps=(), error=None):
        self.id = id
        self.status = status
        self.output_text = output_text
        self.steps = list(steps)
        self.error = error


#: The request fields the real SDK accepts, from
#: ``google.genai._gaos.google_genai._CREATE_BODY_KEYS``. Mirrored here so the fake
#: rejects what the real client rejects — the first version of this fake took a
#: ``body=`` kwarg, which is *not* the real shape, so it happily validated a call
#: that failed against the live API. A fake that accepts more than the real thing
#: tests nothing.
CREATE_BODY_KEYS = frozenset(
    {
        "agent", "agent_config", "background", "environment", "generation_config",
        "input", "labels", "model", "previous_interaction_id", "response_format",
        "response_mime_type", "response_modalities", "safety_settings",
        "service_tier", "store", "stream", "system_instruction", "tools", "webhook_config",
    }
)


class FakeInteractions:
    """Replays a scripted sequence of statuses, recording what it was asked."""

    def __init__(self, statuses=("completed",), output_text=REPORT, steps_per_poll=0, error=None):
        self._statuses = list(statuses)
        self._output = output_text
        self._steps_per_poll = steps_per_poll
        self._error = error
        self.created_body = None
        self.get_calls = 0
        self.cancelled = []

    def create(self, *, request=None, api_version=None, extra_headers=None,
               extra_query=None, extra_body=None, timeout=None, **body):
        """Mirror the real signature: fields arrive as **kwargs, name-checked."""
        unknown = set(body) - CREATE_BODY_KEYS
        if unknown:
            raise TypeError(
                "create() got unexpected keyword argument(s): "
                + ", ".join(sorted(unknown))
                + ". Use extra_body=... to send additional request body fields."
            )
        self.created_body = body
        return FakeInteraction(id="int_1", status="queued")

    def get(self, interaction_id, **_kw):
        self.get_calls += 1
        status = self._statuses[min(self.get_calls - 1, len(self._statuses) - 1)]
        steps = [FakeStep("google_search_call")] * (self._steps_per_poll * self.get_calls)
        return FakeInteraction(
            id=interaction_id,
            status=status,
            output_text=self._output if status == "completed" else None,
            steps=steps,
            error=self._error,
        )

    def cancel(self, interaction_id, **_kw):
        self.cancelled.append(interaction_id)
        return FakeInteraction(id=interaction_id, status="cancelled")


class FakeClient:
    def __init__(self, interactions):
        self.interactions = interactions


def researcher(**kw) -> DeepResearcher:
    kw.setdefault("api_key", "pretend-key")
    kw.setdefault("poll_seconds", 0.0)  # don't actually sleep
    return DeepResearcher(**kw)


class TestAvailability:
    def test_no_key_names_the_variable(self):
        ok, reason = DeepResearcher(api_key="").is_available()
        assert ok is False
        assert "GEMINI_API_KEY" in reason

    def test_it_points_at_where_to_get_a_key(self):
        _ok, reason = DeepResearcher(api_key="").is_available()
        assert "aistudio.google.com" in reason

    def test_an_explicit_empty_key_does_not_fall_back_to_the_environment(self, monkeypatch):
        """`or` would make "" mean "use the env key", which hides a missing key
        whenever the developer happens to have one configured."""
        monkeypatch.setattr(research.ec, "GEMINI_API_KEY", "a-key-from-the-environment")
        assert DeepResearcher(api_key="").is_available()[0] is False

    def test_a_key_is_enough_to_be_available(self):
        assert DeepResearcher(api_key="pretend-key").is_available() == (True, "")

    def test_check_available_raises_the_typed_error(self):
        with pytest.raises(ResearchUnavailable):
            DeepResearcher(api_key="").check_available()


class TestAgentResolution:
    """Deep Research variants are agents, and their ids are dated previews."""

    @pytest.mark.parametrize("friendly", list(AGENTS))
    def test_friendly_names_map_to_real_ids(self, friendly):
        resolved = research.resolve_agent(friendly)
        assert resolved == AGENTS[friendly]
        assert resolved.startswith("deep-research")

    def test_every_id_is_date_suffixed(self):
        """The bare names 'deep-research-preview' etc. do not exist."""
        import re

        for agent_id in AGENTS.values():
            assert re.search(r"-\d{2}-\d{4}$", agent_id), agent_id

    def test_an_explicit_id_passes_through(self):
        assert research.resolve_agent("deep-research-future-01-2027") == "deep-research-future-01-2027"

    def test_an_unknown_name_is_rejected(self):
        with pytest.raises(ValueError, match="Unknown research agent"):
            research.resolve_agent("turbo")


class TestCallShape:
    def test_it_creates_an_agent_interaction_in_the_background(self, tmp_path):
        """`agent=`, not `model=` — the SDK separates agent and model interactions."""
        api = FakeInteractions()
        researcher().run("a topic", "a_name", client=FakeClient(api), keep_dir=tmp_path)

        assert api.created_body["agent"] == AGENTS["standard"]
        assert api.created_body["input"] == "a topic"
        assert api.created_body["background"] is True
        assert "model" not in api.created_body

    def test_the_fields_are_passed_as_keyword_arguments(self, tmp_path):
        """Regression: `create(body={...})` is rejected by the real SDK as a field
        named "body". The fake enforces the same whitelist, so this would fail."""
        api = FakeInteractions()
        researcher().run("t", "n", client=FakeClient(api), keep_dir=tmp_path)
        assert "body" not in api.created_body
        assert set(api.created_body) <= CREATE_BODY_KEYS

    def test_the_fake_rejects_the_wrong_shape(self, tmp_path):
        """Proves the fake would have caught the original mistake."""
        api = FakeInteractions()
        with pytest.raises(TypeError, match="unexpected keyword argument"):
            api.create(body={"agent": "x"})

    def test_the_agent_choice_reaches_the_call(self, tmp_path):
        api = FakeInteractions()
        researcher().run("t", "n", agent="max", client=FakeClient(api), keep_dir=tmp_path)
        assert api.created_body["agent"] == AGENTS["max"]

    def test_a_missing_interaction_id_is_an_error(self, tmp_path):
        class NoId(FakeInteractions):
            def create(self, body=None, **_kw):
                return FakeInteraction(id=None)

        with pytest.raises(ResearchError, match="interaction id"):
            researcher().run("t", "n", client=FakeClient(NoId()), keep_dir=tmp_path)


class TestPolling:
    def test_it_polls_until_completed(self, tmp_path):
        api = FakeInteractions(statuses=("queued", "in_progress", "in_progress", "completed"))
        result = researcher().run("t", "n", client=FakeClient(api), keep_dir=tmp_path)
        assert api.get_calls == 4
        assert "Harrison" in result.text

    def test_progress_reports_the_search_count(self, tmp_path):
        api = FakeInteractions(statuses=("in_progress", "in_progress", "completed"), steps_per_poll=3)
        lines = []
        researcher().run("t", "n", client=FakeClient(api), keep_dir=tmp_path, on_progress=lines.append)
        assert any("search" in line for line in lines)
        assert any("6 search" in line for line in lines)

    def test_result_records_the_searches_and_id(self, tmp_path):
        api = FakeInteractions(statuses=("in_progress", "completed"), steps_per_poll=2)
        result = researcher().run("t", "n", client=FakeClient(api), keep_dir=tmp_path)
        assert result.searches == 4
        assert result.interaction_id == "int_1"
        assert result.agent == AGENTS["standard"]

    def test_a_timeout_cancels_the_job(self, tmp_path):
        """A run left in flight would keep being billed."""
        api = FakeInteractions(statuses=("in_progress",))
        with pytest.raises(ResearchError, match="was cancelled"):
            researcher(timeout_seconds=-1).run("t", "n", client=FakeClient(api), keep_dir=tmp_path)
        assert api.cancelled == ["int_1"]


class TestTerminalStatuses:
    """Lowercase statuses, and each one deserves its own message."""

    def test_budget_exceeded_explains_the_quota(self, tmp_path):
        """A free-tier key *can* run these agents (verified live), so this status
        means the allowance ran out — not that the tier is wrong."""
        api = FakeInteractions(statuses=("budget_exceeded",))
        with pytest.raises(ResearchError, match="quota"):
            researcher().run("t", "n", client=FakeClient(api), keep_dir=tmp_path)

    def test_requires_action_is_refused_rather_than_polled_forever(self, tmp_path):
        api = FakeInteractions(statuses=("requires_action",))
        with pytest.raises(ResearchError, match="collaborative planning"):
            researcher().run("t", "n", client=FakeClient(api), keep_dir=tmp_path)

    @pytest.mark.parametrize(
        "status,fragment",
        [
            ("failed", "failed"),
            ("cancelled", "cancelled"),
            ("incomplete", "incomplete"),
            ("something_new", "unexpected status"),
        ],
    )
    def test_each_status_gets_its_own_message(self, tmp_path, status, fragment):
        api = FakeInteractions(statuses=(status,))
        with pytest.raises(ResearchError, match=fragment):
            researcher().run("t", "n", client=FakeClient(api), keep_dir=tmp_path)

    def test_an_error_detail_is_surfaced(self, tmp_path):
        api = FakeInteractions(statuses=("failed",), error="quota drained")
        with pytest.raises(ResearchError, match="quota drained"):
            researcher().run("t", "n", client=FakeClient(api), keep_dir=tmp_path)

    def test_an_empty_report_is_an_error(self, tmp_path):
        api = FakeInteractions(output_text="   ")
        with pytest.raises(ResearchError, match="empty report"):
            researcher().run("t", "n", client=FakeClient(api), keep_dir=tmp_path)


class TestNarrationSource:
    def test_a_trailing_sources_section_is_dropped(self):
        out = research.to_narration_source(REPORT)
        assert "References" not in out
        assert "example.com" not in out

    def test_bracketed_citation_markers_go(self):
        out = research.to_narration_source(REPORT)
        assert "[1]" not in out and "[2, 3]" not in out
        assert "Longitude was the problem" in out

    def test_headings_and_prose_survive(self):
        out = research.to_narration_source(REPORT)
        assert "## Background" in out
        assert "Harrison's work changed navigation." in out

    def test_an_early_mention_does_not_truncate_the_report(self):
        """A 'further reading' aside near the top must not eat the whole document."""
        text = "# T\n\n## Further reading advice\n\n" + ("Real body prose. " * 200)
        out = research.to_narration_source(text)
        assert "Real body prose." in out
        assert len(out) > 1000

    def test_empty_input_is_safe(self):
        assert research.to_narration_source("") == ""
        assert research.to_narration_source(None) == ""


class TestArtefacts:
    def test_keep_dir_writes_the_narration_source_and_the_notes(self, tmp_path):
        api = FakeInteractions()
        result = researcher().run("a topic", "chrono", client=FakeClient(api), keep_dir=tmp_path)

        assert result.path == tmp_path / "chrono.md"
        assert result.notes_path == tmp_path / "chrono.notes.md"
        narration = result.path.read_text()
        notes = result.notes_path.read_text()
        # Citations live in the notes, never in what gets read aloud.
        assert "example.com" not in narration
        assert "example.com" in notes
        assert "a topic" in notes
        assert AGENTS["standard"] in notes

    def test_without_keep_dir_only_a_temp_narration_source_is_written(self, tmp_path):
        api = FakeInteractions()
        result = researcher().run("t", "n", client=FakeClient(api))
        assert result.notes_path is None
        assert result.path.exists()
        assert result.path.name == "n.md"
        assert tmp_path not in result.path.parents

    def test_the_filename_is_the_name_so_downstream_naming_works(self, tmp_path):
        api = FakeInteractions()
        result = researcher().run("t", "my_report", client=FakeClient(api), keep_dir=tmp_path)
        assert result.path.stem == "my_report"

    def test_metadata_is_ready_for_the_pipeline(self, tmp_path):
        api = FakeInteractions()
        meta = researcher().run("t", "marine_chronometer", client=FakeClient(api), keep_dir=tmp_path).as_meta()
        assert meta["title"] == "marine chronometer"
        assert meta["author"] == "Gemini Deep Research"

    def test_the_report_is_narratable_by_the_pipeline(self, tmp_path):
        """End to end through the real extractor: chapters, and no link furniture."""
        import echo.core as core

        api = FakeInteractions()
        result = researcher().run("t", "chrono", client=FakeClient(api), keep_dir=tmp_path)
        doc = core.extract_document(result.path)
        script = core.build_script(doc)
        text = script.as_text()
        assert "Background" in [c.title for c in script.chapters] or "Background" in text
        assert "https://" not in text
        assert "Harrison" in text


class TestInputValidation:
    def test_a_blank_topic_is_refused(self, tmp_path):
        with pytest.raises(ValueError, match="topic"):
            researcher().run("  ", "n", client=FakeClient(FakeInteractions()), keep_dir=tmp_path)

    def test_a_blank_name_is_refused(self, tmp_path):
        """There is no filename to infer a name from."""
        with pytest.raises(ValueError, match="name"):
            researcher().run("t", "", client=FakeClient(FakeInteractions()), keep_dir=tmp_path)
