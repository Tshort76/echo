import os
import re

from dotenv import load_dotenv

from echo.paths import resource_path

load_dotenv()


def _get_env_int(env_key: str, default_: int) -> int:
    if s := os.environ.get(env_key):
        try:
            return int(s.strip())
        except ValueError:
            pass
    return default_


def _get_env_float(env_key: str, default_: float) -> float:
    """Read a float from the environment.

    Split out from the int reader because ``DEFAULT_SPEED`` is a float: the old
    shared int-only helper meant the ``DEFAULT_SPEED="1.1"`` documented in the
    README raised ValueError, was swallowed, and silently fell back to the
    default.
    """
    if s := os.environ.get(env_key):
        try:
            return float(s.strip())
        except ValueError:
            pass
    return default_


def _get_env_bool(env_key: str, default_: bool = False) -> bool:
    s = os.environ.get(env_key)
    if s is None:
        return default_
    return s.strip().lower() in {"1", "true", "yes", "on"}


# Resolved so it works both from a normal checkout (any cwd) and a frozen build.
# Note: in a frozen app this points inside the bundle, so update_voice_cache_file()
# (a dev/CLI maintenance helper, not reachable from the GUI) would not be writable
# there — acceptable for now.
VOICE_CACHE_FILE = str(resource_path("resources/voices.csv"))
OUTPUT_FOLDER = os.environ.get("DEFAULT_OUTPUT_FOLDER", "")

##### Synthesis
DEFAULT_ENGINE = os.environ.get("DEFAULT_ENGINE", "edge")
DEFAULT_VOICE = os.environ.get("DEFAULT_VOICE", "en-GB-SoniaNeural")
# Kept at 1.25 for continuity with existing behaviour. Note that speed is baked
# into the audio by the engine, so 1.0 leaves the file re-usable at any playback
# speed — worth considering if you keep a library.
DEFAULT_SPEED = _get_env_float("DEFAULT_SPEED", 1.25)
CHUNK_SIZE = _get_env_int("DEFAULT_CHUNK_SIZE", 8000)  # characters
MAX_THREADS = _get_env_int("DEFAULT_MAX_THREADS", 4)
#: Attempts per chunk before a synthesis run gives up. Engines fail transiently
#: (edge-tts websocket 403s, cloud rate limits); one bad chunk should not cost
#: an hour of work.
MAX_RETRIES = _get_env_int("DEFAULT_MAX_RETRIES", 3)
RETRY_BACKOFF_SECONDS = _get_env_float("DEFAULT_RETRY_BACKOFF", 2.0)

##### Output
#: "m4b" (chaptered audiobook) or "mp3" (plays everywhere).
DEFAULT_FORMAT = os.environ.get("DEFAULT_FORMAT", "m4b")
#: Bitrate for the AAC encode when writing M4B.
M4B_BITRATE = os.environ.get("M4B_BITRATE", "64k")
#: Write an .srt transcript alongside the audio when the engine reports timings.
WRITE_TRANSCRIPT = _get_env_bool("WRITE_TRANSCRIPT", False)

##### Structure
#: Headings at or above this level start a new chapter.
CHAPTER_HEADING_LEVEL = _get_env_int("CHAPTER_HEADING_LEVEL", 2)

##### Google engines
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
GEMINI_TTS_MODEL = os.environ.get("GEMINI_TTS_MODEL", "gemini-2.5-flash-preview-tts")
GOOGLE_CLOUD_VOICE = os.environ.get("GOOGLE_CLOUD_VOICE", "en-GB-Neural2-C")

##### mlx-audio (Apple Silicon)
MLX_TTS_MODEL = os.environ.get("MLX_TTS_MODEL", "prince-canuma/Kokoro-82M")
MLX_TTS_VOICE = os.environ.get("MLX_TTS_VOICE", "bf_emma")
MLX_LANG_CODE = os.environ.get("MLX_LANG_CODE", "")  # "" = infer from voice prefix

##### Optional LLM normalization
#: off | local | gemini
NORMALIZER = os.environ.get("NORMALIZER", "off")
#: OpenAI-compatible endpoint for a local server (LM Studio, Ollama, vLLM).
LOCAL_LLM_BASE_URL = os.environ.get("LOCAL_LLM_BASE_URL", "http://localhost:1234/v1")
LOCAL_LLM_MODEL = os.environ.get("LOCAL_LLM_MODEL", "qwen3")
LOCAL_LLM_API_KEY = os.environ.get("LOCAL_LLM_API_KEY", "not-needed")
GEMINI_TEXT_MODEL = os.environ.get("GEMINI_TEXT_MODEL", "gemini-2.5-flash")
#: A normalized chunk may not differ in length from its input by more than this
#: fraction, or it is rejected and the original is used. The guardrail that keeps
#: a hallucinating model from quietly rewriting a book.
NORMALIZER_LENGTH_TOLERANCE = _get_env_float("NORMALIZER_LENGTH_TOLERANCE", 0.25)

LOG_FORMAT = "%(asctime)s.%(msecs)03d %(filename)s (%(levelname)s):\t%(message)s"
LOG_DATE_FORMAT = "%H:%M:%S"

##### REGEXs
EMPTY_LINES = re.compile(r"\n\s*\n")
REDUNDANT_SPACES = re.compile(r" +")
SENTENCES = re.compile(r"(?<=[.!?])\s+")
