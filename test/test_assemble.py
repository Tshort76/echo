"""Assembly helpers: durations, chapter marks, atempo chains, SRT output."""

import shutil
import subprocess

import pytest

import echo.audio.assemble as asm
from echo.audio.wav import write_float_wav, write_pcm16_wav
from echo.document import Timing

HAVE_FFMPEG = asm.configure_ffmpeg() is not None


class TestAtempoChain:
    @pytest.mark.parametrize("speed", [0.5, 0.75, 1.25, 1.5, 2.0])
    def test_in_range_speeds_use_one_filter(self, speed):
        assert asm._atempo_chain(speed).count("atempo") == 1

    def test_above_two_is_chained(self):
        chain = asm._atempo_chain(3.0)
        assert chain.count("atempo") == 2
        factors = [float(part.split("=")[1]) for part in chain.split(",")]
        assert pytest.approx(factors[0] * factors[1], rel=1e-6) == 3.0

    def test_below_half_is_chained(self):
        chain = asm._atempo_chain(0.25)
        factors = [float(part.split("=")[1]) for part in chain.split(",")]
        assert pytest.approx(factors[0] * factors[1], rel=1e-6) == 0.25

    @pytest.mark.parametrize("speed", [0.25, 0.5, 1.0, 1.25, 3.0, 4.0])
    def test_every_factor_stays_within_ffmpeg_limits(self, speed):
        for part in asm._atempo_chain(speed).split(","):
            assert 0.5 <= float(part.split("=")[1]) <= 2.0


class TestWavDuration:
    def test_pcm16_duration(self, tmp_path):
        # One second of silence at 24 kHz mono, 16-bit.
        path = tmp_path / "a.wav"
        write_pcm16_wav(b"\x00\x00" * 24_000, path, rate=24_000)
        assert asm.audio_duration_ms(path) == pytest.approx(1000, abs=2)

    def test_float_wav_roundtrip(self, tmp_path):
        path = tmp_path / "b.wav"
        write_float_wav([0.0] * 12_000, path, rate=24_000)
        assert asm.audio_duration_ms(path) == pytest.approx(500, abs=2)

    def test_out_of_range_floats_are_clipped_not_wrapped(self, tmp_path):
        path = tmp_path / "c.wav"
        write_float_wav([2.0, -2.0, 0.5], path, rate=8000)
        data = path.read_bytes()[44:]
        # 2.0 would wrap to a large negative value if not clipped.
        assert int.from_bytes(data[0:2], "little", signed=True) == 32767
        assert int.from_bytes(data[2:4], "little", signed=True) == -32767

    def test_unsupported_suffix_is_refused(self, tmp_path):
        path = tmp_path / "d.ogg"
        path.write_bytes(b"nope")
        with pytest.raises(ValueError):
            asm.audio_duration_ms(path)


class TestChapterMarks:
    def test_marks_are_contiguous(self):
        marks = asm.chapter_marks(["One", "Two", "Three"], [[1000, 500], [2000], [750, 250]])
        assert [(m.start_ms, m.end_ms) for m in marks] == [(0, 1500), (1500, 3500), (3500, 4500)]
        assert [m.title for m in marks] == ["One", "Two", "Three"]

    def test_mismatched_lengths_are_an_error(self):
        with pytest.raises(ValueError):
            asm.chapter_marks(["One"], [[100], [200]])


class TestSrt:
    def test_cues_are_offset_by_preceding_segments(self, tmp_path):
        segments = [
            (1000, [Timing(0, 900, "First segment.")]),
            (1000, [Timing(0, 900, "Second segment.")]),
        ]
        path = asm.write_srt(tmp_path / "x.srt", segments)
        body = path.read_text()
        assert "00:00:00,000 --> 00:00:00,900" in body
        assert "00:00:01,000 --> 00:00:01,900" in body

    def test_overlapping_engine_timings_are_made_monotonic(self, tmp_path):
        segments = [(2000, [Timing(0, 1000, "one"), Timing(950, 1800, "two")])]
        path = asm.write_srt(tmp_path / "y.srt", segments)
        starts_ends = [line for line in path.read_text().splitlines() if "-->" in line]
        first_end = starts_ends[0].split(" --> ")[1]
        second_start = starts_ends[1].split(" --> ")[0]
        assert second_start >= first_end

    def test_time_formatting(self):
        assert asm._srt_time(3_661_001) == "01:01:01,001"
        assert asm._srt_time(-5) == "00:00:00,000"


class TestAssemble:
    def test_no_segments_is_an_error(self, tmp_path):
        with pytest.raises(asm.AssemblyError, match="no audio segments"):
            asm.assemble([], tmp_path / "out.m4b")

    def test_missing_segment_is_an_error(self, tmp_path):
        with pytest.raises(asm.AssemblyError, match="Missing audio segment"):
            asm.assemble([tmp_path / "nope.wav"], tmp_path / "out.m4b")

    def test_unknown_format_is_an_error(self, tmp_path):
        seg = tmp_path / "a.wav"
        write_pcm16_wav(b"\x00\x00" * 100, seg, rate=8000)
        with pytest.raises(asm.AssemblyError, match="Unsupported output format"):
            asm.assemble([seg], tmp_path / "out.ogg", fmt="ogg")

    @pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg not available")
    def test_wav_segments_become_a_chaptered_m4b(self, tmp_path):
        segments = []
        for i in range(3):
            seg = tmp_path / f"chunk_{i:05d}.wav"
            write_pcm16_wav(b"\x00\x00" * 24_000, seg, rate=24_000)  # 1s each
            segments.append(seg)
        marks = asm.chapter_marks(["A", "B"], [[1000], [1000, 1000]])

        out = asm.assemble(segments, tmp_path / "book", fmt="m4b", chapters=marks, title="T", author="A")
        assert out.suffix == ".m4b"
        assert asm.audio_duration_ms(out) == pytest.approx(3000, abs=150)

        probe = subprocess.run(
            [shutil.which("ffprobe") or "ffprobe", "-v", "error", "-show_chapters", out.as_posix()],
            capture_output=True,
            text=True,
        )
        if probe.returncode == 0:
            assert probe.stdout.count("[CHAPTER]") == 2

    @pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg not available")
    def test_speed_is_applied_when_the_engine_could_not(self, tmp_path):
        seg = tmp_path / "chunk_00000.wav"
        write_pcm16_wav(b"\x00\x00" * 48_000, seg, rate=24_000)  # 2s
        out = asm.assemble([seg], tmp_path / "fast", fmt="m4b", speed=2.0)
        assert asm.audio_duration_ms(out) == pytest.approx(1000, abs=200)

    @pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg not available")
    def test_cleanup_removes_the_chunk_directory(self, tmp_path):
        chunks = tmp_path / "book_chunks"
        chunks.mkdir()
        (chunks / "chunk_00000.wav").write_bytes(b"x")
        asm.cleanup(chunks)
        assert not chunks.exists()
        asm.cleanup(chunks)  # idempotent
