from pathlib import Path
import edge_tts
import echo.constants as ec


async def _request_voices() -> dict[str, list[str]]:
    voices = await edge_tts.list_voices()
    voices = sorted(voices, key=lambda voice: voice["ShortName"])

    voice_strs = []
    for v in voices:
        fields = [v["ShortName"]] + v["ShortName"].split("-")[:2] + [v["Gender"]]
        voice_strs.append(",".join(fields) + ',"' + ",".join(v["VoiceTag"]["VoicePersonalities"]) + '"')
    return voice_strs


async def update_voice_cache_file():
    voices = await _request_voices()
    with open(ec.VOICE_CACHE_FILE, "w") as fp:
        s = ""
        for v in voices:
            s += v + "\n"
        fp.write(s)


async def find_voices(lang: str = None, gender: str = None, tag: str = None, use_cache: bool = True) -> list[str]:
    """Find available edge-tts voices that match the search criteria

    Args:
        lang (str, optional): filter by language ('en', 'es', 'fr'). Defaults to None.
        gender (str, optional): filter by gender ('Male', 'Female'). Defaults to None.
        tag (str, optional): filter by tag/description. Defaults to None.
        use_cache (bool, optional): Pull from voices.csv cache file. Defaults to True.

    Returns:
        list[str]: voice descriptions in csv form of "name,language,locale,gender,tags"
    """
    if use_cache and Path(ec.VOICE_CACHE_FILE).exists():
        with open(ec.VOICE_CACHE_FILE, "r") as fp:
            voices = [l.strip() for l in fp.readlines()]
    else:
        voices = await _request_voices()

    if lang:
        _filter = lambda v: "," + lang + "," in v
        voices = filter(_filter, voices)
    if gender:
        _filter = lambda v: "," + gender + "," in v
        voices = filter(_filter, voices)
    if tag:
        _filter = lambda v: tag in v
        voices = filter(_filter, voices)

    return list(voices)
