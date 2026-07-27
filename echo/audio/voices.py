"""Voice discovery.

Cross-engine listing lives in :mod:`echo.audio.engines`; what remains here is the
edge-tts voice cache — ``resources/voices.csv``, which ships with the app so the
GUI can populate its dropdown without a network round trip.
"""

from __future__ import annotations

import logging
from pathlib import Path

import echo.constants as ec

log = logging.getLogger(__name__)


async def _request_voices() -> list[str]:
    """Ask the Edge service for its current voices, in the cache's CSV shape."""
    from echo.audio.engines.edge import list_live_voices

    voices = sorted(await list_live_voices(), key=lambda voice: voice["ShortName"])
    rows = []
    for v in voices:
        fields = [v["ShortName"]] + v["ShortName"].split("-")[:2] + [v["Gender"]]
        personalities = ",".join(v.get("VoiceTag", {}).get("VoicePersonalities", []))
        rows.append(",".join(fields) + ',"' + personalities + '"')
    return rows


async def update_voice_cache_file(path: str | Path = None) -> Path:
    """Refresh ``resources/voices.csv`` from the live Edge voice list."""
    path = Path(path or ec.VOICE_CACHE_FILE)
    rows = await _request_voices()
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    log.info(f"Wrote {len(rows)} voices to {path}")
    return path


async def find_voices(
    lang: str = None,
    gender: str = None,
    tag: str = None,
    use_cache: bool = True,
) -> list[str]:
    """Find edge-tts voices matching the given criteria.

    Args:
        lang: language code filter ('en', 'es', 'fr').
        gender: 'Male' or 'Female'.
        tag: substring match against the personality tags or locale.
        use_cache: read ``resources/voices.csv`` instead of calling the service.

    Returns:
        Voice descriptions as "name,language,locale,gender,tags".
    """
    cache = Path(ec.VOICE_CACHE_FILE)
    if use_cache and cache.exists():
        voices = [line.strip() for line in cache.read_text(encoding="utf-8").splitlines() if line.strip()]
    else:
        voices = await _request_voices()

    if lang:
        voices = [v for v in voices if f",{lang}," in v]
    if gender:
        voices = [v for v in voices if f",{gender}," in v]
    if tag:
        voices = [v for v in voices if tag in v]
    return voices
