"""Minimal WAV writing.

Local and Gemini engines hand back raw samples rather than an encoded file, and
a 44-byte canonical header is all that stands between those samples and
something ffmpeg can read. Not worth a dependency.
"""

from __future__ import annotations

import struct
from pathlib import Path


def write_pcm16_wav(pcm: bytes, path: Path, rate: int, channels: int = 1) -> None:
    """Write signed 16-bit little-endian PCM as a WAV file."""
    width = 2
    block_align = channels * width
    header = b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt "
    header += struct.pack(
        "<IHHIIHH",
        16,  # fmt chunk size
        1,  # format: PCM
        channels,
        rate,
        rate * block_align,
        block_align,
        width * 8,
    )
    header += b"data" + struct.pack("<I", len(pcm))
    Path(path).write_bytes(header + pcm)


def write_float_wav(samples, path: Path, rate: int, channels: int = 1) -> None:
    """Write a float array in [-1, 1] as 16-bit PCM WAV.

    ``samples`` is anything numpy can turn into a 1-D float array — including an
    mlx array, which supports the buffer protocol.
    """
    import numpy as np  # noqa: PLC0415  (numpy arrives with the local engines)

    flat = np.asarray(samples, dtype=np.float32).reshape(-1)
    # Guard against a model emitting values slightly outside the range.
    clipped = np.clip(flat, -1.0, 1.0)
    pcm = (clipped * 32767.0).astype("<i2").tobytes()
    write_pcm16_wav(pcm, path, rate=rate, channels=channels)
