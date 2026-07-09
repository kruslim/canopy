"""Tool 2 — ``get_signal``. Retrieve one signal over a time range as a timeseries.

Two return-shape disciplines live here (docs/03):

* **Token economy.** An uncapped series is both useless and expensive once serialized into
  a model's context. ``max_samples`` caps it (hard limit 1000), the series is decimated to
  that many evenly-spaced points, and ``truncated`` tells the model it is looking at a
  decimation.
* **Point reads.** A source may return a single sample (``is_point_read``). ``note`` and a
  null ``actual_sample_rate_hz`` warn the model not to perform timing analysis on it — the
  single most likely reasoning error this tool has to pre-empt.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from canopy.model.signals import SignalSeries
from canopy.readers.base import SignalReader, UnknownSignalError
from canopy.tools.errors import unknown_signal_payload

DESCRIPTION = (
    "Retrieves one signal over a time range, returned as a timeseries with explicit units "
    "and timestamps.\n\n"
    "The `name` must exactly match a name from list_available_signals. Calling this with an "
    "unknown name returns a structured error, not an estimate.\n\n"
    "Different data sources have very different sample rates. A request-response source may "
    "return a SINGLE sample (a 'point read'), with actual_sample_rate_hz set to null. Do "
    "NOT perform timing analysis on a point read — check actual_sample_rate_hz before "
    "reasoning about how a signal changed over time.\n\n"
    "Results are downsampled to max_samples. If `truncated` is true, the series is a "
    "decimation of the full data and fine timing detail may be lost."
)


class GetSignalInput(BaseModel):
    name: str = Field(
        ...,
        description=(
            "Canonical signal name, exactly as returned by list_available_signals. "
            "Case-sensitive. Do not guess or abbreviate."
        ),
    )
    start: datetime = Field(..., description="Start of the time range, inclusive, ISO 8601.")
    end: datetime = Field(..., description="End of the time range, inclusive, ISO 8601.")
    max_samples: int = Field(
        default=200,
        ge=1,
        le=1000,
        description=(
            "Downsampling cap. The full series is decimated to at most this many "
            "evenly-spaced samples. Raise it only when fine timing detail matters; large "
            "values consume context without adding insight."
        ),
    )


class GetSignalOutput(BaseModel):
    series: SignalSeries
    truncated: bool
    actual_sample_rate_hz: float | None
    note: str | None = None


def _decimate(series: SignalSeries, max_samples: int) -> tuple[SignalSeries, bool]:
    """Return an evenly-spaced decimation of ``series`` to at most ``max_samples`` points.

    First and last samples are always retained so the endpoints (which witness a trend) are
    never lost to downsampling.
    """
    samples = series.samples
    n = len(samples)
    if n <= max_samples:
        return series, False
    if max_samples == 1:
        picked = [samples[0]]
    else:
        step = (n - 1) / (max_samples - 1)
        indices = sorted({round(i * step) for i in range(max_samples)})
        picked = [samples[i] for i in indices]
    return series.model_copy(update={"samples": picked}), True


def get_signal(reader: SignalReader, inp: GetSignalInput) -> GetSignalOutput | dict:
    try:
        series = reader.read(inp.name, inp.start, inp.end)
    except UnknownSignalError as exc:
        return unknown_signal_payload(exc)

    # Rate is computed from the full series *before* decimation so it reflects the real
    # source cadence, not the downsampled spacing. Null signals a point read.
    actual_rate = series.sample_rate_hz
    full_count = len(series.samples)
    decimated, truncated = _decimate(series, inp.max_samples)

    if series.is_point_read:
        note = (
            "Point read: the source returned a single sample. No timing analysis is valid; "
            "do not reason about how this signal changed over time."
        )
    elif truncated:
        note = (
            f"Series decimated from {full_count} to {len(decimated.samples)} samples; "
            f"fine timing detail may be lost."
        )
    else:
        note = None

    return GetSignalOutput(
        series=decimated,
        truncated=truncated,
        actual_sample_rate_hz=actual_rate,
        note=note,
    )
