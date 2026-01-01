import argparse
import os
import sys
import time
import json
from pathlib import Path
import logging

import google.generativeai as genai
from dotenv import load_dotenv

import echo.core as echo
import echo.clean as cln
import echo.constants as ec

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format=ec.LOG_FORMAT,
    datefmt=ec.LOG_DATE_FORMAT,
    stream=sys.stdout,
)

log = logging.getLogger(__name__)

# Configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
OUTPUT_DIR = Path("resources\\outputs\\geminiDR")
PREAMBLE_KEYWORDS = ["i'll conduct", "i'll search", "researching", "gathering information"]
CONCLUSION_KEYWORDS = ["in conclusion", "summary", "here's what i found", "based on my research"]


def setup_output_directory():
    OUTPUT_DIR.mkdir(exist_ok=True)


def initialize_gemini():
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY environment variable not set")
    genai.configure(api_key=GEMINI_API_KEY)


def start_deep_research(prompt_config: dict) -> str:
    log.info(f"Starting deep research on: {prompt_config['name']}")

    prompt = f"""Conduct a comprehensive deep research on the following topic:
    {prompt_config['topic']}
    Please provide detailed, well-researched information on this topic. Include relevant data, sources, and thorough analysis.
    All sources should be listed under a heading with the name 'SOURCES', which should appear at the bottom of the response."""

    model = genai.GenerativeModel("gemini-2.0-flash-exp")
    response = model.generate_content(prompt, stream=True)

    # Collect the full response
    full_text = ""
    for chunk in response:
        if chunk.text:
            full_text += chunk.text

    log.info("Deep research completed")
    return full_text


def strip_preamble_and_conclusion(text: str) -> str:
    """Remove generic preamble and conclusion from the response."""
    lines = text.split("\n")
    filtered_lines = []
    skip_mode = False

    for i, line in enumerate(lines):
        lower_line = line.lower().strip()

        # Skip initial preamble lines
        if i < 3 and any(keyword in lower_line for keyword in PREAMBLE_KEYWORDS):
            continue

        # Detect conclusion and skip from there onward
        if any(keyword in lower_line for keyword in CONCLUSION_KEYWORDS):
            skip_mode = True
            continue

        if not skip_mode and line.strip():
            filtered_lines.append(line)

    # Remove leading and trailing empty lines
    while filtered_lines and not filtered_lines[0].strip():
        filtered_lines.pop(0)
    while filtered_lines and not filtered_lines[-1].strip():
        filtered_lines.pop()

    return "\n".join(filtered_lines)


def _write_to_file(content: str, topic_name: str = None) -> Path:
    _prefix = "" if topic_name.startswith("20") else f"{time.strftime('%Y%m%d')}_DR_"
    filename = f"{_prefix}{topic_name}.txt"

    file_path = OUTPUT_DIR / filename
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)

    return file_path


def main():
    parser = argparse.ArgumentParser(description="Deep Research CLI - Research topics with Gemini and convert to audio")
    parser.add_argument("file_path", type=str, help="Path to meta file for the query")

    args = parser.parse_args()
    fpath = Path(args.file_path)
    topic_config, raw_response = None, None
    with open(fpath, "r") as fp:
        if fpath.suffix == ".txt":
            log.debug("Txt file found, converting to MP3")
            raw_response = fp.read()
            _name = fpath.with_suffix("").name
        else:
            topic_config = json.load(fp)
            _name = topic_config["name"]

    # Setup
    setup_output_directory()

    if topic_config:
        log.debug("Deep Research Config found, calling gemini")
        initialize_gemini()
        raw_response = start_deep_research(topic_config)
        _ = _write_to_file(raw_response, "raw_" + _name)

    log.debug("Formatting gemini output")
    cleaned = cln.clean_gemini_contents(raw_response)
    log.debug("Writing formatted output to file")
    text_file = _write_to_file(cleaned, _name)
    mp3_file = echo.file_to_mp3(
        text_file,
        mp3_meta={"title": _name, "author": "Gemini"},
        voice="en-GB-SoniaNeural",
        speed=1.5,
    )
    log.info(f"Success!  Created audio file: {mp3_file}")


if __name__ == "__main__":
    main()
