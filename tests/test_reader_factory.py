"""Tests for ``build_reader`` — source selection and the demo scenario passthrough.

The scenario mapping lives *below the seam* (a host passes a plain string; the factory
maps it to the concrete reader's anomaly preset), so this is where it is asserted.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from canopy.readers import build_reader
from canopy.readers.base import SignalReader

T0 = datetime(2026, 1, 1, 0, 0, 0)


def _coolant_rise(reader: SignalReader) -> float:
    series = reader.read("CoolantTemp", T0, T0 + timedelta(seconds=120))
    return series.samples[-1].value - series.samples[0].value


def test_default_builds_a_reader():
    assert isinstance(build_reader(), SignalReader)


def test_normal_scenario_has_no_injected_anomaly():
    # None and "normal" both mean "healthy bus": coolant stays near baseline.
    assert abs(_coolant_rise(build_reader())) < 10
    assert abs(_coolant_rise(build_reader(scenario="normal"))) < 10


def test_overheat_scenario_injects_a_rising_coolant_ramp():
    # The overheat preset ramps coolant up over the window — the ground truth the
    # correlation rule (and the web UI's annotated chart) needs.
    assert _coolant_rise(build_reader(scenario="overheat")) > 100


def test_unknown_scenario_is_rejected_with_the_known_list():
    with pytest.raises(ValueError, match="Unknown scenario"):
        build_reader(scenario="meltdown")
