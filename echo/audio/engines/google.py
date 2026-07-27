"""Google's two text-to-speech paths, which differ in how you authenticate.

``gemini``
    The Gemini API's TTS models. Authenticates with a plain ``GEMINI_API_KEY``,
    which makes it the easiest engine to turn on. Returns raw PCM, so this module
    adds the WAV header.

``google-cloud``
    Cloud Text-to-Speech. Needs Application Default Credentials (a service
    account or ``gcloud auth application-default login``) — the REST API does not
    accept API keys. Worth the extra setup for its permanent free tier of
    4M Standard / 1M WaveNet characters a month, which covers a couple of books.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import echo.constants as ec
from echo.audio.engines.base import BaseEngine, EngineUnavailable, SynthOutput, VoiceInfo
from echo.audio.wav import write_pcm16_wav

log = logging.getLogger(__name__)

#: Gemini TTS returns signed 16-bit little-endian mono PCM at 24 kHz.
_PCM_RATE = 24_000

#: Prebuilt Gemini voices with the character Google documents for each. Gender is
#: not published, so it is left blank rather than guessed.
_GEMINI_VOICES: tuple[tuple[str, str], ...] = (
    ("Zephyr", "Bright"),
    ("Puck", "Upbeat"),
    ("Charon", "Informative"),
    ("Kore", "Firm"),
    ("Fenrir", "Excitable"),
    ("Leda", "Youthful"),
    ("Orus", "Firm"),
    ("Aoede", "Breezy"),
    ("Callirrhoe", "Easy-going"),
    ("Autonoe", "Bright"),
    ("Enceladus", "Breathy"),
    ("Iapetus", "Clear"),
    ("Umbriel", "Easy-going"),
    ("Algieba", "Smooth"),
    ("Despina", "Smooth"),
    ("Erinome", "Clear"),
    ("Algenib", "Gravelly"),
    ("Rasalgethi", "Informative"),
    ("Laomedeia", "Upbeat"),
    ("Achernar", "Soft"),
    ("Alnilam", "Firm"),
    ("Schedar", "Even"),
    ("Gacrux", "Mature"),
    ("Pulcherrima", "Forward"),
    ("Achird", "Friendly"),
    ("Zubenelgenubi", "Casual"),
    ("Vindemiatrix", "Gentle"),
    ("Sadachbia", "Lively"),
    ("Sadaltager", "Knowledgeable"),
    ("Sulafat", "Warm"),
)


class GeminiEngine(BaseEngine):
    name = "gemini"
    label = "Gemini TTS (API key)"
    audio_suffix = ".wav"
    max_concurrency = 2  # free-tier request rates are modest
    max_chars = 6000
    #: The TTS models take no rate parameter, so speed is applied downstream by
    #: ffmpeg rather than pretended at here.
    supports_speed = False

    def __init__(self, model: str = None, api_key: str = None):
        self.model = model or ec.GEMINI_TTS_MODEL
        # `is not None`, not `or`: an explicit "" means "no key", and `or` would
        # silently fall back to the environment.
        self._api_key = api_key if api_key is not None else ec.GEMINI_API_KEY
        self._client = None

    def check_available(self) -> None:
        if not self._api_key:
            raise EngineUnavailable(
                "Gemini TTS needs an API key. Set GEMINI_API_KEY in your .env "
                "(create one at https://aistudio.google.com/apikey)."
            )
        try:
            import google.genai  # noqa: F401, PLC0415
        except ImportError as ex:
            raise EngineUnavailable("Gemini TTS needs `pip install google-genai`") from ex

    def _client_or_load(self):
        if self._client is None:
            self.check_available()
            from google import genai  # noqa: PLC0415

            self._client = genai.Client(api_key=self._api_key)
        return self._client

    def voices(self) -> list[VoiceInfo]:
        return [
            VoiceInfo(id=name, engine=self.name, name=name, language="en", tags=character)
            for name, character in _GEMINI_VOICES
        ]

    def default_voice(self) -> str:
        return "Kore"

    def _synthesize_blocking(self, text: str, voice: str, out_path: Path) -> None:
        from google.genai import types  # noqa: PLC0415

        response = self._client_or_load().models.generate_content(
            model=self.model,
            contents=text,
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)
                    )
                ),
            ),
        )
        try:
            part = response.candidates[0].content.parts[0]
            pcm = part.inline_data.data
        except (AttributeError, IndexError, TypeError) as ex:
            raise EngineUnavailable(f"Gemini TTS returned no audio for this passage: {ex}") from ex
        if not pcm:
            raise EngineUnavailable("Gemini TTS returned an empty audio payload")
        write_pcm16_wav(pcm, out_path, rate=_PCM_RATE)

    async def synthesize(self, text: str, voice: str, speed: float, out_path: Path) -> SynthOutput:
        await asyncio.to_thread(self._synthesize_blocking, text, voice, out_path)
        return SynthOutput(path=out_path)


class GoogleCloudEngine(BaseEngine):
    name = "google-cloud"
    label = "Google Cloud TTS (free tier)"
    audio_suffix = ".mp3"
    max_concurrency = 4
    #: Cloud TTS rejects requests over 5,000 bytes; stay clear of the limit since
    #: non-ASCII characters cost more than one byte.
    max_chars = 4000
    supports_speed = True

    def __init__(self, voice: str = None):
        self._voice = voice or ec.GOOGLE_CLOUD_VOICE
        self._client = None

    def check_available(self) -> None:
        try:
            from google.cloud import texttospeech  # noqa: F401, PLC0415
        except ImportError as ex:
            raise EngineUnavailable(
                "Google Cloud TTS needs `pip install google-cloud-texttospeech`"
            ) from ex
        try:
            self._client_or_load()
        except Exception as ex:
            raise EngineUnavailable(
                "Google Cloud TTS could not find credentials. Run "
                "`gcloud auth application-default login`, or set "
                "GOOGLE_APPLICATION_CREDENTIALS to a service-account JSON file. "
                "(The REST API does not accept plain API keys.)"
            ) from ex

    def _client_or_load(self):
        if self._client is None:
            from google.cloud import texttospeech  # noqa: PLC0415

            self._client = texttospeech.TextToSpeechClient()
        return self._client

    def voices(self) -> list[VoiceInfo]:
        try:
            client = self._client_or_load()
            response = client.list_voices()
        except Exception as ex:
            log.info(f"Could not list Cloud TTS voices ({ex}); offering the configured default only")
            return [VoiceInfo(id=self._voice, engine=self.name, name=self._voice)]

        out: list[VoiceInfo] = []
        for voice in response.voices:
            locale = voice.language_codes[0] if voice.language_codes else ""
            language, _, region = locale.partition("-")
            out.append(
                VoiceInfo(
                    id=voice.name,
                    engine=self.name,
                    name=voice.name.split("-", 2)[-1],
                    language=language,
                    locale=region,
                    gender=voice.ssml_gender.name.title() if voice.ssml_gender else "",
                    tags=f"{voice.natural_sample_rate_hertz} Hz",
                )
            )
        return sorted(out, key=lambda v: v.id)

    def default_voice(self) -> str:
        return self._voice

    def _synthesize_blocking(self, text: str, voice: str, speed: float, out_path: Path) -> None:
        from google.cloud import texttospeech as gtts  # noqa: PLC0415

        # "en-GB-Neural2-C" -> language code "en-GB"
        language_code = "-".join(voice.split("-")[:2]) if voice.count("-") >= 2 else "en-GB"
        response = self._client_or_load().synthesize_speech(
            input=gtts.SynthesisInput(text=text),
            voice=gtts.VoiceSelectionParams(language_code=language_code, name=voice),
            audio_config=gtts.AudioConfig(
                audio_encoding=gtts.AudioEncoding.MP3,
                speaking_rate=max(0.25, min(4.0, speed)),
            ),
        )
        if not response.audio_content:
            raise EngineUnavailable("Google Cloud TTS returned an empty audio payload")
        out_path.write_bytes(response.audio_content)

    async def synthesize(self, text: str, voice: str, speed: float, out_path: Path) -> SynthOutput:
        await asyncio.to_thread(self._synthesize_blocking, text, voice, speed, out_path)
        return SynthOutput(path=out_path)
