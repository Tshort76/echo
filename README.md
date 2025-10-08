# echo
Utilities to convert text based files into audio files using the Edge Text To Speech server

# Installation
## For ijupyter usage
```bash
$ python -m venv .venv     
$ ./.venv/Scripts/Activate.ps1                                                           
(.venv) $ pip install -r requirements.txt
```

## To handle scanned (image) pdfs
### Install Poppler for pdf2image
[pdf2image](https://github.com/Belval/pdf2image) requires the `poppler` library, which Windows users will have to build or download. [@oschwartz10612](https://github.com/oschwartz10612/poppler-windows/releases/) has a version which is the most up-to-date. You will then have to add the `bin/` folder to PATH or use `poppler_path = "C:\path\to\poppler-xx\bin"` as an argument in `pdf2image.convert_from_path`.

### Install Tesseract
`winget install --id=UB-Mannheim.TesseractOCR -e`
Add the binaries directory, typically `C:\Program Files\Tesseract-OCR`, to your PATH variable

## Example .env file
```
DEFAULT_VOICE="en-GB-SoniaNeural"
VERBOSE=True
DEFAULT_SPEED="1.1"
POPPLER_PATH="C:/Program Files/poppler-24.08.0/Library/bin"
```

# Usage
Assuming that you have activated your `venv` and your working directory is the project's root directory ...

## Run with CLI interface
`python create_audio.py my_little_pony.txt`
`python create_audio.py my_little_pony.txt -o my_little_pony.mp3 -v Eric_US -s 1.75`
`python create_audio.py my_little_pony.txt --meta '{"author": "An Author", "image_path": "pony.jpg", "title": "A Great Book"}'`

## Choosing a voice ... that speaks to you ;)
```python
import echo.core as core
import echo.audio.voices as vc

# query edge-tts server for available voices
voices = await vc.find_voices(use_cache=False)
# -> ['af-ZA-AdriNeural,af,ZA,Female,"Friendly,Positive"',
#     'af-ZA-WillemNeural,af,ZA,Male,"Friendly,Positive"',
#     'am-ET-AmehaNeural,am,ET,Male,"Friendly,Positive"', ...]

# update voices cache file (resources/voices.csv)
await vc.update_voice_cache_file()

# Find all female, English voices with a Great British accent
await vc.find_voices(lang="en", gender="Female", tag="GB")
# ['en-GB-LibbyNeural,en,GB,Female,"Friendly,Positive"',
#  'en-GB-MaisieNeural,en,GB,Female,"Friendly,Positive"',
#  'en-GB-SoniaNeural,en,GB,Female,"Friendly,Positive"']

# to generate and play a 10 second sample recording
core.play_mp3_clip("en-GB-SoniaNeural", speed=1)
```

## Convert a pdf, epub, or text file to an MP3
```python
import echo.core as core

mp3_meta = {
    "author": "An Author",
    "image_path": "resources/images/singapore.jpg",
    "title": "A Great Book",
}


core.file_to_mp3(
    "resources/your_book.pdf", # or .txt or .epub file
    mp3_meta=mp3_meta,
    voice="en-GB-SoniaNeural",
    speed=1.5
)
# -> resources/your_book.mp3
```

## Extract text data

### Strip out Gutenberg pre and post amble
```python
import echo.extractors.text as t
from pathlib import Path

input_path = Path(f"abridged_virgil_from_gutenberg.txt")

with open(input_path, "r", encoding="utf-8") as fp:
    bloated_text = fp.read()

if t.is_gutenberg_text(bloated_text):
    text = t.strip_gutenberg_bloat(bloated_text)
```

### PDF to text file
```python
import echo.extractors.pdfs as p

p.extract_page_contents("samples/cybernetics_one_page.pdf", first_page=30, last_page=30, content_types=["text"])
# -> ['Note: As a reminder ...', 'The approach of ...', 'oppose this ominous...']
```

### EPUB to text file
```python
import echo.extractors.misc as m

m.extract_epub_text("samples/critique_pure_reason-kant.epub")
# -> '\n\n\nThe Project ...'
```
### Text to mp3
```python
import echo.core as core

mp3_file = core.text_to_mp3("Hello friend, you look excellent today!", "affirmation.mp3", voice="en-GB-SoniaNeural")
# -> affirmation.mp3
```