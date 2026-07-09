"""The data-access interface — the contract every reader below the seam implements.

``available_signals()`` is a first-class citizen, not an afterthought: it is the mechanism
by which the agent (later phases) can *know what it cannot answer*. OBD will never expose
rear-camera timing; asked for it, the correct behavior is a grounded refusal, not a
hallucinated number. See ``docs/02-architecture-and-data-model.md``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from canopy.model.signals import SignalSeries


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

    def available_signals(self) -> list[str]:
        """Canonical names this reader can produce. The agent needs this to know what it
        cannot answer."""
        ...

    def read(self, name: str, start: datetime, end: datetime) -> SignalSeries:
        """Read one signal over ``[start, end]`` (inclusive) as a normalized series.

        Raises ``UnknownSignalError`` if ``name`` is not in ``available_signals()``.
        """
        ...
