import logging
import os
from dotenv import load_dotenv
import echo.constants as cn
import echo.core as c
import echo.mp3z as mp3z

load_dotenv()

_log_level = logging.WARNING
_verbose = os.environ.get("VERBOSE")
if _verbose and _verbose.lower() == "true":
    _log_level = logging.DEBUG

logging.basicConfig(level=_log_level, format=cn.LOG_FORMAT, datefmt=cn.LOG_DATE_FORMAT)

output_path = mp3z.file_to_mp3("resources/daily_listen.txt", voice="Sonia_GB")

if output_path:
    c.open_parent_dir(output_path)
