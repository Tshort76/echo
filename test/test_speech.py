"""The library entry point: chapters of text in, one chaptered file out."""

import subprocess
import sys

import pytest
from mutagen.id3 import ID3
from mutagen.mp4 import MP4

import echo
from echo import Chapter, SynthesisError, speak_chapters, split_text
from echo.audio.mp3_utils import configure_ffmpeg
from test.test_synthesis import FakeEngine

pytestmark = pytest.mark.skipif(configure_ffmpeg() is None, reason="ffmpeg not available")

CHAPTERS = [Chapter("Opening", "First words."), Chapter("Europe", "Second words."), Chapter("Close", "Last.")]


class SlowEngine(FakeEngine):
    """Cannot vary its rate, so the assembler applies speed with atempo."""

    supports_speed = False


class TestSpeakChapters:
    def test_mp3_carries_id3_chapters_matching_the_returned_marks(self, tmp_path):
        result = speak_chapters(CHAPTERS, tmp_path / "out.mp3", engine=FakeEngine(), title="Digest")

        assert result.path == tmp_path / "out.mp3"
        assert [m.title for m in result.chapters] == ["Opening", "Europe", "Close"]
        title, start, end = result.chapters[1]  # unpacks as a tuple
        assert (title, start, end) == ("Europe", 1000, 2000)
        assert result.duration_ms == 3000

        tags = ID3(result.path)
        toc = tags.getall("CTOC")[0]
        chaps = sorted(tags.getall("CHAP"), key=lambda c: c.start_time)
        assert toc.child_element_ids == [c.element_id for c in chaps]
        assert [(c.sub_frames["TIT2"].text[0], c.start_time, c.end_time) for c in chaps] == [
            tuple(m) for m in result.chapters
        ]
        assert tags["TIT2"].text == ["Digest"]

    def test_chap_frames_are_stored_in_time_order_whatever_the_title_lengths(self, tmp_path):
        # Readers that ignore the CTOC list chapters in file order.
        chapters = [Chapter("A much longer opening title", "One."), Chapter("B", "Two."), Chapter("Mid", "Three.")]
        result = speak_chapters(chapters, tmp_path / "out.mp3", engine=FakeEngine(), cover=None, title="T")
        stored = ID3(result.path).getall("CHAP")  # file order
        assert [c.sub_frames["TIT2"].text[0] for c in stored] == ["A much longer opening title", "B", "Mid"]

    def test_m4b_gets_native_chapters(self, tmp_path):
        result = speak_chapters(CHAPTERS, tmp_path / "out.m4b", engine=FakeEngine())
        assert MP4(result.path).chapters is not None
        assert [c.title for c in MP4(result.path).chapters] == ["Opening", "Europe", "Close"]

    def test_a_chapter_never_shares_a_chunk_with_its_neighbour(self, tmp_path):
        engine = FakeEngine()
        speak_chapters(CHAPTERS, tmp_path / "out.mp3", engine=engine)
        assert sorted(engine.texts) == sorted(["First words.", "Second words.", "Last."])

    def test_long_chapters_are_split_to_the_engine_limit(self, tmp_path):
        engine = FakeEngine()  # max_chars = 1000
        speak_chapters([Chapter("Long", "A sentence of words. " * 200)], tmp_path / "out.mp3", engine=engine)
        assert len(engine.texts) > 1
        assert all(len(t) <= engine.max_chars for t in engine.texts)

    def test_speed_applied_by_ffmpeg_scales_the_chapter_marks(self, tmp_path):
        result = speak_chapters(CHAPTERS, tmp_path / "out.mp3", engine=SlowEngine(), speed=2.0)
        assert [(m.start_ms, m.end_ms) for m in result.chapters] == [(0, 500), (500, 1000), (1000, 1500)]

    def test_format_comes_from_the_suffix_and_an_unknown_one_is_refused(self, tmp_path):
        with pytest.raises(ValueError, match="output format"):
            speak_chapters(CHAPTERS, tmp_path / "out.wav", engine=FakeEngine())


class TestFilesystem:
    def test_nothing_is_left_beside_the_output_or_in_work_dir(self, tmp_path):
        out_dir, work = tmp_path / "out", tmp_path / "work"
        speak_chapters(CHAPTERS, out_dir / "out.mp3", engine=FakeEngine(), work_dir=work)
        assert [p.name for p in out_dir.iterdir()] == ["out.mp3"]
        assert list(work.iterdir()) == []

    def test_work_dir_is_cleaned_after_a_failure_too(self, tmp_path):
        work = tmp_path / "work"
        with pytest.raises(SynthesisError):
            speak_chapters(
                CHAPTERS, tmp_path / "out.mp3", engine=FakeEngine(fail_always_at={1}), work_dir=work, retry_backoff=0
            )
        assert list(work.iterdir()) == []

    def test_resume_dir_survives_failure_and_is_reused(self, tmp_path):
        resume = tmp_path / "resume"
        with pytest.raises(SynthesisError):
            speak_chapters(
                CHAPTERS, tmp_path / "out.mp3", engine=FakeEngine(fail_always_at={2}), resume_dir=resume,
                retry_backoff=0,
            )
        assert len(list(resume.glob("*.wav"))) == 2

        engine = FakeEngine()
        speak_chapters(CHAPTERS, tmp_path / "out.mp3", engine=engine, resume_dir=resume)
        assert engine.texts == ["Last."]
        assert not resume.exists()


class TestProgress:
    def test_reports_done_and_total_in_utterances(self, tmp_path):
        seen = []
        speak_chapters(CHAPTERS, tmp_path / "out.mp3", engine=FakeEngine(), on_progress=lambda d, t: seen.append((d, t)))
        assert seen[0] == (0, 3)
        assert seen[-1] == (3, 3)

    def test_a_broken_callback_does_not_fail_the_run(self, tmp_path):
        def boom(done, total):
            raise RuntimeError("ui went away")

        result = speak_chapters(CHAPTERS, tmp_path / "out.mp3", engine=FakeEngine(), on_progress=boom)
        assert result.path.exists()


class TestSplitText:
    def test_a_sentence_longer_than_the_limit_is_cut_at_words(self):
        pieces = split_text("word " * 100, max_chars=42)
        assert all(len(p) <= 42 for p in pieces)
        assert " ".join(pieces).split() == ["word"] * 100

    def test_an_unbroken_run_is_cut_as_a_last_resort(self):
        assert all(len(p) <= 10 for p in split_text("x" * 35, max_chars=10))


def test_importing_echo_reads_no_env_file_and_loads_no_app_code(tmp_path):
    (tmp_path / ".env").write_text("DEFAULT_ENGINE=gemini\nECHO_SENTINEL=1\n")
    code = (
        "import os, sys; before = dict(os.environ); import echo; "
        "assert dict(os.environ) == before, 'os.environ changed'; "
        "heavy = {'echo_app', 'dotenv', 'fitz', 'pymupdf', 'ebooklib', 'bs4', 'edge_tts'}; "
        "loaded = sorted(heavy & {m.split('.')[0] for m in sys.modules}); "
        "assert not loaded, loaded"
    )
    root = str(__import__("pathlib").Path(echo.__file__).parent.parent)
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=tmp_path, capture_output=True, text=True, env={"PYTHONPATH": root}
    )
    assert result.returncode == 0, result.stderr
