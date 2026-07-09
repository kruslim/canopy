"""Errors as results (Constraint 3, docs/03).

Below the seam, readers *raise* ``UnknownSignalError``. At the tool layer that exception
must never escape to crash the agent loop; it becomes a structured payload the model can
read and recover from. The payload carries the recovery information — what *is* available
and a hint — because a good tool error does not just say "no," it says "no, and here is what
to do instead."
"""

from __future__ import annotations

from canopy.readers.base import UnknownSignalError, WindowTooLargeError


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


def window_too_large_payload(exc: WindowTooLargeError) -> dict:
    """Turn a raised ``WindowTooLargeError`` into the structured tool-error result.

    Recoverable by construction: the hint tells the model the window is too wide and to
    request a smaller one, which is always the right move — the tool decimates to at most
    ``max_samples`` points anyway, so a narrower window loses no usable resolution.
    """
    return {
        "error": "window_too_large",
        "requested": exc.requested,
        "message": (
            f"The requested time window (~{exc.span_seconds:g}s) is too large: it would "
            f"produce about {exc.estimated_samples} samples, over the "
            f"{exc.max_samples}-sample limit."
        ),
        "estimated_samples": exc.estimated_samples,
        "max_samples": exc.max_samples,
        "hint": (
            "Narrow the time range and try again. Results are downsampled to max_samples "
            "regardless, so a shorter window loses no usable detail."
        ),
    }
