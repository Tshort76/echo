"""Turn synthesized chunks into one finished audiobook.

This replaces pydub, which was last released in March 2021, needed the
``audioop-lts`` shim on Python 3.13+, and worked by decoding every chunk to raw
PCM in memory before re-encoding the lot — roughly 6 GB of RAM for a ten-hour
book, plus a second generation of lossy encoding.

ffmpeg does the same job in one pass at constant memory, and is already bundled
with the frozen app. Writing MP3 from MP3 chunks is now a stream copy: no
re-encode, no quality loss.

Durations come from mutagen and the WAV header rather than ffprobe, so the
packaged app only has to ship the one ffmpeg binary it already does.
"""

from __future__ import annotations

import logging
import shutil
import struct
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import echo.constants as ec
from echo.audio.mp3_utils import configure_ffmpeg

log = logging.getLogger(__name__)

FORMATS = ("m4b", "mp3")


class AssemblyError(RuntimeError):
    pass


@dataclass(slots=True)
class ChapterMark:
    title: str
    start_ms: int
    end_ms: int


# ─────────────────────────────────────────────────────────────────────────────
# Durations
# ─────────────────────────────────────────────────────────────────────────────


def _wav_duration_ms(path: Path) -> int:
    """Read duration straight out of the WAV header."""
    with open(path, "rb") as fp:
        if fp.read(4) != b"RIFF":
            raise ValueError(f"{path} is not a RIFF/WAV file")
        fp.seek(22)
        channels, rate = struct.unpack("<HI", fp.read(6))
        fp.seek(34)
        (bits,) = struct.unpack("<H", fp.read(2))
        # Walk chunks to find 'data' — the header is not always exactly 44 bytes.
        fp.seek(36)
        while True:
            header = fp.read(8)
            if len(header) < 8:
                raise ValueError(f"{path} has no data chunk")
            chunk_id, size = struct.unpack("<4sI", header)
            if chunk_id == b"data":
                bytes_per_second = rate * channels * (bits // 8)
                if not bytes_per_second:
                    raise ValueError(f"{path} has a zero byte rate")
                return int(size * 1000 / bytes_per_second)
            fp.seek(size + (size % 2), 1)


def audio_duration_ms(path: Path) -> int:
    """Duration of a synthesized chunk, without shelling out."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".wav":
        return _wav_duration_ms(path)
    if suffix in (".mp3", ".m4a", ".m4b", ".mp4", ".aac"):
        from mutagen import File as MutagenFile  # noqa: PLC0415

        audio = MutagenFile(path)
        if audio is None or not getattr(audio, "info", None):
            raise ValueError(f"Could not read the duration of {path}")
        return int(audio.info.length * 1000)
    raise ValueError(f"Unsupported audio suffix for duration: {path.suffix}")


# ─────────────────────────────────────────────────────────────────────────────
# ffmpeg plumbing
# ─────────────────────────────────────────────────────────────────────────────


def _ffmpeg() -> str:
    binary = configure_ffmpeg()
    if binary is None:
        raise AssemblyError(
            "ffmpeg was not found — it is needed to join the synthesized chunks. "
            "Install it (`brew install ffmpeg` on macOS) or, for a packaged build, "
            "run `python packaging/fetch_ffmpeg.py`."
        )
    return binary


def _atempo_chain(speed: float) -> str:
    """ffmpeg's atempo filter only accepts 0.5–2.0, so chain it for extremes."""
    factors: list[float] = []
    remaining = speed
    while remaining > 2.0:
        factors.append(2.0)
        remaining /= 2.0
    while remaining < 0.5:
        factors.append(0.5)
        remaining /= 0.5
    factors.append(remaining)
    return ",".join(f"atempo={f:.6g}" for f in factors)


def _concat_list(segments: list[Path], directory: Path) -> Path:
    """Write ffmpeg's concat demuxer playlist."""
    listing = directory / "concat.txt"
    lines = []
    for segment in segments:
        # The concat demuxer takes single quotes; escape any in the path.
        escaped = str(segment.resolve()).replace("'", "'\\''")
        lines.append(f"file '{escaped}'")
    listing.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return listing


def _ffmetadata(chapters: list[ChapterMark], title: str | None, author: str | None, directory: Path) -> Path:
    """Write an ffmetadata file describing the chapter marks."""
    lines = [";FFMETADATA1"]
    if title:
        lines.append(f"title={_escape_meta(title)}")
        lines.append(f"album={_escape_meta(title)}")
    if author:
        lines.append(f"artist={_escape_meta(author)}")
        lines.append(f"album_artist={_escape_meta(author)}")
    for mark in chapters:
        lines += [
            "",
            "[CHAPTER]",
            "TIMEBASE=1/1000",
            f"START={max(0, mark.start_ms)}",
            f"END={max(mark.start_ms + 1, mark.end_ms)}",
            f"title={_escape_meta(mark.title)}",
        ]
    path = directory / "chapters.txt"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _escape_meta(value: str) -> str:
    for char in ("\\", "=", ";", "#"):
        value = value.replace(char, "\\" + char)
    return value.replace("\n", " ")


def _run(cmd: list[str]) -> None:
    log.debug("Running: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        tail = (result.stderr or "").strip().splitlines()[-12:]
        raise AssemblyError("ffmpeg failed:\n" + "\n".join(tail))


# ─────────────────────────────────────────────────────────────────────────────
# Assembly
# ─────────────────────────────────────────────────────────────────────────────


def assemble(
    segments: list[Path],
    output_path: Path,
    fmt: str = None,
    chapters: list[ChapterMark] = None,
    title: str = None,
    author: str = None,
    speed: float = None,
    bitrate: str = None,
) -> Path:
    """Join ``segments`` into ``output_path``.

    Args:
        segments: chunk files in reading order. All must share a container.
        fmt: ``"m4b"`` (chaptered) or ``"mp3"``.
        chapters: chapter marks, written only for M4B.
        speed: applied here (atempo) when the engine could not apply it itself.
        bitrate: AAC/MP3 bitrate when re-encoding.
    """
    if not segments:
        raise AssemblyError("There are no audio segments to join")
    missing = [str(s) for s in segments if not Path(s).exists()]
    if missing:
        raise AssemblyError(f"Missing audio segment(s): {missing[:5]}")

    fmt = (fmt or ec.DEFAULT_FORMAT).lower().lstrip(".")
    if fmt not in FORMATS:
        raise AssemblyError(f"Unsupported output format '{fmt}'. Choose from: {', '.join(FORMATS)}")

    output_path = Path(output_path).with_suffix(f".{fmt}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    bitrate = bitrate or ec.M4B_BITRATE
    needs_tempo = speed is not None and abs(speed - 1.0) > 0.001
    suffixes = {Path(s).suffix.lower() for s in segments}

    with tempfile.TemporaryDirectory(prefix="echo-assemble-") as tmp:
        tmpdir = Path(tmp)
        listing = _concat_list([Path(s) for s in segments], tmpdir)

        cmd = [_ffmpeg(), "-hide_banner", "-nostdin", "-y", "-f", "concat", "-safe", "0", "-i", str(listing)]

        metadata_input = None
        if fmt == "m4b" and chapters:
            metadata_input = _ffmetadata(chapters, title, author, tmpdir)
            cmd += ["-i", str(metadata_input), "-map_metadata", "1", "-map_chapters", "1"]

        cmd += ["-map", "0:a"]

        if needs_tempo:
            cmd += ["-filter:a", _atempo_chain(speed)]

        can_stream_copy = fmt == "mp3" and suffixes == {".mp3"} and not needs_tempo
        if can_stream_copy:
            cmd += ["-c:a", "copy"]
            log.info(f"Joining {len(segments)} chunk(s) by stream copy — no re-encode")
        elif fmt == "mp3":
            cmd += ["-c:a", "libmp3lame", "-b:a", bitrate]
        else:
            cmd += ["-c:a", "aac", "-b:a", bitrate, "-movflags", "+faststart"]

        if fmt == "m4b":
            cmd += ["-f", "mp4"]

        cmd.append(str(output_path))
        _run(cmd)

    duration = audio_duration_ms(output_path) / 1000
    log.info(
        f"Created {output_path} — {duration / 60:.1f} minutes"
        + (f", {len(chapters)} chapter(s)" if (fmt == "m4b" and chapters) else "")
    )
    return output_path


def chapter_marks(chapter_titles: list[str], durations_by_chapter: list[list[int]]) -> list[ChapterMark]:
    """Build chapter marks from per-chapter segment durations."""
    marks: list[ChapterMark] = []
    cursor = 0
    for title, durations in zip(chapter_titles, durations_by_chapter, strict=True):
        total = sum(durations)
        marks.append(ChapterMark(title=title, start_ms=cursor, end_ms=cursor + total))
        cursor += total
    return marks


def write_srt(path: Path, segments_with_timings: list[tuple[int, list]], offset_ms: int = 0) -> Path:
    """Write an SRT transcript from engine-reported timings.

    Args:
        segments_with_timings: ``(segment_duration_ms, [Timing, ...])`` in order.
            Timings are relative to their own segment, so each segment's start is
            offset by the total duration of everything before it.
    """
    lines: list[str] = []
    index = 1
    cursor = offset_ms
    previous_end = 0
    for duration_ms, timings in segments_with_timings:
        for timing in timings:
            # Engines report per-sentence spans that can overlap slightly; SRT
            # requires monotonic, non-overlapping cues.
            start = max(cursor + timing.start_ms, previous_end)
            end = max(cursor + timing.end_ms, start + 1)
            previous_end = end
            lines.append(str(index))
            lines.append(f"{_srt_time(start)} --> {_srt_time(end)}")
            lines.append(timing.text)
            lines.append("")
            index += 1
        cursor += duration_ms

    path = Path(path).with_suffix(".srt")
    path.write_text("\n".join(lines), encoding="utf-8")
    log.info(f"Wrote transcript with {index - 1} cue(s) to {path}")
    return path


def _srt_time(ms: int) -> str:
    ms = max(0, int(ms))
    hours, ms = divmod(ms, 3_600_000)
    minutes, ms = divmod(ms, 60_000)
    seconds, ms = divmod(ms, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{ms:03d}"


def cleanup(directory: Path) -> None:
    """Remove a chunk directory once its contents are safely in the output."""
    if directory and Path(directory).exists():
        shutil.rmtree(directory, ignore_errors=True)
        log.debug(f"Removed {directory}")
