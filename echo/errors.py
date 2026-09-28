"""The library's exceptions, under one base so a caller can catch them together."""

from __future__ import annotations


class EchoError(RuntimeError):
    """Base class for every error echo raises on purpose."""


class EngineUnavailable(EchoError):
    """An engine's dependencies or credentials are missing.

    Carries an actionable message: what to install, or which variable to set.
    """


class SynthesisError(EchoError):
    """Utterances could not be synthesized after retries."""


class AssemblyError(EchoError):
    """The synthesized audio could not be joined into the output file."""
