"""Tests for SyntheticReader — including the Phase 0 done-signal."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from canopy.model.signals import SignalSource
from canopy.readers.base import SignalReader, UnknownSignalError
from canopy.readers.synthetic import SyntheticReader

T0 = datetime(2026, 1, 1, 0, 0, 0)


def test_satisfies_reader_protocol():
    assert isinstance(SyntheticReader(), SignalReader)


def test_available_signals_expected_set():
    reader = SyntheticReader(seed=42)
    assert set(reader.available_signals()) == {
        "EngineRPM",
        "VehicleSpeed",
        "CoolantTemp",
        "EngineLoad",
        "ThrottlePosition",
    }


def test_done_signal_returns_normalized_series():
    """docs/00 & docs/02: call get_signal('EngineRPM', t0, t1) and get a normalized result."""
    reader = SyntheticReader(seed=42)
    series = reader.read("EngineRPM", T0, T0 + timedelta(seconds=10))
    assert series.unit == "rpm"
    assert series.source is SignalSource.SYNTHETIC
    assert series.is_point_read is False
    assert series.sample_rate_hz == pytest.approx(10.0, rel=0.05)
    assert all(s.unit == "rpm" for s in series.samples)


def test_determinism_same_seed_same_output():
    a = SyntheticReader(seed=7).read("CoolantTemp", T0, T0 + timedelta(seconds=5))
    b = SyntheticReader(seed=7).read("CoolantTemp", T0, T0 + timedelta(seconds=5))
    assert a.model_dump() == b.model_dump()


def test_different_seed_differs():
    a = SyntheticReader(seed=1).read("CoolantTemp", T0, T0 + timedelta(seconds=5))
    b = SyntheticReader(seed=2).read("CoolantTemp", T0, T0 + timedelta(seconds=5))
    assert a.model_dump() != b.model_dump()


def test_zero_span_is_point_read():
    series = SyntheticReader().read("EngineRPM", T0, T0)
    assert series.is_point_read is True
    assert series.sample_rate_hz is None


def test_unknown_signal_raises_with_recovery_info():
    reader = SyntheticReader()
    with pytest.raises(UnknownSignalError) as exc:
        reader.read("RearCameraActivation", T0, T0 + timedelta(seconds=1))
    assert exc.value.requested == "RearCameraActivation"
    assert "EngineRPM" in exc.value.available


def test_unknown_anomaly_rejected():
    with pytest.raises(ValueError):
        SyntheticReader(anomaly="does_not_exist")
