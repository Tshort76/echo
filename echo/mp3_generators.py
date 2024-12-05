import logging
import os
import time
from pathlib import Path
import pprint

import edge_tts  # https://github.com/rany2/edge-tts/tree/master
import echo.constants as cn


log = logging.getLogger(__name__)


def text_to_mp3(text: str, mp3_path: str, voice: str, rate: str = cn.DEFAULT_SPEED) -> str:
    """Generate an MP3 audio file from a string of text

    Args:
        text (str): The text to be converted into audio data
        mp3_path (str): file path to which the resulting audio data will be written
        voice (str): voice to use for the dictation (see echo.constants)
        rate (str, optional): playback speed adjustment. Defaults to "+0%".

    Returns:
        str: path of the mp3 file
    """
    t0 = time.time()
    x = edge_tts.Communicate(text, cn.voice_lookups[voice], rate=rate)
    x.save_sync(mp3_path)
    t1 = time.time()
    log.debug(
        pprint.pformat(
            {
                "mp3_path": mp3_path,
                "voice": voice,
                "rate": rate,
                "mp3_size": f"{os.path.getsize(mp3_path) / 1e6:.3f} MB",
                "cpu_time": f"{(t1 - t0)/60:.2f} minutes",
            }
        )
    )
    return mp3_path


def file_to_mp3(file_path: str, voice: str, output_dir: str = None) -> str:
    """Generate an audio file from a text file

    Args:
        file_path (str): path to text file
        voice (str): Voice for the narrator
        output_dir (str, optional): output directory for the audio file. Defaults to None.

    Returns:
        str: File path of the resulting audio file
    """
    p = Path(file_path)
    mp3_path = p.name.replace(p.suffix, ".mp3")
    if output_dir:
        mp3_path = os.path.join(output_dir, mp3_path)
    with open(p, mode="r", encoding="utf-8") as fp:
        text_to_mp3(fp.read(), mp3_path, voice=voice)
    return mp3_path
