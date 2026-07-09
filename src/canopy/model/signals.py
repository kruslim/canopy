"""The normalizer contract — the single most important artifact in the project.

Everything *above the seam* (tools, MCP, agent, evals) speaks only these shapes. It must
never learn whether a number came from an OBD PID or a decoded CAN frame. Two decisions
here are what make Phase 5 (raw CAN) an afternoon instead of a rewrite:

1. A time-ranged read is the general case; "value now" is the special case. So
   ``SignalSeries`` is *always* the return type — an OBD point read is simply a series of
   length one. See ``docs/02-architecture-and-data-model.md``.
2. The engineering ``unit`` travels with the value, always. A bare float is an outage
   waiting to happen, and when serialized into an LLM's context a missing unit is a guess
   the model will make confidently.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class SignalSource(StrEnum):
    """Where a sample originated. Recorded on every sample so provenance survives
    serialization, but callers above the seam must never branch on it."""

    OBD = "obd"
    CAN = "can"
    SYNTHETIC = "synthetic"


class SignalSample(BaseModel):
    """One observation of one signal at one instant."""

    name: str = Field(..., description="Canonical signal name, e.g. 'EngineRPM'.")
    value: float
    unit: str = Field(..., description="Engineering unit, e.g. 'rpm', 'km/h', 'degC'.")
    timestamp: datetime
    source: SignalSource
    quality: Literal["good", "estimated", "stale"] = Field(
        default="good",
        description=(
            "Confidence marker. OBD polling degrades as PIDs are added (values go 'stale'); "
            "CAN captures have dropouts. Lets the domain layer reason about confidence "
            "instead of treating every number as gospel."
        ),
    )


class SignalSeries(BaseModel):
    """A time-ranged read of one signal. The universal return shape.

    An OBD "value now" read returns a series of length one; ``is_point_read`` tells the
    domain layer to degrade gracefully rather than pretend it has a timeseries.
    """

    name: str
    unit: str
    source: SignalSource
    samples: list[SignalSample] = Field(default_factory=list)

    @property
    def is_point_read(self) -> bool:
        """True when there is at most one sample — no timing analysis is valid."""
        return len(self.samples) <= 1

    @property
    def sample_rate_hz(self) -> float | None:
        """Mean sample rate in hertz, or ``None`` for a point read.

        Derived from the mean inter-sample interval across ``samples`` (robust to slight
        irregular spacing). Returns ``None`` when fewer than two samples exist, which is
        the signal to callers that this was a point read.
        """
        if len(self.samples) < 2:
            return None
        ordered = sorted(self.samples, key=lambda s: s.timestamp)
        span_s = (ordered[-1].timestamp - ordered[0].timestamp).total_seconds()
        if span_s <= 0:
            return None
        # N samples across the span => (N - 1) intervals.
        return (len(ordered) - 1) / span_s
