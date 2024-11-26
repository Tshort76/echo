# echo
Utilities to convert text based files into audio files using the Edge Text To Speech server

# Installation
## For ijupyter usage
```bash
$ python -m venv .venv     
$ ./.venv/Scripts/Activate.ps1                                                           
(.venv) $ pip install -r requirements.txt
```

## Tkinter UI
This project includes a Tkinter-based UI for user convenience.  To use it, you will need to have a complete Python installation on your machine, including the tk/tcl packages.
To check this, you can run `python -m tkinter` and if a little UI window pops up, you are in good shape.  If you get an error ... the internet is your friend!  I had an error with running from the within a venv environment, but copying the `tcl/tcl8.6` and `tcl/tk8.6` folders into the `Lib` folder (all within the Python installation folder) fixed my issues. My Python installation folder was located at `C:\Users\<name>\AppData\Local\Programs\Python\Python313`.

## Example .env file
```
DEFAULT_VOICE="Asilia_KE"
DEFAULT_PROCESS="text_to_mp3"
OUTPUT_DIRECTORY="resources/outputs"
VERBOSE=False
```

# Usage
Assuming that you have activated your `venv` and your working directory is the project's root directory ...

## UI
Start the UI with:
`python app.py`

### Sample the voice options
- Set `Process` to `sample_voice`
- Choose your `Voice`
- Hit `Generate`

### Generate MP3 Files
- Use `<Input File>` File Picker to select your input data (text or pdf)
- Set your `Process` (basically `<input_format>_to_<output_format>`)
- If generating an MP3 file, you can specify the album front cover by selecting your desired image file with the `<MP3 Icon>` File Picker
- Choose a `Voice`
- If you are converting a pdf to text, you can specify a page range
- Hit `Generate`

## More Granular functionality
### Strip out Gutenberg pre and post amble
```python
import echo.extractors.bloated_text as g
g.extract_gutenberg_data("samples/abridged_virgil_from_gutenberg.txt")
# -> {'title': 'The Bucolics and Eclogues',  'author': 'Virgil', 'contents': '37 BC\n\nTHE ECLOGUES ...' 
```

### PDF to text file
```python
import echo.extractors.pdf_utils as p

p.extract_pdf_pages("samples/america_against_america_3pages.pdf")
# -> ['Note: As a reminder ...', 'The approach of ...', 'oppose this ominous...']
```
### EPUB to text file
```python
import echo.extractors.html_like as h

h.extract_epub_text("samples/critique_pure_reason-kant.epub")
# -> ['\n\n\nThe Project ...', '\n\n\nThe Project ...', ...]
```
### Text to mp3
```python
import echo.mp3_generators as t
import echo.mp3_utils as mp

mp3_file = t.text_to_mp3("Hello friend, you look excellent today!", "affirmation.mp3", voice="Sonia_GB")
mp.add_front_cover(mp3_file, "samples/cow.jpg") # https://cyfairanimalhospital.com/cows/cow-facts/
# Creates affirmation.mp3 file in project root

# or create from a text file
mp3_file = file_to_mp3("samples/sample.txt", voice="Sonia_GB")
```