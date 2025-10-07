import asyncio
import logging
import time
from pathlib import Path

import edge_tts  # https://github.com/rany2/edge-tts/tree/master

import echo.constants as ec
import echo.audio.mp3_utils as mp3

log = logging.getLogger(__name__)


async def _convert_chunk_to_audio(text: str, voice: str, rate: str, output_path: str):
    communicate = edge_tts.Communicate(text, voice, rate=rate)
    await communicate.save(output_path)


def _speed_as_rate(speed: float) -> str:
    "Convert a multiplier fraction such as 1.5 to the edge-tts equivalent of '(+|-)XX%'"
    assert speed >= 0.25 and speed < 5, "Rate cannot be less than 0.25x or greater than 5x"
    if speed < 1:
        return f"-{(round((1-speed)*100))}%"
    return f"+{(round((speed-1)*100))}%"


def is_in_ipython_env():
    try:
        in_ipython = __IPYTHON__ is not None
        if in_ipython:
            log.warning("In an Ipython environment, will make a synchronous TTS call")
        return in_ipython
    except NameError:
        return False


def to_chunks(text: str, max_chars: int = ec.CHUNK_SIZE) -> list[str]:
    # Remove excessive whitespace
    ec.EMPTY_LINES.sub("\n\n", text)
    ec.REDUNDANT_SPACES.sub(" ", text)

    chunks = []
    current_chunk = ""

    # Split by paragraphs first
    paragraphs = text.split("\n\n")

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        # If adding this paragraph exceeds max_chars, process current chunk
        if len(current_chunk) + len(para) + 2 > max_chars and current_chunk:
            chunks.append(current_chunk.strip())
            current_chunk = ""

        # If a single paragraph is too long, split by sentences
        if len(para) > max_chars:
            sentences = ec.SENTENCES.split(para)
            for sentence in sentences:
                if len(current_chunk) + len(sentence) + 1 > max_chars and current_chunk:
                    chunks.append(current_chunk.strip())
                    current_chunk = ""
                current_chunk += sentence + " "
        else:
            current_chunk += para + "\n\n"

    # Add the last chunk
    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    return chunks


async def _distributed_text_to_mp3(text: str, output_file: str, voice: str, rate: str):

    log.info(f"Performing Text to Speech with up to {ec.MAX_THREADS} concurrent threads")
    total_chars = len(text)
    chunks = to_chunks(text)
    log.info(f"Split text into {len(chunks)} chunks")

    output_path = Path(output_file)
    chunks_dir = output_path.parent / f"{output_path.stem}_chunks"
    chunks_dir.mkdir(exist_ok=True)

    audio_files = [None] * len(chunks)
    chars_processed = 0
    semaphore = asyncio.Semaphore(ec.MAX_THREADS)

    async def _process_chunk(i: int, chunk: str):
        nonlocal chars_processed
        async with semaphore:
            chunk_file = chunks_dir / f"chunk_{i:04d}.mp3"
            await _convert_chunk_to_audio(chunk, voice, rate, str(chunk_file))
            audio_files[i] = str(chunk_file)

            chars_processed += len(chunk)
            log.debug(f"{(chars_processed / total_chars):.0%} complete")

    tasks = [_process_chunk(i, chunk) for i, chunk in enumerate(chunks)]
    await asyncio.gather(*tasks)

    log.info(f"All chunks processed, creating final mp3 file at {output_path}")
    mp3.merge_audio_files(chunks_dir, output_path)


async def _text_to_mp3_async(text: str, mp3_path: str, tts_voice: str, rate: str):
    await _distributed_text_to_mp3(text, mp3_path, tts_voice, rate)


def _text_to_mp3_sync(text: str, mp3_path: str, tts_voice: str, rate: str):
    log.info(f"Using a single TTS batch request for {mp3_path}")
    x = edge_tts.Communicate(text, tts_voice, rate=rate)
    x.save_sync(mp3_path)


def text_to_mp3(text: str, mp3_path: str, voice: str = "Sonia_GB", speed: float = 1):
    """Leverages a TTS engine (i.e. Edge-tts) to generate an MP3 audio file for text

    Args:
        text (str): The text to be converted into audio data
        mp3_path (str): file path to which the resulting audio data will be written
        voice (str): voice to use for the dictation (see echo.constants)
        speed (float, optional): playback speed adjustment multiplier. Defaults to "1".

    """
    t0 = time.perf_counter()
    voice_id = ec.voice_lookups.get(voice, voice)
    rate = _speed_as_rate(speed)
    log.info(f"Running Text to Speech with parameters:\nmp3_path: {mp3_path}\nvoice: {voice_id} , rate: {rate}")
    if len(text) < ec.CHUNK_SIZE or is_in_ipython_env():
        _text_to_mp3_sync(text, mp3_path, voice_id, rate)
    else:
        return asyncio.run(_text_to_mp3_async(text, mp3_path, voice_id, rate))

    t1 = time.perf_counter()
    log.info(f"{mp3_path} created in {(t1 - t0)/60:.2f} minutes")
