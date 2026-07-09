"""Tests for the coolant/load correlation rule, against SyntheticReader ground truth."""

from __future__ import annotations

from datetime import datetime, timedelta

from canopy.domain.rules.correlation import RULE_ID, coolant_load_correlation
from canopy.readers.synthetic import SyntheticReader

T0 = datetime(2026, 1, 1, 0, 0, 0)
WINDOW = timedelta(seconds=20)


def test_fires_on_overheat_anomaly_with_evidence():
    reader = SyntheticReader(seed=3, anomaly="overheat")
    coolant = reader.read("CoolantTemp", T0, T0 + WINDOW)
    load = reader.read("EngineLoad", T0, T0 + WINDOW)

    findings = coolant_load_correlation(coolant, load)

    assert len(findings) == 1
    f = findings[0]
    assert f.rule_id == RULE_ID
    assert f.severity == "warning"
    assert f.confidence == "high"
    assert f.evidence, "a finding must cite evidence"


def test_silent_on_nominal_data():
    reader = SyntheticReader(seed=3)  # no anomaly: coolant is stable
    coolant = reader.read("CoolantTemp", T0, T0 + WINDOW)
    load = reader.read("EngineLoad", T0, T0 + WINDOW)

    assert coolant_load_correlation(coolant, load) == []


def test_point_read_degrades_to_low_confidence():
    reader = SyntheticReader(seed=3, anomaly="overheat")
    coolant = reader.read("CoolantTemp", T0, T0)  # zero span => point read
    load = reader.read("EngineLoad", T0, T0)

    findings = coolant_load_correlation(coolant, load)

    assert len(findings) == 1
    f = findings[0]
    assert f.confidence == "low"
    assert f.severity == "warning"
    assert "point read" in f.message.lower()
    assert f.evidence
