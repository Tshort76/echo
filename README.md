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
DEFAULT_VOICE="Sonia_GB"
VERBOSE=True
DEFAULT_SPEED="1.1"
POPPLER_PATH="C:/Program Files/poppler-24.08.0/Library/bin"
```

# Usage
Assuming that you have activated your `venv` and your working directory is the project's root directory ...

## Run with CLI interface
`python create_audio.py my_little_pony.txt --voice Sonia_GB --speed 1.2`

## Choose a voice
```python
import echo.constants as c
import echo.core as core
import pprint

# to see the list of voices
pprint([x for x in c.voice_lookups])

# to generate a 10 second sample recording
playback_speed = 1
core.play_mp3_clip("Steffan_US", speed=playback_speed)
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
    voice="Sonia_GB",
    speed=1.5
)
# -> resources/your_book.mp3
```

## Extract text data

### Strip out Gutenberg pre and post amble
```python
import echo.extractors.text as t
t.extract_gutenberg_data("samples/abridged_virgil_from_gutenberg.txt")
# -> {'title': 'The Bucolics and Eclogues',  'author': 'Virgil', 'contents': '37 BC\n\nTHE ECLOGUES ...' 
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
# -> ['\n\n\nThe Project ...', '\n\n\nThe Project ...', ...]
```
### Text to mp3
```python
import echo.core as core

mp3_file = core.text_to_mp3("Hello friend, you look excellent today!", "affirmation.mp3", voice="Sonia_GB")
# -> affirmation.mp3
```