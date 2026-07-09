"""``SyntheticReader`` — deterministic, seeded, no hardware.

This is *not* a toy. It is the reader Layers 2-6 are developed against, and it becomes the
eval fixture in Phase 4 precisely because it is deterministic: the same ``seed`` and time
range always produce byte-identical output, so a capture with a known anomaly at a known
time can be asserted against. If the architecture required a dongle to test, the
architecture would be wrong (``docs/02-architecture-and-data-model.md``).

The canonical signal set mirrors the publicly documented OBD-II PIDs in
``docs/01-domain-primer.md`` so the numbers are physically plausible.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import datetime

from canopy.model.signals import (
    SignalDescriptor,
    SignalSample,
    SignalSeries,
    SignalSource,
)
from canopy.readers.base import UnknownSignalError, WindowTooLargeError


@dataclass(frozen=True)
class _SignalSpec:
    sid: int  # stable per-signal id, mixed into the seed for reproducible noise
    unit: str
    baseline: float
    amplitude: float  # peak deviation of the slow sinusoid around baseline
    noise: float  # peak magnitude of per-sample white noise
    typical_range: tuple[float, float]
    description: str


# Canonical signals, drawn from the OBD-II PID table in docs/01.
_SIGNALS: dict[str, _SignalSpec] = {
    "EngineRPM": _SignalSpec(
        1, "rpm", 1500.0, 700.0, 40.0, (600.0, 6500.0), "crankshaft rotational speed"
    ),
    "VehicleSpeed": _SignalSpec(
        2, "km/h", 55.0, 45.0, 2.0, (0.0, 240.0), "road speed of the vehicle"
    ),
    "CoolantTemp": _SignalSpec(
        3, "degC", 90.0, 3.0, 0.5, (-40.0, 215.0), "engine coolant temperature"
    ),
    "EngineLoad": _SignalSpec(4, "%", 40.0, 8.0, 1.5, (0.0, 100.0), "calculated engine load"),
    "ThrottlePosition": _SignalSpec(
        5, "%", 20.0, 12.0, 2.0, (0.0, 100.0), "throttle plate position"
    ),
}

# Anomaly presets. Each maps a signal name to a per-second linear ramp (in the signal's
# unit) added on top of its normal waveform, letting rules be tested against ground truth.
_ANOMALIES: dict[str, dict[str, float]] = {
    # Coolant climbs steadily while engine load stays moderate — the classic overheat
    # pattern the correlation rule looks for.
    "overheat": {"CoolantTemp": 2.5},
}

_DEFAULT_SAMPLE_RATE_HZ = 10.0

# Upper bound on samples a single read may materialize. Sits far above any realistic
# diagnostic window (a full hour at 10 Hz is 36k samples) and only trips on a pathological
# span — a decade-wide window at 10 Hz would try to build ~3 billion samples in a Python
# loop. The guard raises before the loop so a bad span costs nothing.
_MAX_MATERIALIZED_SAMPLES = 1_000_000


class SyntheticReader:
    """A ``SignalReader`` backed by generated waveforms. Deterministic per ``seed``."""

    def __init__(
        self,
        seed: int = 0,
        sample_rate_hz: float = _DEFAULT_SAMPLE_RATE_HZ,
        anomaly: str | None = None,
        available: tuple[str, ...] | None = None,
    ) -> None:
        if anomaly is not None and anomaly not in _ANOMALIES:
            raise ValueError(
                f"Unknown anomaly {anomaly!r}. Known: {', '.join(_ANOMALIES) or '(none)'}."
            )
        # A real connection exposes a *subset* of what the bus could carry — the port may
        # only bring out HS1/HS2, so callers must treat availability as discovered, not
        # fixed (CLAUDE.md). ``available`` restricts this reader to that discovered subset;
        # asking for anything outside it raises ``UnknownSignalError`` exactly as a source
        # that never carried the signal would. ``None`` means "everything this reader can
        # synthesize."
        if available is not None:
            unknown = [s for s in available if s not in _SIGNALS]
            if unknown:
                raise ValueError(f"Cannot expose signals this reader cannot synthesize: {unknown}.")
        self.seed = seed
        self.sample_rate_hz = sample_rate_hz
        self.anomaly = anomaly
        self._available = tuple(available) if available is not None else tuple(_SIGNALS)

    @property
    def source(self) -> SignalSource:
        return SignalSource.SYNTHETIC

    def available_signals(self) -> list[str]:
        return list(self._available)

    def read(self, name: str, start: datetime, end: datetime) -> SignalSeries:
        if name not in self._available:
            raise UnknownSignalError(name, self.available_signals())
        if end < start:
            raise ValueError("end must be >= start")

        spec = _SIGNALS[name]
        ramp = _ANOMALIES.get(self.anomaly, {}).get(name, 0.0) if self.anomaly else 0.0

        span_s = (end - start).total_seconds()
        # N samples across the span => (N - 1) intervals; a zero span yields one sample
        # (a point read), which is exactly how an OBD "value now" read degrades.
        n = int(math.floor(span_s * self.sample_rate_hz)) + 1

        # Refuse a span that would build an unusable, memory-heavy list. Raised before the
        # loop so the cost is O(1), and carried up as a structured "narrow the window" error
        # at the tool layer (Constraint 3).
        if n > _MAX_MATERIALIZED_SAMPLES:
            raise WindowTooLargeError(
                name,
                estimated_samples=n,
                max_samples=_MAX_MATERIALIZED_SAMPLES,
                span_seconds=span_s,
            )

        # Reproducible noise: seed a private RNG from (global seed, signal id) only.
        rng = random.Random(self.seed * 100_003 + spec.sid)
        step = (1.0 / self.sample_rate_hz) if self.sample_rate_hz > 0 else 0.0

        samples: list[SignalSample] = []
        for i in range(n):
            t = i * step  # elapsed seconds since start
            slow = spec.amplitude * math.sin(2 * math.pi * 0.05 * t)  # gentle 0.05 Hz drift
            jitter = rng.uniform(-spec.noise, spec.noise)
            value = spec.baseline + slow + jitter + ramp * t
            samples.append(
                SignalSample(
                    name=name,
                    value=round(value, 3),
                    unit=spec.unit,
                    timestamp=start + _seconds(i * step),
                    source=SignalSource.SYNTHETIC,
                    quality="good",
                )
            )

        return SignalSeries(
            name=name, unit=spec.unit, source=SignalSource.SYNTHETIC, samples=samples
        )

    def describe(self, name: str) -> SignalDescriptor:
        """Unit / typical-range / description metadata for a signal, used by the
        ``list_available_signals`` tool (docs/03)."""
        if name not in self._available:
            raise UnknownSignalError(name, self.available_signals())
        spec = _SIGNALS[name]
        return SignalDescriptor(
            name=name,
            unit=spec.unit,
            typical_range=spec.typical_range,
            description=spec.description,
        )


def _seconds(value: float):
    from datetime import timedelta

    return timedelta(seconds=value)
