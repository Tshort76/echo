import argparse
import os
import sys
import time
import json
from pathlib import Path

import google.generativeai as genai
from dotenv import load_dotenv

import echo.core as echo
import echo.clean as cln

load_dotenv()

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
    print(f"Starting deep research on: {prompt_config['name']}")

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

    print("Deep research completed")
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
    filename = f"{time.strftime('%Y%m%d')}_DR_{topic_name}.txt"

    file_path = OUTPUT_DIR / filename
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)

    return file_path


def main():
    parser = argparse.ArgumentParser(description="Deep Research CLI - Research topics with Gemini and convert to audio")
    parser.add_argument("topic_json", type=str, help="Path to meta file for the query")

    args = parser.parse_args()
    with open(args.topic_json, "r") as fp:
        topic_config = json.load(fp)

    try:
        # Setup
        setup_output_directory()
        initialize_gemini()

        raw_response = start_deep_research(topic_config)
        cleaned = cln.simplify_gemini_for_audio(raw_response)
        text_file = _write_to_file(cleaned, topic_config["name"])
        mp3_file = echo.file_to_mp3(
            text_file,
            mp3_meta={"title": topic_config["name"], "author": "Gemini"},
            voice="en-GB-SoniaNeural",
            speed=1.5,
        )
        print(f"Success!  Created audio file: {mp3_file}")

    except Exception as e:
        print(f"Error: {str(e)}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
