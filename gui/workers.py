"""Background worker threads for long-running backend operations.

Everything in the ``echo`` pipeline is blocking (and synthesis spins up its own
asyncio loop), so it must run off the Qt main thread to keep the UI responsive.
Each worker is a ``QThread`` that:

* installs a temporary logging handler to forward backend log lines to the UI,
* parses the backend's ``"Progress Report: NN%"`` log messages into a progress
  signal (no backend changes required), and
* reports success/failure via Qt signals, which are delivered safely to the main
  thread.
"""

from __future__ import annotations

import logging
import re
import traceback
from pathlib import Path

from PySide6.QtCore import QThread, Signal

import echo.core as core

_PROGRESS_RE = re.compile(r"Progress Report:\s*(\d+)\s*%")

# Loggers whose output we surface in the UI while a job runs.
_CAPTURED_LOGGERS = ("echo", "__main__")


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
            for lg, prior in touched:
                lg.removeHandler(handler)
                lg.setLevel(prior)


class ConversionWorker(_BaseWorker):
    """Runs the full document-to-audiobook pipeline for the Convert view."""

    def __init__(
        self,
        file_path: str,
        output_path: str,
        voice: str,
        speed: float,
        meta: dict,
        save_text: bool,
        parser_configs: dict,
        engine: str = None,
        fmt: str = None,
        normalizer: str = None,
        write_transcript: bool = False,
        resume: bool = True,
        log_level: int = logging.INFO,
        parent=None,
    ):
        super().__init__(parent)
        self._level = log_level
        self._args = dict(
            file_path=file_path,
            output_path=output_path,
            mp3_meta=meta,
            voice=voice,
            speed=speed,
            engine=engine,
            fmt=fmt,
            normalizer=normalizer,
            write_text_file=save_text,
            write_transcript=write_transcript,
            resume=resume,
            parser_configs=parser_configs,
        )

    def run(self) -> None:
        self._run_captured(lambda: core.file_to_audio(**self._args))


class GutenbergSearchWorker(QThread):
    """Searches the Project Gutenberg catalogue off the main thread.

    Not a ``_BaseWorker``: its result is a list of catalogue records rather than a
    path, and it has no progress to report.
    """

    results = Signal(list)  # list[GutenbergBook]
    failed = Signal(str)

    def __init__(self, title: str, author: str = "", language: str = "en", parent=None):
        super().__init__(parent)
        self._title = title
        self._author = author
        self._language = language

    def run(self) -> None:
        try:
            import echo.gutenberg as gutenberg

            self.results.emit(
                gutenberg.search(self._title, self._author or None, language=self._language)
            )
        except Exception as exc:
            self.failed.emit(str(exc) or exc.__class__.__name__)


class GutenbergDownloadWorker(QThread):
    """Downloads a chosen book (and its cover art) off the main thread."""

    downloaded = Signal(object)  # DownloadedBook
    message = Signal(str)
    failed = Signal(str)

    def __init__(self, book, prefer: str = "epub", parent=None):
        super().__init__(parent)
        self._book = book
        self._prefer = prefer

    def run(self) -> None:
        handler = _SignalLogHandler(self.message.emit, lambda _pct: None, logging.INFO)
        logger = logging.getLogger("echo.gutenberg")
        prior = logger.level
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)
        try:
            import echo.gutenberg as gutenberg

            self.downloaded.emit(gutenberg.download(self._book, prefer=self._prefer))
        except Exception as exc:
            self.failed.emit(str(exc) or exc.__class__.__name__)
        finally:
            logger.removeHandler(handler)
            logger.setLevel(prior)


class ResearchWorker(QThread):
    """Runs a Gemini Deep Research job off the main thread.

    A run takes 2–15 minutes, so this reports progress as it goes rather than
    leaving the dialog on a spinner, and supports cancelling.
    """

    finished_ok = Signal(object)  # ResearchResult
    message = Signal(str)
    failed = Signal(str)

    def __init__(self, topic: str, name: str, agent: str, keep: bool, parent=None):
        super().__init__(parent)
        self._topic = topic
        self._name = name
        self._agent = agent
        self._keep = keep
        self._researcher = None
        self._cancelled = False

    def run(self) -> None:
        try:
            import echo.constants as ec
            from echo.research import DeepResearcher

            self._researcher = DeepResearcher()
            result = self._researcher.run(
                self._topic,
                self._name,
                agent=self._agent,
                keep_dir=ec.RESEARCH_DIR if self._keep else None,
                on_progress=self.message.emit,
            )
            if self._cancelled:
                return
            self.finished_ok.emit(result)
        except Exception as exc:
            if not self._cancelled:
                self.failed.emit(str(exc) or exc.__class__.__name__)

    def cancel(self) -> None:
        """Stop reporting, and shorten the deadline so the poll loop gives up.

        The interaction itself is cancelled server-side by ``DeepResearcher`` when its
        timeout trips, so a cancelled job is not left running and billed.
        """
        self._cancelled = True
        if self._researcher is not None:
            self._researcher.timeout_seconds = 0.0


class PreviewWorker(_BaseWorker):
    """Synthesizes a short spoken sample for a voice and opens it in the OS player.

    The work itself lives in ``core.preview_voice`` — this only moves it off the UI
    thread. It used to carry its own copy, with different sample text and its own
    temp-file naming.
    """

    def __init__(self, voice: str, speed: float, engine: str = None, parent=None):
        super().__init__(parent)
        self._voice = voice
        self._speed = speed
        self._engine = engine

    def run(self) -> None:
        self._run_captured(self._make_and_open)

    def _make_and_open(self) -> str:
        return str(core.preview_voice(self._voice, self._speed, engine=self._engine))


def open_in_default_app(path: Path) -> None:
    """Open ``path`` with the platform's default application, cross-platform."""
    core.open_in_default_app(path)
