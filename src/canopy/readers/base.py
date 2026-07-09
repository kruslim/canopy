"""The data-access interface — the contract every reader below the seam implements.

``available_signals()`` is a first-class citizen, not an afterthought: it is the mechanism
by which the agent (later phases) can *know what it cannot answer*. OBD will never expose
rear-camera timing; asked for it, the correct behavior is a grounded refusal, not a
hallucinated number. See ``docs/02-architecture-and-data-model.md``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from canopy.model.signals import SignalDescriptor, SignalSeries, SignalSource


class UnknownSignalError(Exception):
    """Raised by ``SignalReader.read`` when a signal is not available from the source.

    Carries the recovery information (the requested name and what *is* available) so that
    the tool layer can later turn it into a structured error payload with a hint, rather
    than crashing the agent loop (``docs/03-tool-design-spec.md``).
    """

    def __init__(self, requested: str, available: list[str]) -> None:
        self.requested = requested
        self.available = available
        super().__init__(
            f"Signal {requested!r} is not available. "
            f"Available signals: {', '.join(available) or '(none)'}."
        )


@runtime_checkable
class SignalReader(Protocol):
    """Implemented by ``SyntheticReader`` (Phase 0), ``ObdReader`` (Phase 1),
    ``CanLogReader`` (Phase 5)."""

    @property
    def source(self) -> SignalSource:
        """Which normalized source this reader represents (``obd`` / ``can`` / ``synthetic``).

        Exposed so tools can report provenance without reading a sample. It is a *value*
        from the normalized ``SignalSource`` enum, not source-library knowledge — callers
        above the seam report it but must never branch on it (docs/02)."""
        ...

    def available_signals(self) -> list[str]:
        """Canonical names this reader can produce. The agent needs this to know what it
        cannot answer."""
        ...

    def describe(self, name: str) -> SignalDescriptor:
        """Static metadata (unit, typical range, gloss) for one available signal.

        Each source owns its own metadata, so this lives on the reader rather than in a
        shared registry that could drift from what the source actually produces. The tool
        layer reaches signal metadata only through here — never by importing a concretion.

        Raises ``UnknownSignalError`` if ``name`` is not in ``available_signals()``.
        """
        ...

    def read(self, name: str, start: datetime, end: datetime) -> SignalSeries:
        """Read one signal over ``[start, end]`` (inclusive) as a normalized series.

        Raises ``UnknownSignalError`` if ``name`` is not in ``available_signals()``.
        """
        ...
