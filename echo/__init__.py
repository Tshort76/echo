"""echo — text to chaptered speech.

    from echo import speak_chapters, Chapter

    result = speak_chapters(
        [Chapter("Opening", text), Chapter("Europe", more_text)],
        "digest.mp3",
        title="The weekly digest",
        engine="edge",
        voice="en-GB-RyanNeural",
    )
    result.chapters  # [ChapterMark(title, start_ms, end_ms), ...]

Everything importable from here is the public API, versioned by ``__version__``
under semver: a breaking change to any name in ``__all__`` bumps the major
version (the minor version while below 1.0). Submodules are internal.

Importing echo reads no configuration file and changes nothing in
``os.environ``. Engines read their own credentials from the environment
(``GEMINI_API_KEY``, Google ADC) when first used, never at import.
"""

import logging

from echo.audio.assemble import ChapterMark
from echo.audio.engines import SpeechEngine, VoiceInfo, available_engines, engine_names, get_engine
from echo.errors import AssemblyError, EchoError, EngineUnavailable, SynthesisError
from echo.script import Script, ScriptChapter, Utterance
from echo.speech import (
    Chapter,
    SpeechResult,
    aspeak_chapters,
    aspeak_script,
    speak_chapters,
    speak_script,
)
from echo.text import split_text

__version__ = "0.3.2"

__all__ = [
    "AssemblyError",
    "Chapter",
    "ChapterMark",
    "EchoError",
    "EngineUnavailable",
    "Script",
    "ScriptChapter",
    "SpeechEngine",
    "SpeechResult",
    "SynthesisError",
    "Utterance",
    "VoiceInfo",
    "__version__",
    "aspeak_chapters",
    "aspeak_script",
    "available_engines",
    "engine_names",
    "get_engine",
    "speak_chapters",
    "speak_script",
    "split_text",
]

# A library logs; it never configures logging. Without a handler of its own,
# Python's last-resort handler would print warnings to stderr.
logging.getLogger(__name__).addHandler(logging.NullHandler())
