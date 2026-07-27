"""Synthesis orchestration: retry, resume, and refusing partial output.

Uses a fake engine so the behaviour under test is the orchestrator's, not a
network service's.
"""

import asyncio

import pytest

import echo.audio.tts as tts
from echo.audio.engines.base import BaseEngine, SynthOutput
from echo.audio.wav import write_pcm16_wav
from echo.document import Chapter, Script, Timing, Utterance


class FakeEngine(BaseEngine):
    """Writes a valid one-second WAV, and can be told to fail the first N tries."""

    name = "fake"
    label = "Fake"
    audio_suffix = ".wav"
    max_concurrency = 4
    max_chars = 1000
    supports_speed = True

    def __init__(self, fail_times: int = 0, fail_always_at: set[int] = None, with_timings: bool = False):
        self.calls = 0
        self.per_index_calls: dict[int, int] = {}
        self._fail_times = fail_times
        self._fail_always_at = fail_always_at or set()
        self._with_timings = with_timings

    def voices(self):
        return []

    def default_voice(self) -> str:
        return "fake-voice"

    async def synthesize(self, text, voice, speed, out_path):
        self.calls += 1
        index = int(out_path.stem.split("_")[-1])
        self.per_index_calls[index] = self.per_index_calls.get(index, 0) + 1

        if index in self._fail_always_at:
            raise RuntimeError(f"index {index} always fails")
        if self.per_index_calls[index] <= self._fail_times:
            raise RuntimeError("transient websocket 403")

        write_pcm16_wav(b"\x00\x00" * 24_000, out_path, rate=24_000)
        timings = [Timing(0, 900, text[:20])] if self._with_timings else []
        return SynthOutput(path=out_path, timings=timings)


def script_of(n: int) -> Script:
    return Script(
        title="Fake Book",
        chapters=[Chapter(title=f"Chapter {i + 1}", utterances=[Utterance(f"Passage {i}.")]) for i in range(n)],
    )


def run(script, engine, chunks_dir, resume=True):
    return asyncio.run(
        tts.synthesize_script(script, engine=engine, voice="v", speed=1.0, chunks_dir=chunks_dir, resume=resume)
    )


class TestHappyPath:
    def test_every_utterance_becomes_a_segment_in_order(self, tmp_path):
        engine = FakeEngine()
        segments = run(script_of(5), engine, tmp_path / "chunks")
        assert [s.index for s in segments] == [0, 1, 2, 3, 4]
        assert all(s.duration_ms == pytest.approx(1000, abs=5) for s in segments)
        assert engine.calls == 5

    def test_timings_are_carried_through(self, tmp_path):
        segments = run(script_of(2), FakeEngine(with_timings=True), tmp_path / "chunks")
        assert all(s.timings for s in segments)

    def test_chunk_files_are_named_by_index(self, tmp_path):
        chunks = tmp_path / "chunks"
        run(script_of(3), FakeEngine(), chunks)
        assert sorted(p.name for p in chunks.glob("*.wav")) == [
            "chunk_00000.wav",
            "chunk_00001.wav",
            "chunk_00002.wav",
        ]


class TestRetry:
    def test_a_transient_failure_is_retried(self, tmp_path):
        engine = FakeEngine(fail_times=1)
        segments = run(script_of(3), engine, tmp_path / "chunks")
        assert len(segments) == 3
        assert engine.calls == 6  # one failure + one success each

    def test_persistent_failure_names_the_chunk_and_keeps_the_others(self, tmp_path):
        chunks = tmp_path / "chunks"
        with pytest.raises(tts.SynthesisError) as excinfo:
            run(script_of(4), FakeEngine(fail_always_at={2}), chunks)
        message = str(excinfo.value)
        assert "chunk 2" in message
        assert "resumes" in message
        # The chunks that did succeed are still on disk for the re-run.
        assert len(list(chunks.glob("*.wav"))) == 3


class TestResume:
    def test_existing_chunks_are_reused(self, tmp_path):
        chunks = tmp_path / "chunks"
        script = script_of(4)
        run(script, FakeEngine(), chunks)

        second = FakeEngine()
        segments = run(script, second, chunks)
        assert len(segments) == 4
        assert second.calls == 0, "nothing should have been re-synthesized"

    def test_only_the_missing_chunk_is_redone(self, tmp_path):
        chunks = tmp_path / "chunks"
        script = script_of(4)
        run(script, FakeEngine(), chunks)
        (chunks / "chunk_00002.wav").unlink()

        second = FakeEngine()
        assert len(run(script, second, chunks)) == 4
        assert second.calls == 1
        assert set(second.per_index_calls) == {2}

    def test_a_truncated_chunk_is_not_trusted(self, tmp_path):
        chunks = tmp_path / "chunks"
        script = script_of(2)
        run(script, FakeEngine(), chunks)
        (chunks / "chunk_00001.wav").write_bytes(b"")  # zero-length leftover

        second = FakeEngine()
        run(script, second, chunks)
        assert set(second.per_index_calls) == {1}

    def test_resume_can_be_switched_off(self, tmp_path):
        chunks = tmp_path / "chunks"
        script = script_of(3)
        run(script, FakeEngine(), chunks)
        second = FakeEngine()
        run(script, second, chunks, resume=False)
        assert second.calls == 3


class TestConcurrency:
    def test_engine_concurrency_is_respected(self, tmp_path):
        """A serial engine must never see two overlapping calls."""

        class SerialEngine(FakeEngine):
            max_concurrency = 1

            def __init__(self):
                super().__init__()
                self.in_flight = 0
                self.max_seen = 0

            async def synthesize(self, text, voice, speed, out_path):
                self.in_flight += 1
                self.max_seen = max(self.max_seen, self.in_flight)
                await asyncio.sleep(0)
                try:
                    return await super().synthesize(text, voice, speed, out_path)
                finally:
                    self.in_flight -= 1

        engine = SerialEngine()
        run(script_of(6), engine, tmp_path / "chunks")
        assert engine.max_seen == 1


class TestProgress:
    def test_progress_is_reported_in_the_format_the_gui_parses(self, tmp_path, caplog):
        import logging

        with caplog.at_level(logging.INFO, logger="echo.audio.tts"):
            run(script_of(4), FakeEngine(), tmp_path / "chunks")
        percentages = [m for m in caplog.messages if "Progress Report:" in m]
        assert percentages, "no progress lines emitted"
        assert percentages[-1].endswith("100%")

    def test_a_fully_resumed_run_still_reports_completion(self, tmp_path, caplog):
        import logging

        chunks = tmp_path / "chunks"
        script = script_of(2)
        run(script, FakeEngine(), chunks)
        with caplog.at_level(logging.INFO, logger="echo.audio.tts"):
            run(script, FakeEngine(), chunks)
        assert any(m.endswith("100%") for m in caplog.messages)
