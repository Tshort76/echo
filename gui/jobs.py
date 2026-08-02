"""The conversion queue: jobs waiting behind the one being converted.

"Create audiobook" enqueues rather than refusing while a conversion runs; the
main window drains the queue one job at a time. Serial is deliberate: within a
book the synthesizer already runs ``engine.max_concurrency`` requests at once,
so a second simultaneous book would double the pressure on the same endpoint
without adding throughput.

This module is pure model — what is waiting, what is converting — so it can be
tested without starting workers. The widgets live in ``gui.app``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import QObject, Signal


@dataclass(slots=True)
class ConversionJob:
    """One queued conversion: a display name plus ``ConversionWorker`` kwargs."""

    name: str
    params: dict = field(default_factory=dict)

    @property
    def output_path(self) -> str:
        return str(self.params.get("output_path", ""))

    @property
    def detail(self) -> str:
        """One line for tooltips: what will be made, with what."""
        engine = self.params.get("engine") or "default engine"
        voice = self.params.get("voice") or "default voice"
        fmt = (self.params.get("fmt") or "").upper()
        bits = " · ".join(p for p in (engine, voice, fmt) if p)
        return f"{bits} → {self.output_path}"


class ConversionQueue(QObject):
    """Pending jobs plus the one currently converting.

    Emits ``changed`` on every mutation, so the queue button's count and an open
    queue dialog stay live without polling.
    """

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pending: list[ConversionJob] = []
        self.current: ConversionJob | None = None

    @property
    def pending(self) -> tuple[ConversionJob, ...]:
        return tuple(self._pending)

    def __len__(self) -> int:
        return len(self._pending)

    def add(self, job: ConversionJob) -> None:
        self._pending.append(job)
        self.changed.emit()

    def remove(self, index: int) -> None:
        if 0 <= index < len(self._pending):
            del self._pending[index]
            self.changed.emit()

    def clear_pending(self) -> None:
        if self._pending:
            self._pending.clear()
            self.changed.emit()

    def pop_next(self) -> ConversionJob | None:
        """Promote the first waiting job to ``current``; None if nothing waits."""
        if not self._pending:
            return None
        self.current = self._pending.pop(0)
        self.changed.emit()
        return self.current

    def finish_current(self) -> None:
        self.current = None
        self.changed.emit()

    def holds_output(self, output_path: str) -> bool:
        """Is some queued (or running) job already writing to this path?

        Guards the easiest mistake: clicking "Create audiobook" twice queues the
        same book twice, and the second run would clobber the first's output.
        """
        jobs = list(self._pending) + ([self.current] if self.current else [])
        return any(j.output_path == str(output_path) for j in jobs)
