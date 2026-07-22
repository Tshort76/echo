"""Background worker threads for long-running backend operations.

Everything in the ``echo`` pipeline is blocking (and TTS spins up its own asyncio
loop), so it must run off the Qt main thread to keep the UI responsive. Each
worker is a ``QThread`` that:

* installs a temporary logging handler to forward backend log lines to the UI,
* parses the backend's ``"Progress Report: NN%"`` log messages into a progress
  signal (no backend changes required), and
* reports success/failure via Qt signals, which are delivered safely to the main
  thread.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
import traceback
from pathlib import Path

from PySide6.QtCore import QThread, Signal

import echo.core as core
import echo.clean as cln
import deep_research_cli as dr

_REPO_ROOT = Path(__file__).resolve().parent.parent
_PROGRESS_RE = re.compile(r"Progress Report:\s*(\d+)\s*%")

# Loggers whose output we surface in the UI while a job runs.
_CAPTURED_LOGGERS = ("echo", "deep_research_cli", "__main__")


class _SignalLogHandler(logging.Handler):
    """Routes backend log records to a worker's Qt signals.

    Runs in the worker thread; the signals it emits are queued to the main
    thread automatically by Qt, so this is safe.
    """

    def __init__(self, on_message, on_progress, level=logging.INFO):
        super().__init__(level=level)
        self._on_message = on_message
        self._on_progress = on_progress
        self.setFormatter(logging.Formatter("%(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            match = _PROGRESS_RE.search(msg)
            if match:
                self._on_progress(int(match.group(1)))
            self._on_message(msg)
        except Exception:  # never let logging break the job
            pass


class _BaseWorker(QThread):
    """Shared plumbing: log capture + uniform result signals."""

    progress = Signal(int)  # 0-100
    message = Signal(str)  # a line of backend log output
    succeeded = Signal(str)  # path to the produced file
    failed = Signal(str)  # human-readable error text

    # Verbosity of the captured backend logs; subclasses may override per-run.
    _level = logging.INFO

    def _run_captured(self, work) -> None:
        """Run ``work()`` with backend logging piped into ``self`` signals."""
        level = self._level
        handler = _SignalLogHandler(self.message.emit, self.progress.emit, level)
        touched = []
        for name in _CAPTURED_LOGGERS:
            lg = logging.getLogger(name)
            # Remember prior level so we can restore it, then apply the chosen
            # verbosity (e.g. ERROR shows only errors, DEBUG shows everything).
            touched.append((lg, lg.level))
            lg.setLevel(level)
            lg.addHandler(handler)
        try:
            result = work()
            self.succeeded.emit(str(result))
        except Exception as exc:
            self.message.emit(traceback.format_exc())
            self.failed.emit(str(exc) or exc.__class__.__name__)
        finally:
            for lg, level in touched:
                lg.removeHandler(handler)
                lg.setLevel(level)


class ConversionWorker(_BaseWorker):
    """Runs ``core.file_to_mp3`` for the Convert File tab."""

    def __init__(
        self,
        file_path: str,
        output_path: str,
        voice: str,
        speed: float,
        meta: dict,
        save_text: bool,
        parser_configs: dict,
        log_level: int = logging.INFO,
        parent=None,
    ):
        super().__init__(parent)
        self._level = log_level
        self._args = dict(
            file_path=file_path,
            mp3_path=output_path,
            mp3_meta=meta,
            voice=voice,
            speed=speed,
            write_text_file=save_text,
            parser_configs=parser_configs,
        )

    def run(self) -> None:
        self._run_captured(lambda: core.file_to_mp3(**self._args))


class DeepResearchWorker(_BaseWorker):
    """Runs the Gemini Deep Research → clean → audio pipeline.

    ``mode`` is either ``"topic"`` (call Gemini for a topic) or ``"text"``
    (convert an existing research .txt file).
    """

    def __init__(
        self,
        mode: str,
        name: str,
        topic: str,
        text_path: str,
        voice: str,
        speed: float,
        parent=None,
    ):
        super().__init__(parent)
        self._mode = mode
        self._name = name
        self._topic = topic
        self._text_path = text_path
        self._voice = voice
        self._speed = speed
        self._out_dir = _REPO_ROOT / "resources" / "outputs" / "geminiDR"

    def run(self) -> None:
        self._run_captured(self._pipeline)

    def _pipeline(self) -> str:
        log = logging.getLogger("deep_research_cli")
        self._out_dir.mkdir(parents=True, exist_ok=True)

        if self._mode == "topic":
            dr.initialize_gemini()
            raw = dr.start_deep_research({"name": self._name, "topic": self._topic})
            (self._out_dir / f"raw_{self._name}.txt").write_text(raw, encoding="utf-8")
        else:
            raw = Path(self._text_path).read_text(encoding="utf-8")

        log.info("Formatting research output")
        cleaned = cln.clean_gemini_contents(raw)
        text_file = self._out_dir / f"{self._name}.txt"
        text_file.write_text(cleaned, encoding="utf-8")

        mp3_file = core.file_to_mp3(
            str(text_file),
            mp3_meta={"title": self._name, "author": "Gemini"},
            voice=self._voice,
            speed=self._speed,
        )
        return str(mp3_file)


class PreviewWorker(_BaseWorker):
    """Synthesizes a short spoken sample for a voice and opens it in the OS player."""

    _SAMPLE = (
        "Hello! This is a short preview of how this voice sounds "
        "at the selected speed. Thank you for listening."
    )

    def __init__(self, voice: str, speed: float, parent=None):
        super().__init__(parent)
        self._voice = voice
        self._speed = speed

    def run(self) -> None:
        self._run_captured(self._make_and_open)

    def _make_and_open(self) -> str:
        import tempfile

        import echo.audio.tts as tts

        tmp = Path(tempfile.gettempdir()) / f"echo_preview_{abs(hash(self._voice))}.mp3"
        tts.text_to_mp3(self._SAMPLE, str(tmp), voice=self._voice, speed=self._speed)
        open_in_default_app(tmp)
        return str(tmp)


def open_in_default_app(path: Path) -> None:
    """Open ``path`` with the platform's default application, cross-platform."""
    path = str(path)
    if sys.platform.startswith("darwin"):
        subprocess.run(["open", path], check=False)
    elif os.name == "nt":
        os.startfile(path)  # type: ignore[attr-defined]  # Windows only
    else:
        subprocess.run(["xdg-open", path], check=False)
