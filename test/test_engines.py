"""The engine registry and per-engine behaviour that does not need a network."""

import asyncio

import pytest

import echo.constants as ec
from echo.audio.engines import (
    EngineUnavailable,
    available_engines,
    engine_names,
    get_engine,
)
from echo.audio.engines.base import BaseEngine, VoiceInfo
from echo.audio.engines.edge import EdgeEngine, speed_as_rate
from echo.audio.engines.google import GeminiEngine, GoogleCloudEngine
from echo.audio.engines.mlx import MlxEngine


class TestRegistry:
    def test_all_four_engines_are_registered(self):
        assert set(engine_names()) == {"edge", "gemini", "google-cloud", "mlx"}

    @pytest.mark.parametrize(
        "alias,expected",
        [
            ("google", "google-cloud"),
            ("cloud", "google-cloud"),
            ("gcp", "google-cloud"),
            ("local", "mlx"),
            ("kokoro", "mlx"),
            ("mlx-audio", "mlx"),
            ("edge-tts", "edge"),
            ("EDGE", "edge"),
            ("  edge  ", "edge"),
        ],
    )
    def test_aliases_resolve(self, alias, expected):
        assert get_engine(alias).name == expected

    def test_engines_are_cached_per_process(self):
        assert get_engine("edge") is get_engine("edge")

    def test_unknown_engine_is_rejected(self):
        with pytest.raises(ValueError, match="Unknown engine"):
            get_engine("wav2lip")

    def test_none_falls_back_to_the_configured_default(self):
        assert get_engine(None).name == get_engine(ec.DEFAULT_ENGINE).name

    def test_availability_never_raises(self):
        for engine, ok, reason in available_engines():
            assert isinstance(ok, bool)
            assert ok or reason, f"{engine.name} reported unavailable with no reason"


class TestEngineContract:
    """Every engine must declare the attributes the pipeline reads."""

    @pytest.mark.parametrize("name", ["edge", "gemini", "google-cloud", "mlx"])
    def test_declares_the_full_contract(self, name):
        engine = get_engine(name)
        assert engine.name == name
        assert engine.label
        assert engine.audio_suffix.startswith(".")
        assert engine.max_concurrency >= 1
        assert engine.max_chars > 0
        assert isinstance(engine.supports_speed, bool)
        assert isinstance(engine.default_voice(), str)

    def test_base_engine_reports_no_voices_clearly(self):
        with pytest.raises(EngineUnavailable, match="no available voices"):
            BaseEngine().default_voice()

    def test_base_synthesize_is_unimplemented(self):
        with pytest.raises(NotImplementedError):
            asyncio.run(BaseEngine().synthesize("hi", "v", 1.0, "x.mp3"))


class TestEdgeEngine:
    @pytest.mark.parametrize(
        "speed,expected",
        [(1.0, "+0%"), (1.5, "+50%"), (1.25, "+25%"), (0.5, "-50%"), (0.75, "-25%"), (2.0, "+100%")],
    )
    def test_speed_becomes_a_rate_string(self, speed, expected):
        assert speed_as_rate(speed) == expected

    @pytest.mark.parametrize("speed", [0.1, 0.24, 5.0, 9.0])
    def test_out_of_range_speed_is_refused(self, speed):
        with pytest.raises(ValueError, match="out of range"):
            speed_as_rate(speed)

    def test_voices_parse_from_the_shipped_cache(self):
        voices = EdgeEngine().voices()
        assert len(voices) > 100
        sonia = next(v for v in voices if v.id == "en-GB-SoniaNeural")
        assert (sonia.language, sonia.locale, sonia.gender) == ("en", "GB", "Female")
        assert sonia.name == "Sonia"
        assert all(v.engine == "edge" for v in voices)

    def test_needs_no_setup(self):
        assert EdgeEngine().is_available() == (True, "")


class TestGoogleEngines:
    def test_gemini_says_what_is_missing_without_a_key(self):
        engine = GeminiEngine(api_key=None)
        ok, reason = engine.is_available()
        if not ok:
            assert "GEMINI_API_KEY" in reason

    def test_gemini_offers_the_prebuilt_voices(self):
        voices = GeminiEngine(api_key="x").voices()
        assert len(voices) == 30
        assert {v.id for v in voices} >= {"Kore", "Puck", "Zephyr"}
        assert all(v.engine == "gemini" for v in voices)

    def test_gemini_cannot_control_rate_so_ffmpeg_does(self):
        assert GeminiEngine(api_key="x").supports_speed is False

    def test_cloud_stays_under_the_five_thousand_byte_request_limit(self):
        assert GoogleCloudEngine().max_chars < 5000

    def test_cloud_supports_its_own_rate(self):
        assert GoogleCloudEngine().supports_speed is True


class TestMlxEngine:
    def test_kokoro_voice_names_decode_to_language_and_gender(self):
        voices = MlxEngine(model_id="prince-canuma/Kokoro-82M").voices()
        by_id = {v.id: v for v in voices}
        assert by_id["bf_emma"].language == "en"
        assert by_id["bf_emma"].locale == "GB"
        assert by_id["bf_emma"].gender == "Female"
        assert by_id["am_adam"].locale == "US"
        assert by_id["am_adam"].gender == "Male"
        assert by_id["jf_alpha"].language == "ja"

    def test_lang_code_follows_the_voice_prefix(self):
        engine = MlxEngine(model_id="prince-canuma/Kokoro-82M")
        assert engine.lang_code_for("bf_emma") == "b"
        assert engine.lang_code_for("af_heart") == "a"

    def test_a_non_kokoro_model_offers_its_configured_voice(self):
        engine = MlxEngine(model_id="mlx-community/chatterbox-turbo-4bit", voice="default")
        voices = engine.voices()
        assert len(voices) == 1
        assert voices[0].id == "default"

    def test_it_runs_one_utterance_at_a_time(self):
        assert MlxEngine().max_concurrency == 1

    def test_missing_phonemizer_is_explained_not_just_raised(self):
        """Kokoro needs misaki, whose spaCy dependency has no 3.14 wheels — the
        engine should say what to do about it."""
        engine = MlxEngine(model_id="prince-canuma/Kokoro-82M")
        ok, reason = engine.is_available()
        if not ok and "misaki" in reason:
            assert "MLX_TTS_MODEL" in reason or "3.13" in reason


class TestVoiceInfo:
    def test_label_includes_locale_and_gender(self):
        v = VoiceInfo(id="x", engine="edge", name="Sonia", locale="GB", gender="Female")
        assert v.label == "Sonia (GB) · Female"

    def test_label_degrades_when_metadata_is_absent(self):
        assert VoiceInfo(id="Kore", engine="gemini", name="Kore").label == "Kore"
