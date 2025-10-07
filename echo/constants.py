import os
from dotenv import load_dotenv
import re

load_dotenv()


def _get_env_number(env_key: str, default_: int) -> int:
    try:
        if s := os.environ.get(env_key):
            cleaned_s = s.strip()
            return int(cleaned_s)
    except ValueError:
        pass
    return default_


VOICE_CACHE_FILE = "resources/voices.csv"
OUTPUT_FOLDER = os.environ.get("DEFAULT_OUTPUT_FOLDER", "")
DEFAULT_VOICE = os.environ.get("DEFAULT_VOICE", "en-GB-SoniaNeural")
DEFAULT_SPEED = _get_env_number("DEFAULT_SPEED", 1.25)
CHUNK_SIZE = _get_env_number("DEFAULT_CHUNK_SIZE", 8000)  # characters
MAX_THREADS = _get_env_number("DEFAULT_MAX_THREADS", 4)
LOG_FORMAT = "%(asctime)s.%(msecs)03d %(filename)s (%(levelname)s):\t%(message)s"
LOG_DATE_FORMAT = "%H:%M:%S"

##### REGEXs
EMPTY_LINES = re.compile(r"\n\s*\n")
REDUNDANT_SPACES = re.compile(r" +")
SENTENCES = re.compile(r"(?<=[.!?])\s+")
