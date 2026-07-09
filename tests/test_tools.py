"""Phase 1 tool tests — all against SyntheticReader (plus a small in-test stub reader).

Covers the docs/03 checklist: schema validation, handler behaviour, the structured error
path (never a raw exception), the point-read note, rule-skipping (absence != negation), and
the citation invariant (every finding carries evidence).
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError

from canopy.model.signals import SignalSample, SignalSource
from canopy.readers.base import UnknownSignalError
from canopy.readers.synthetic import SyntheticReader
from canopy.tools import (
    GetSignalInput,
    ListAvailableSignalsInput,
    RunDiagnosticRulesInput,
    SummarizeSessionInput,
    get_signal,
    list_available_signals,
    run_diagnostic_rules,
    summarize_session,
)
from canopy.tools.get_signal import GetSignalOutput
from canopy.tools.list_signals import DESCRIPTION as LIST_DESCRIPTION
from canopy.tools.summarize import CoverageGap, find_coverage_gaps

T0 = datetime(2026, 1, 1, 0, 0, 0)
WINDOW = timedelta(seconds=20)


class _LimitedReader:
    """A SignalReader exposing only a subset of signals — exercises the rule-skip path."""

    def __init__(self, allowed: list[str], anomaly: str | None = None) -> None:
        self._inner = SyntheticReader(seed=0, anomaly=anomaly)
        self._allowed = list(allowed)

    @property
    def source(self) -> SignalSource:
        return self._inner.source

    def available_signals(self) -> list[str]:
        return list(self._allowed)

    def describe(self, name: str):
        if name not in self._allowed:
            raise UnknownSignalError(name, self._allowed)
        return self._inner.describe(name)

    def read(self, name: str, start: datetime, end: datetime):
        if name not in self._allowed:
            raise UnknownSignalError(name, self._allowed)
        return self._inner.read(name, start, end)


# --------------------------------------------------------------------------- schema tests
def test_get_signal_input_rejects_oversized_max_samples():
    with pytest.raises(ValidationError):
        GetSignalInput(name="EngineRPM", start=T0, end=T0 + WINDOW, max_samples=1001)


def test_get_signal_input_rejects_nonpositive_max_samples():
    with pytest.raises(ValidationError):
        GetSignalInput(name="EngineRPM", start=T0, end=T0 + WINDOW, max_samples=0)


def test_get_signal_input_valid_parses_and_defaults():
    inp = GetSignalInput(name="EngineRPM", start=T0, end=T0 + WINDOW)
    assert inp.max_samples == 200


# ------------------------------------------------------------------ list_available_signals
def test_list_available_signals_returns_all_descriptors():
    reader = SyntheticReader(seed=1)
    out = list_available_signals(reader, ListAvailableSignalsInput())

    assert out.source is SignalSource.SYNTHETIC
    assert {d.name for d in out.signals} == set(reader.available_signals())
    assert all(d.unit for d in out.signals)
    assert all(d.description for d in out.signals)


def test_list_available_signals_described_as_call_first():
    assert "call this first" in LIST_DESCRIPTION.lower()


# --------------------------------------------------------------------------------- get_signal
def test_get_signal_returns_series_with_units():
    # 10s at 10Hz => 101 samples, under the default 200 cap: no decimation.
    short = timedelta(seconds=10)
    out = get_signal(
        SyntheticReader(seed=1), GetSignalInput(name="EngineRPM", start=T0, end=T0 + short)
    )
    assert isinstance(out, GetSignalOutput)
    assert out.series.unit == "rpm"
    assert out.truncated is False
    assert out.actual_sample_rate_hz == pytest.approx(10.0, rel=0.05)
    assert out.note is None


def test_get_signal_point_read_sets_null_rate_and_note():
    out = get_signal(SyntheticReader(seed=1), GetSignalInput(name="EngineRPM", start=T0, end=T0))
    assert isinstance(out, GetSignalOutput)
    assert len(out.series.samples) == 1
    assert out.actual_sample_rate_hz is None
    assert out.truncated is False
    assert out.note is not None and "point read" in out.note.lower()


def test_get_signal_truncates_and_flags():
    inp = GetSignalInput(name="EngineRPM", start=T0, end=T0 + WINDOW, max_samples=50)
    out = get_signal(SyntheticReader(seed=1), inp)
    assert isinstance(out, GetSignalOutput)
    assert out.truncated is True
    assert 0 < len(out.series.samples) <= 50
    # Rate must reflect the full pre-decimation cadence, not the downsampled spacing.
    assert out.actual_sample_rate_hz == pytest.approx(10.0, rel=0.05)
    assert out.note is not None and "decimat" in out.note.lower()


def test_get_signal_unknown_name_returns_structured_error():
    out = get_signal(
        SyntheticReader(seed=1),
        GetSignalInput(name="RearCameraActivation", start=T0, end=T0 + WINDOW),
    )
    assert isinstance(out, dict)
    assert out["error"] == "unknown_signal"
    assert out["requested"] == "RearCameraActivation"
    assert out["available_signals"]
    assert out["hint"]


# An excessively wide window is a recoverable tool error, not an exception that spins the
# CPU materializing billions of samples — every read-tool converts the reader's raise.
_HUGE_WINDOW = timedelta(days=3650)


def test_get_signal_oversized_window_returns_structured_error():
    out = get_signal(
        SyntheticReader(seed=1),
        GetSignalInput(name="EngineRPM", start=T0, end=T0 + _HUGE_WINDOW),
    )
    assert isinstance(out, dict)
    assert out["error"] == "window_too_large"
    assert out["estimated_samples"] > out["max_samples"]
    assert "narrow" in out["hint"].lower()


def test_run_diagnostic_rules_oversized_window_returns_structured_error():
    out = run_diagnostic_rules(
        SyntheticReader(seed=3, anomaly="overheat"),
        RunDiagnosticRulesInput(start=T0, end=T0 + _HUGE_WINDOW),
    )
    assert isinstance(out, dict)
    assert out["error"] == "window_too_large"


def test_summarize_session_oversized_window_returns_structured_error():
    out = summarize_session(
        SyntheticReader(seed=1),
        SummarizeSessionInput(start=T0, end=T0 + _HUGE_WINDOW),
    )
    assert isinstance(out, dict)
    assert out["error"] == "window_too_large"


# ------------------------------------------------------------------------ run_diagnostic_rules
def test_run_diagnostic_rules_fires_with_cited_evidence():
    reader = SyntheticReader(seed=3, anomaly="overheat")
    out = run_diagnostic_rules(reader, RunDiagnosticRulesInput(start=T0, end=T0 + WINDOW))

    assert out.findings, "overheat anomaly should produce a finding"
    assert "correlation.coolant_rising_under_moderate_load" in out.rules_run
    assert out.skipped == []
    assert all(f.evidence for f in out.findings), "every finding must cite evidence"


def test_run_diagnostic_rules_skips_when_signal_unavailable():
    # EngineLoad is required by the correlation rule; withhold it.
    reader = _LimitedReader(allowed=["CoolantTemp", "EngineRPM"], anomaly="overheat")
    out = run_diagnostic_rules(reader, RunDiagnosticRulesInput(start=T0, end=T0 + WINDOW))

    assert out.findings == [], "absence of evidence is not evidence of absence"
    assert out.rules_run == []
    assert len(out.skipped) == 1
    assert out.skipped[0]["rule_id"] == "correlation.coolant_rising_under_moderate_load"
    assert "EngineLoad" in out.skipped[0]["reason"]


# ----------------------------------------------------------------------------- summarize_session
def test_summarize_session_structural_overview():
    reader = SyntheticReader(seed=1)
    out = summarize_session(reader, SummarizeSessionInput(start=T0, end=T0 + WINDOW))

    assert out.source is SignalSource.SYNTHETIC
    assert out.duration_s == pytest.approx(20.0)
    assert set(out.signals_present) == set(reader.available_signals())
    assert all(count > 0 for count in out.sample_counts.values())
    assert set(out.finding_counts) == {"violation", "warning", "info"}
    assert out.coverage_gaps == []  # uniform synthetic data has no gaps


def test_summarize_session_counts_findings_by_severity():
    reader = SyntheticReader(seed=3, anomaly="overheat")
    out = summarize_session(reader, SummarizeSessionInput(start=T0, end=T0 + WINDOW))
    assert out.finding_counts["warning"] >= 1


# ------------------------------------------------------------------------------ coverage gaps
def _sample(offset_s: float) -> SignalSample:
    return SignalSample(
        name="EngineRPM",
        value=1500.0,
        unit="rpm",
        timestamp=T0 + timedelta(seconds=offset_s),
        source=SignalSource.SYNTHETIC,
    )


def test_find_coverage_gaps_detects_a_hole():
    # Cadence ~1s, then a 10s hole, then resumes.
    samples = [_sample(0), _sample(1), _sample(2), _sample(12), _sample(13)]
    gaps = find_coverage_gaps("EngineRPM", samples, T0, T0 + timedelta(seconds=13))
    assert len(gaps) == 1
    assert gaps[0].duration_s == pytest.approx(10.0)


def test_find_coverage_gaps_none_on_uniform_data():
    samples = [_sample(i) for i in range(10)]
    assert find_coverage_gaps("EngineRPM", samples, T0, T0 + timedelta(seconds=9)) == []


def test_find_coverage_gaps_empty_signal_is_one_full_window_gap():
    gaps = find_coverage_gaps("EngineRPM", [], T0, T0 + timedelta(seconds=20))
    assert gaps == [
        CoverageGap(
            signal="EngineRPM",
            gap_start=T0,
            gap_end=T0 + timedelta(seconds=20),
            duration_s=20.0,
        )
    ]
