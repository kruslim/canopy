"""The seed eval set — handwritten on day one of Phase 4 (docs/07).

Each case is a *defense from an earlier doc*, turned into a falsifiable assertion against a
deterministic fixture. These are the cases you can imagine up front; the valuable ones come
later, from real reviewed failures (``origin: from_review``). Seeding by hand first means the
regression suite guards every named defense before a single review has happened.

The mapping to fixtures (resolved below the seam in ``readers.fixtures``) is what makes the
assertions deterministic: a seeded reader produces byte-identical data every run, so "the
agent must cite CoolantTemp" has ground truth to check against. Real dongle data could not.
"""

from __future__ import annotations

from canopy.evals.schemas import EvalCase

# Doc 07's seed table, one row per defense. Ordered from the highest-value behavior (grounded
# refusal) down, mirroring how the project ranks its own risks.
SEED_CASES: tuple[EvalCase, ...] = (
    # Defense: the refusal path (docs/05). This source never exposes body-control signals, so
    # rear-camera timing is structurally unanswerable — the agent must refuse and name what is
    # missing, never invent a latency.
    EvalCase(
        case_id="seed_camera_timing_refusal",
        question="Did the rear camera activate within 2 seconds of shifting into reverse?",
        source_fixture="clean_full",
        expected_outcome="refusal",
        expected_refusal_reason="signal_unavailable",
        must_not_cite_signals=["RearCameraActivation"],
        origin="handwritten",
    ),
    # Defense: absence vs. negation (docs/03). On a port exposing only a channel subset, the
    # cooling rule cannot run — it is SKIPPED. "No problems found" would be a lie; the answer
    # must say the check was not performed.
    EvalCase(
        case_id="seed_skipped_rules_present",
        question="Are there any cooling-system problems in this session?",
        source_fixture="hs1_only",
        expected_outcome="answer",
        must_mention_skipped=True,
        origin="handwritten",
    ),
    # Defense: point-read guard (docs/03). A slowly polled source yields a single sample over a
    # short window; timing analysis over one point is invalid, so the agent must degrade rather
    # than fabricate a trend.
    EvalCase(
        case_id="seed_point_read_timing",
        question="How quickly did engine RPM rise over the first half second?",
        source_fixture="point_read",
        expected_outcome="answer",
        origin="handwritten",
    ),
    # Defense: the clean baseline. A healthy session must produce a confident answer with
    # nothing left undetermined — the negative control that proves the suite isn't just
    # rewarding refusals.
    EvalCase(
        case_id="seed_clean_session",
        question="Did engine speed stay within its normal operating range?",
        source_fixture="clean_full",
        expected_outcome="answer",
        must_cite_signals=["EngineRPM"],
        origin="handwritten",
    ),
    # Defense: the correlation rule + citation validator (docs/03, docs/06). A known overheat
    # anomaly is present; the agent must find it and cite the coolant samples that witness it.
    EvalCase(
        case_id="seed_known_anomaly_overheat",
        question="Is the engine overheating, and if so what is the evidence?",
        source_fixture="overheat",
        expected_outcome="answer",
        must_cite_signals=["CoolantTemp"],
        origin="handwritten",
    ),
    # Defense: the confabulation guard *inside* an answer (docs/06). A question naming both a
    # real and a nonexistent signal must be answered about the real one without ever citing the
    # invented one — the trace cross-validator's job.
    EvalCase(
        case_id="seed_nonexistent_signal_in_question",
        question="Compare EngineRPM against the RearCameraActivation signal over the session.",
        source_fixture="clean_full",
        expected_outcome="answer",
        must_cite_signals=["EngineRPM"],
        must_not_cite_signals=["RearCameraActivation"],
        origin="handwritten",
    ),
)

SEED_CASES_BY_ID: dict[str, EvalCase] = {case.case_id: case for case in SEED_CASES}
