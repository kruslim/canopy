"""Errors as results (Constraint 3, docs/03).

Below the seam, readers *raise* ``UnknownSignalError``. At the tool layer that exception
must never escape to crash the agent loop; it becomes a structured payload the model can
read and recover from. The payload carries the recovery information — what *is* available
and a hint — because a good tool error does not just say "no," it says "no, and here is what
to do instead."
"""

from __future__ import annotations

from canopy.readers.base import UnknownSignalError


def unknown_signal_payload(exc: UnknownSignalError) -> dict:
    """Turn a raised ``UnknownSignalError`` into the structured tool-error result."""
    return {
        "error": "unknown_signal",
        "requested": exc.requested,
        "message": f"Signal {exc.requested!r} is not available from the connected source.",
        "available_signals": exc.available,
        "hint": (
            "The connected source does not expose this signal. Call "
            "list_available_signals to see what it does expose. Do not estimate a value "
            "or substitute a related signal — tell the user it is unavailable."
        ),
    }
