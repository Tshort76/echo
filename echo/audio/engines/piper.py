"""Local, offline synthesis with Piper (ONNX, CPU).

The local engine that works everywhere the library does: any OS, Python 3.14
included, no GPU, and no phonemizer setup, because the ``piper-tts`` wheel
bundles espeak-ng. Measured at RTF 0.027 on an M4 Pro CPU (a paragraph that
reads for 31 s synthesized in 0.85 s). Kokoro on mlx sounds better, but runs
only on Apple Silicon under Python 3.13.

Voices are ~60 MB ONNX files from the rhasspy/piper-voices repository on Hugging
Face. They are downloaded on first use into ``voice_dir`` (default
``~/.cache/echo/piper``, or ``PIPER_VOICE_DIR``), so the first chapter with a new
voice needs the network, and every later run is offline.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import wave
from pathlib import Path

from echo.audio.engines.base import BaseEngine, EngineUnavailable, SynthOutput, VoiceInfo

log = logging.getLogger(__name__)

DEFAULT_VOICE = "en_GB-alan-medium"

#: A short list of good single-speaker English voices for pickers. Any id from
#: https://huggingface.co/rhasspy/piper-voices works too; it is fetched on first use.
_CATALOGUE = {
    "en_GB-alan-medium": "Male",
    "en_GB-alba-medium": "Female",
    "en_GB-cori-high": "Female",
    "en_GB-jenny_dioco-medium": "Female",
    "en_GB-northern_english_male-medium": "Male",
    "en_GB-southern_english_female-low": "Female",
    "en_US-amy-medium": "Female",
    "en_US-hfc_female-medium": "Female",
    "en_US-joe-medium": "Male",
    "en_US-lessac-high": "Female",
    "en_US-ryan-high": "Male",
}


def _voice_info(voice_id: str, gender: str = "") -> VoiceInfo:
    lang, _, rest = voice_id.partition("-")
    language, _, locale = lang.partition("_")
    name, _, quality = rest.rpartition("-")
    return VoiceInfo(
        id=voice_id,
        engine="piper",
        name=(name or voice_id).replace("_", " ").title(),
        language=language,
        locale=locale,
        gender=gender,
        tags=quality,
    )


class PiperEngine(BaseEngine):
    name = "piper"
    label = "Piper (local, offline)"
    audio_suffix = ".wav"
    #: One ONNX session per voice, already multithreaded inside onnxruntime.
    max_concurrency = 1
    max_chars = 4000
    #: Via the model's length scale, not by resampling.
    supports_speed = True

    def __init__(self, voice: str = None, voice_dir: str | Path = None):
        self._voice = voice or os.environ.get("PIPER_VOICE", DEFAULT_VOICE)
        default_dir = os.environ.get("PIPER_VOICE_DIR") or Path.home() / ".cache" / "echo" / "piper"
        self.voice_dir = Path(voice_dir or default_dir).expanduser()
        self._loaded: dict[str, object] = {}
        self._lock = threading.Lock()

    def check_available(self) -> None:
        try:
            import piper  # noqa: F401, PLC0415
        except ImportError as ex:
            raise EngineUnavailable(
                "Piper needs `pip install piper-tts` (or the `echo-tts[piper]` extra)"
            ) from ex

    def voices(self) -> list[VoiceInfo]:
        found = {p.name.removesuffix(".onnx") for p in self.voice_dir.glob("*.onnx")} if self.voice_dir.is_dir() else set()
        ids = sorted(set(_CATALOGUE) | found)
        return [_voice_info(v, _CATALOGUE.get(v, "")) for v in ids]

    def default_voice(self) -> str:
        return self._voice

    def _load(self, voice: str):
        with self._lock:
            if voice not in self._loaded:
                from piper import PiperVoice  # noqa: PLC0415
                from piper.download_voices import download_voice  # noqa: PLC0415

                model = self.voice_dir / f"{voice}.onnx"
                if not (model.exists() and Path(f"{model}.json").exists()):
                    log.info(f"Downloading Piper voice {voice} to {self.voice_dir} (~60 MB, once)")
                    self.voice_dir.mkdir(parents=True, exist_ok=True)
                    download_voice(voice, self.voice_dir)
                self._loaded[voice] = PiperVoice.load(model)
            return self._loaded[voice]

    def _synthesize_blocking(self, text: str, voice: str, speed: float, out_path: Path) -> None:
        from piper import SynthesisConfig  # noqa: PLC0415

        model = self._load(voice)
        # Length scale is duration: larger is slower, so a speed-up divides it.
        config = SynthesisConfig(length_scale=model.config.length_scale / speed)
        with wave.open(str(out_path), "wb") as wav:
            model.synthesize_wav(text, wav, syn_config=config)

    async def synthesize(self, text: str, voice: str, speed: float, out_path: Path) -> SynthOutput:
        await asyncio.to_thread(self._synthesize_blocking, text, voice, speed, out_path)
        return SynthOutput(path=out_path)
