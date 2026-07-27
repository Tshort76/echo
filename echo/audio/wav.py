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


def _floats_to_pcm16(samples) -> bytes:
    """Convert floats in [-1, 1] to little-endian 16-bit PCM.

    Uses numpy when it is available — it always is alongside a local engine, and it
    is far quicker over a few hundred thousand samples. The stdlib path keeps this
    module usable on the lite install, which has no numpy at all, and expects a flat
    iterable of floats.
    """
    try:
        import numpy as np  # noqa: PLC0415
    except ImportError:
        import array
        import sys

        # Clip: a model can emit values slightly outside the range, and wrapping
        # them would turn a loud passage into a burst of noise.
        pcm = array.array("h", (int(max(-1.0, min(1.0, float(s))) * 32767) for s in samples))
        if sys.byteorder == "big":
            pcm.byteswap()
        return pcm.tobytes()

    flat = np.asarray(samples, dtype=np.float32).reshape(-1)
    return (np.clip(flat, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()


def write_float_wav(samples, path: Path, rate: int, channels: int = 1) -> None:
    """Write a float array in [-1, 1] as 16-bit PCM WAV.

    With numpy present, ``samples`` is anything it can turn into a 1-D float array —
    including an mlx array, which supports the buffer protocol. Without it, pass a
    flat iterable of floats.
    """
    write_pcm16_wav(_floats_to_pcm16(samples), path, rate=rate, channels=channels)
