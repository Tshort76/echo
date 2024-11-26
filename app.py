from echo.ui.widgets import add_core_widgets
from echo.ui.frame import initialize_frame
import logging
import os
from dotenv import load_dotenv

load_dotenv()

_verbose = os.environ.get("VERBOSE")
if _verbose and _verbose.lower() == "true":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s", datefmt="%H:%M:%S")

root, main_frame = initialize_frame()
add_core_widgets(main_frame)
root.mainloop()


import echo.extractors.html_like as h

h.extract_epub_texts("samples/critique_pure_reason-kant.epub")
