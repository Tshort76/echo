from echo.ui.widgets import add_core_widgets
from echo.ui.frame import initialize_frame
import logging
import os
from dotenv import load_dotenv
import echo.constants as c

load_dotenv()

_log_level = logging.WARNING
_verbose = os.environ.get("VERBOSE")
if _verbose and _verbose.lower() == "true":
    _log_level = logging.DEBUG

logging.basicConfig(level=_log_level, format=c.LOG_FORMAT, datefmt=c.LOG_DATE_FORMAT)

root, main_frame = initialize_frame()
add_core_widgets(main_frame)
root.mainloop()
