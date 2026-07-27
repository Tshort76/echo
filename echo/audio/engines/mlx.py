"""Local synthesis on Apple Silicon via ``mlx-audio``.

Offline, private, unmetered, and Metal-accelerated. Which model runs is
configurable (``MLX_TTS_MODEL``) because mlx-audio hosts twenty-odd of them and
they differ a lot in speed, quality and dependencies.

A note on Kokoro specifically: it needs the ``misaki`` grapheme-to-phoneme
package, whose ``[en]`` extra pulls in spaCy, which has no Python 3.14 wheels. On
3.14 either run a model that needs no phonemizer (Chatterbox Turbo works) or use
a 3.13 environment. :meth:`MlxEngine.check_available` says so directly rather
than letting the ImportError surface raw.
"""

from __future__ import annotations

import asyncio
import logging
import platform
from pathlib import Path

import echo.constants as ec
from echo.audio.engines.base import BaseEngine, EngineUnavailable, SynthOutput, VoiceInfo
from echo.audio.wav import write_float_wav

log = logging.getLogger(__name__)

#: Kokoro voice-name prefixes: first letter is the language, second the gender.
_LANG_BY_PREFIX = {
    "a": ("en", "US"),
    "b": ("en", "GB"),
    "e": ("es", ""),
    "f": ("fr", ""),
    "h": ("hi", ""),
    "i": ("it", ""),
    "j": ("ja", ""),
    "p": ("pt", "BR"),
    "z": ("zh", ""),
}

#: The Kokoro voice set. Enumerated statically because listing them requires
#: reaching into the model repo, and this list is stable.
_KOKORO_VOICES: tuple[str, ...] = (
    "af_heart", "af_alloy", "af_aoede", "af_bella", "af_jessica", "af_kore",
    "af_nicole", "af_nova", "af_river", "af_sarah", "af_sky",
    "am_adam", "am_echo", "am_eric", "am_fenrir", "am_liam", "am_michael",
    "am_onyx", "am_puck", "am_santa",
    "bf_alice", "bf_emma", "bf_isabella", "bf_lily",
    "bm_daniel", "bm_fable", "bm_george", "bm_lewis",
    "ef_dora", "em_alex",
    "ff_siwis",
    "hf_alpha", "hf_beta", "hm_omega", "hm_psi",
    "if_sara", "im_nicola",
    "jf_alpha", "jf_gongitsune", "jf_nezumi", "jf_tebukuro", "jm_kumo",
    "pf_dora", "pm_alex", "pm_santa",
    "zf_xiaobei", "zf_xiaoni", "zf_xiaoxiao", "zf_xiaoyi",
    "zm_yunjian", "zm_yunxi", "zm_yunxia", "zm_yunyang",
)

_MISAKI_HELP = (
    "This mlx-audio model needs the 'misaki' phonemizer, which requires spaCy — and "
    "spaCy cannot build on Python {py} here. Either run echo on Python 3.13 (see "
    "requirements-local-llm.txt), or set MLX_TTS_MODEL to a model that needs no "
    "phonemizer, e.g. MLX_TTS_MODEL=mlx-community/chatterbox-turbo-4bit"
)

_ESPEAK_HELP = (
    "Kokoro needs an espeak fallback for words outside its dictionary. Without it, "
    "misaki returns no phonemes for such a word and synthesis dies on the first "
    "unusual one. Install the pip-only backend: "
    "`pip install phonemizer-fork espeakng-loader`."
)


def _is_kokoro(model_id: str) -> bool:
    return "kokoro" in model_id.lower()


def _wire_espeak() -> bool:
    """Point phonemizer at the espeak-ng library shipped by ``espeakng-loader``.

    misaki looks for a *system* espeak-ng and silently logs "espeak not installed"
    when it can't find one — after which any out-of-dictionary word yields
    ``phonemes=None`` and Kokoro raises ``NoneType + str`` mid-synthesis. Wiring the
    pip-installed library in avoids requiring `brew install espeak-ng`.

    Idempotent; returns whether a working fallback is now available.
    """
    try:
        import espeakng_loader  # noqa: PLC0415
        from phonemizer.backend.espeak.wrapper import EspeakWrapper  # noqa: PLC0415
    except ImportError:
        return False

    try:
        library = Path(espeakng_loader.get_library_path())
        if not library.exists():
            return False
        EspeakWrapper.set_library(str(library))
        # Older phonemizer builds have no set_data_path; the loader's data is found
        # relative to the library in that case.
        if hasattr(EspeakWrapper, "set_data_path"):
            EspeakWrapper.set_data_path(str(espeakng_loader.get_data_path()))
        return True
    except Exception as ex:  # pragma: no cover - defensive
        log.debug(f"Could not wire espeak-ng into phonemizer: {ex}")
        return False


class MlxEngine(BaseEngine):
    name = "mlx"
    label = "Local (mlx-audio, Apple Silicon)"
    audio_suffix = ".wav"
    #: One model, one Metal device: parallel calls would just contend.
    max_concurrency = 1
    max_chars = 4000
    supports_speed = True

    def __init__(self, model_id: str = None, voice: str = None):
        self.model_id = model_id or ec.MLX_TTS_MODEL
        self._voice = voice or ec.MLX_TTS_VOICE
        self._model = None

    # ── availability ────────────────────────────────────────────────────────
    def check_available(self) -> None:
        if platform.system() != "Darwin" or platform.machine() != "arm64":
            raise EngineUnavailable(
                "The mlx engine needs an Apple Silicon Mac; this machine is "
                f"{platform.system()}/{platform.machine()}."
            )
        try:
            import mlx_audio  # noqa: F401, PLC0415
        except ImportError as ex:
            raise EngineUnavailable("The mlx engine needs `pip install mlx-audio`") from ex

        if _is_kokoro(self.model_id):
            try:
                import misaki.en  # noqa: F401, PLC0415
            except ImportError as ex:
                raise EngineUnavailable(_MISAKI_HELP.format(py=platform.python_version())) from ex
            # Checked here, not left to fail during synthesis: without the espeak
            # fallback Kokoro reports itself ready and then dies on the first
            # out-of-dictionary word, three retries deep.
            if not _wire_espeak():
                raise EngineUnavailable(_ESPEAK_HELP)

    # ── model ───────────────────────────────────────────────────────────────
    def _model_or_load(self):
        if self._model is None:
            self.check_available()  # also wires espeak for Kokoro
            from mlx_audio.tts.utils import load_model  # noqa: PLC0415

            log.info(f"Loading {self.model_id} (first run downloads weights from Hugging Face)")
            self._model = load_model(self.model_id)
        return self._model

    # ── voices ──────────────────────────────────────────────────────────────
    def voices(self) -> list[VoiceInfo]:
        if not _is_kokoro(self.model_id):
            # Non-Kokoro models either take a reference clip or ship a single
            # default voice; offer the configured one rather than inventing a list.
            return [VoiceInfo(id=self._voice, engine=self.name, name=self._voice, tags=self.model_id)]

        out: list[VoiceInfo] = []
        for voice in _KOKORO_VOICES:
            prefix, _, given = voice.partition("_")
            language, locale = _LANG_BY_PREFIX.get(prefix[0], ("", ""))
            gender = {"f": "Female", "m": "Male"}.get(prefix[1:2], "")
            out.append(
                VoiceInfo(
                    id=voice,
                    engine=self.name,
                    name=given.title() or voice,
                    language=language,
                    locale=locale,
                    gender=gender,
                    tags="Kokoro",
                )
            )
        return out

    def default_voice(self) -> str:
        return self._voice

    def lang_code_for(self, voice: str) -> str:
        if ec.MLX_LANG_CODE:
            return ec.MLX_LANG_CODE
        # Kokoro takes the single-letter code that prefixes its voice names.
        return voice[0] if _is_kokoro(self.model_id) and voice else "a"

    # ── synthesis ───────────────────────────────────────────────────────────
    def _synthesize_blocking(self, text: str, voice: str, speed: float, out_path: Path) -> None:
        import numpy as np  # noqa: PLC0415

        model = self._model_or_load()
        kwargs = {"text": text, "speed": speed}
        if _is_kokoro(self.model_id):
            kwargs["voice"] = voice
            kwargs["lang_code"] = self.lang_code_for(voice)

        segments = list(model.generate(**kwargs))
        if not segments:
            raise EngineUnavailable(f"{self.model_id} produced no audio for this passage")

        audio = np.concatenate([np.asarray(s.audio, dtype=np.float32).reshape(-1) for s in segments])
        rate = getattr(segments[0], "sample_rate", 24_000)
        write_float_wav(audio, out_path, rate=rate)

    async def synthesize(self, text: str, voice: str, speed: float, out_path: Path) -> SynthOutput:
        await asyncio.to_thread(self._synthesize_blocking, text, voice, speed, out_path)
        return SynthOutput(path=out_path)
