"""Eval fixtures — *below the seam*, in ``readers/``.

The Phase 4 eval harness needs **deterministic, reproducible** data: a capture with a known
anomaly at a known time so an assertion has ground truth to check against. Real dongle data
is not reproducible; a seeded ``SyntheticReader`` is (``docs/07``). This is the reason
``docs/02`` insisted the synthetic reader "is not a toy."

An ``EvalCase`` names its fixture with a *string* (``source_fixture``). That string is
resolved to a concrete reader **here**, below the seam, so the eval harness above the seam
selects a fixture by name and receives a bare ``SignalReader`` — never learning which
concretion, seed, or subset produced it. This mirrors ``factory.build_reader`` exactly: the
seam holds the protocol, not the concretion (Constraint 1).

Add a fixture by adding a builder to ``_FIXTURES``; the eval case references it by key and
nothing above the seam changes.
"""

from __future__ import annotations

from collections.abc import Callable

from canopy.readers.base import SignalReader
from canopy.readers.synthetic import SyntheticReader

# Each fixture is a zero-arg builder returning a fresh reader, so a run never shares mutable
# reader state with another. Names are stable identifiers referenced by ``EvalCase`` rows and
# by the regression baseline — renaming one silently orphans its cases, so treat them as an
# API.
_FIXTURES: dict[str, Callable[[], SignalReader]] = {
    # A healthy session with the full signal set. The clean-session and refusal cases run
    # here: everything the rules need is present, so an empty findings list is genuinely
    # "we looked and it's fine," not "we couldn't look."
    "clean_full": lambda: SyntheticReader(seed=0),
    # The overheat anomaly: coolant ramps while load stays moderate, the exact pattern the
    # correlation rule fires on. Ground truth for the "known anomaly" case.
    "overheat": lambda: SyntheticReader(seed=3, anomaly="overheat"),
    # A port that only brought out a subset of channels (HS1-style) — no CoolantTemp or
    # EngineLoad — so the correlation rule is *skipped*, not run. Ground truth for the
    # "skipped rules present" defense. Models the real rig note in CLAUDE.md: available
    # channels are discovered, not fixed.
    "hs1_only": lambda: SyntheticReader(
        seed=0, available=("EngineRPM", "VehicleSpeed", "ThrottlePosition")
    ),
    # A source polled slowly enough that a short window yields a single sample — a point
    # read. Timing analysis over one sample is invalid; the agent must degrade rather than
    # pretend it has a timeseries. Ground truth for the "point read, timing question" case.
    "point_read": lambda: SyntheticReader(seed=0, sample_rate_hz=0.01),
}


def fixture_names() -> list[str]:
    """The registered fixture keys — for validating eval cases and building CI baselines."""
    return list(_FIXTURES)


def build_fixture(name: str) -> SignalReader:
    """Resolve an eval fixture name to a fresh ``SignalReader``.

    Returns the protocol, never the concretion: the caller above the seam must not learn or
    branch on what it received (Constraint 1). Raises ``KeyError`` with the known keys on an
    unknown name, so a typo in a case fails loudly rather than silently reading the wrong
    fixture.
    """
    try:
        return _FIXTURES[name]()
    except KeyError:
        raise KeyError(
            f"Unknown eval fixture {name!r}. Known fixtures: {', '.join(_FIXTURES)}."
        ) from None
