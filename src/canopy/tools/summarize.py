"""Tool 4 — ``summarize_session``. A cheap, structural first move.

Good agent design front-loads a cheap orienting call before expensive ones. This tool
returns *structure only* — which signals are present, how many samples each has, where
coverage has gaps, and finding counts by severity — and no interpretation. It constrains all
subsequent reasoning at low token cost (docs/03).

``coverage_gaps`` is the subtle one: a signal can be "present" while missing the exact
interval a user is asking about, so a present signal is not the same as a covered interval.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from canopy.domain.registry import run_rules
from canopy.model.signals import SignalSample, SignalSource
from canopy.readers.base import SignalReader

DESCRIPTION = (
    "Returns a structural overview of a data session: which signals are present, how many "
    "samples each has, where there are gaps in coverage, and a count of findings by "
    "severity.\n\n"
    "Use this BEFORE detailed analysis to understand what data actually exists. This tool "
    "returns no interpretation — only structure. It will not tell you what a finding means; "
    "call run_diagnostic_rules for that.\n\n"
    "coverage_gaps matters: a signal can be 'present' while missing the exact interval a "
    "user is asking about."
)

# A gap is an inter-sample interval this many times the signal's own median cadence.
_GAP_FACTOR = 2.5


class CoverageGap(BaseModel):
    signal: str
    gap_start: datetime
    gap_end: datetime
    duration_s: float


class SummarizeSessionInput(BaseModel):
    start: datetime
    end: datetime


class SummarizeSessionOutput(BaseModel):
    source: SignalSource
    duration_s: float
    signals_present: list[str]
    sample_counts: dict[str, int]
    coverage_gaps: list[CoverageGap]
    finding_counts: dict[str, int]


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def find_coverage_gaps(
    signal: str,
    samples: list[SignalSample],
    start: datetime,
    end: datetime,
    *,
    gap_factor: float = _GAP_FACTOR,
) -> list[CoverageGap]:
    """Detect intervals within a signal's samples materially larger than its own cadence.

    A signal with no samples at all is reported as one gap spanning the whole window. A
    single sample has no cadence to judge, so it yields no gaps. Uniformly-sampled data
    (the nominal case) yields none.
    """
    if not samples:
        return [
            CoverageGap(
                signal=signal,
                gap_start=start,
                gap_end=end,
                duration_s=(end - start).total_seconds(),
            )
        ]

    ordered = sorted(samples, key=lambda s: s.timestamp)
    intervals = [
        (b.timestamp - a.timestamp).total_seconds()
        for a, b in zip(ordered, ordered[1:], strict=False)
    ]
    if not intervals:
        return []
    median_interval = _median(intervals)
    if median_interval <= 0:
        return []

    threshold = gap_factor * median_interval
    gaps: list[CoverageGap] = []
    for a, b in zip(ordered, ordered[1:], strict=False):
        delta = (b.timestamp - a.timestamp).total_seconds()
        if delta > threshold:
            gaps.append(
                CoverageGap(
                    signal=signal,
                    gap_start=a.timestamp,
                    gap_end=b.timestamp,
                    duration_s=round(delta, 3),
                )
            )
    return gaps


def summarize_session(
    reader: SignalReader,
    inp: SummarizeSessionInput,
) -> SummarizeSessionOutput:
    sample_counts: dict[str, int] = {}
    signals_present: list[str] = []
    coverage_gaps: list[CoverageGap] = []

    for name in reader.available_signals():
        series = reader.read(name, inp.start, inp.end)
        count = len(series.samples)
        sample_counts[name] = count
        if count:
            signals_present.append(name)
        coverage_gaps.extend(find_coverage_gaps(name, series.samples, inp.start, inp.end))

    result = run_rules(reader, inp.start, inp.end)
    finding_counts = {"violation": 0, "warning": 0, "info": 0}
    for finding in result.findings:
        finding_counts[finding.severity] += 1

    return SummarizeSessionOutput(
        source=reader.source,
        duration_s=(inp.end - inp.start).total_seconds(),
        signals_present=signals_present,
        sample_counts=sample_counts,
        coverage_gaps=coverage_gaps,
        finding_counts=finding_counts,
    )
