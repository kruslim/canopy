"""Tests for the normalizer contract: SignalSample / SignalSeries."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from canopy.model.signals import SignalSample, SignalSeries, SignalSource

T0 = datetime(2026, 1, 1, 0, 0, 0)


def _sample(value: float, offset_s: float, unit: str = "rpm") -> SignalSample:
    return SignalSample(
        name="EngineRPM",
        value=value,
        unit=unit,
        timestamp=T0 + timedelta(seconds=offset_s),
        source=SignalSource.SYNTHETIC,
    )


def test_point_read_has_no_sample_rate():
    series = SignalSeries(
        name="EngineRPM", unit="rpm", source=SignalSource.OBD, samples=[_sample(800, 0)]
    )
    assert series.is_point_read is True
    assert series.sample_rate_hz is None


def test_empty_series_is_point_read():
    series = SignalSeries(name="EngineRPM", unit="rpm", source=SignalSource.OBD, samples=[])
    assert series.is_point_read is True
    assert series.sample_rate_hz is None


def test_sample_rate_computed_from_span():
    # 11 samples spanning 1.0 s => 10 intervals => 10 Hz.
    samples = [_sample(800 + i, i * 0.1) for i in range(11)]
    series = SignalSeries(
        name="EngineRPM", unit="rpm", source=SignalSource.SYNTHETIC, samples=samples
    )
    assert series.is_point_read is False
    assert series.sample_rate_hz == pytest.approx(10.0)


def test_unit_travels_with_value():
    s = _sample(90.0, 0, unit="degC")
    assert s.unit == "degC"
    # round-trips through serialization with the unit intact.
    assert SignalSample.model_validate(s.model_dump()).unit == "degC"


def test_quality_defaults_to_good():
    assert _sample(800, 0).quality == "good"
