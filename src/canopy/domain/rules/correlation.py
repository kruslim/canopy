"""Correlation rule: coolant temperature rising while engine load is only moderate.

This is a genuine diagnostic pattern and one that is answerable from OBD data alone, which
is why it is the first rule (``docs/01`` / ``docs/02``). If coolant climbs steadily while
load stays moderate, the cooling system — not the driver's right foot — is the suspect:
low coolant, a failing thermostat, a weak water pump, or airflow blockage.

The rule *assumes a timeseries and degrades on a point read*. Handed a single sample it
cannot assess a trend, so it returns a ``low``-confidence ``warning`` rather than silently
passing — the difference between "we looked and it's fine" and "we couldn't look."
"""

from __future__ import annotations

from canopy.model.findings import Finding
from canopy.model.signals import SignalSample, SignalSeries

RULE_ID = "correlation.coolant_rising_under_moderate_load"

# A coolant slope above this (degC per second) counts as "rising".
_COOLANT_RISE_C_PER_S = 0.5
# Mean engine load at or below this (%) counts as "moderate" — i.e. the rise is not simply
# explained by the engine working hard.
_MODERATE_LOAD_MAX_PCT = 60.0


def coolant_load_correlation(
    coolant: SignalSeries,
    load: SignalSeries,
) -> list[Finding]:
    """Evaluate the coolant-vs-load pattern over two aligned series.

    Returns a list of findings (empty when the pattern is absent and the data was
    sufficient to say so).
    """
    # Insufficient data: cannot assess a trend from a point read.
    if coolant.is_point_read or load.is_point_read:
        evidence = _first_n(coolant, 1) + _first_n(load, 1)
        if not evidence:
            return []
        return [
            Finding(
                rule_id=RULE_ID,
                severity="warning",
                message=(
                    "Cannot assess coolant/load correlation: at least one input is a point "
                    "read (single sample), so no trend can be computed. Retrieve a "
                    "timeseries to evaluate this rule."
                ),
                evidence=evidence,
                confidence="low",
            )
        ]

    coolant_slope = _slope_per_second(coolant)
    mean_load = sum(s.value for s in load.samples) / len(load.samples)

    rising = coolant_slope > _COOLANT_RISE_C_PER_S
    moderate = mean_load <= _MODERATE_LOAD_MAX_PCT

    if rising and moderate:
        evidence = _endpoints(coolant) + _endpoints(load)
        return [
            Finding(
                rule_id=RULE_ID,
                severity="warning",
                message=(
                    f"Coolant temperature is rising at ~{coolant_slope:.2f} degC/s while "
                    f"engine load averages only {mean_load:.0f}% (moderate). A temperature "
                    f"climb that is not driven by load suggests a cooling-system issue "
                    f"rather than normal thermal loading."
                ),
                evidence=evidence,
                confidence="high",
            )
        ]

    return []


def _slope_per_second(series: SignalSeries) -> float:
    """Least-squares slope of value vs. elapsed seconds. Robust to per-sample noise."""
    samples = sorted(series.samples, key=lambda s: s.timestamp)
    t0 = samples[0].timestamp
    xs = [(s.timestamp - t0).total_seconds() for s in samples]
    ys = [s.value for s in samples]
    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    denom = sum((x - mean_x) ** 2 for x in xs)
    if denom == 0:
        return 0.0
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
    return num / denom


def _endpoints(series: SignalSeries) -> list[SignalSample]:
    """First and last sample — enough to witness a trend without bloating context."""
    samples = sorted(series.samples, key=lambda s: s.timestamp)
    if len(samples) <= 2:
        return list(samples)
    return [samples[0], samples[-1]]


def _first_n(series: SignalSeries, n: int) -> list[SignalSample]:
    return series.samples[:n]
