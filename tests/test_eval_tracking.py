"""Baseline diffing, run history, and the persisted from_review case store (docs/07).

These three artifacts turn the regression *report* — which already knows how to diff itself —
into a ratchet with memory: a bar you move deliberately, a trend you can tail, and a suite that
grows from reviewed failures. The tests pin the load-bearing behaviors: a baseline round-trips
and flags a regression, history appends without clobbering, and persisted cases merge with the
seeds without shadowing them.
"""

from __future__ import annotations

from canopy.evals.assertions import CaseResult
from canopy.evals.cases import SEED_CASES
from canopy.evals.runner import RegressionReport
from canopy.evals.schemas import EvalCase
from canopy.evals.store import append_case, load_persisted_cases, load_regression_cases
from canopy.evals.tracking import (
    HistoryRow,
    append_history,
    load_baseline,
    load_history,
    save_baseline,
)


def _report(passed_by_id: dict[str, bool]) -> RegressionReport:
    return RegressionReport(
        results=[
            CaseResult(case_id=cid, trace_id=f"trace_{cid}", outcome="answer", passed=ok)
            for cid, ok in passed_by_id.items()
        ]
    )


def test_baseline_round_trips_and_flags_regression(tmp_path):
    path = tmp_path / "baseline.json"
    assert load_baseline(path) == {}  # nothing accepted yet

    # Accept a run where case B was already failing (a known, un-fixed bug).
    save_baseline(path, _report({"a": True, "b": False}))
    baseline = load_baseline(path)
    assert baseline == {"a": True, "b": False}

    # Next run: A breaks (regression, blocks) and B starts passing (flywheel payoff).
    now = _report({"a": False, "b": True})
    assert now.regressions(baseline) == ["a"]
    assert now.newly_fixed(baseline) == ["b"]


def test_history_appends_without_clobbering(tmp_path):
    path = tmp_path / "history.jsonl"
    assert load_history(path) == []

    append_history(
        path, HistoryRow(timestamp="2026-07-09T10:00:00", n_passed=5, n_total=6, pass_rate=5 / 6)
    )
    append_history(
        path,
        HistoryRow(
            timestamp="2026-07-09T11:00:00",
            n_passed=6,
            n_total=6,
            pass_rate=1.0,
            newly_fixed=["seed_clean_session"],
            judge_error_types={"overconfident": 1},
        ),
    )

    rows = load_history(path)
    assert [r.n_passed for r in rows] == [5, 6]  # oldest first, both survive
    assert rows[1].newly_fixed == ["seed_clean_session"]
    assert rows[1].judge_error_types == {"overconfident": 1}


def _from_review_case(case_id: str) -> EvalCase:
    return EvalCase(
        case_id=case_id,
        question="Did the rear camera activate within 2s of reverse?",
        source_fixture="clean_full",
        expected_outcome="refusal",
        expected_refusal_reason="signal_unavailable",
        must_not_cite_signals=["RearCameraActivation"],
        origin="from_review",
        source_trace_id="cap_005",
    )


def test_store_appends_dedupes_and_merges_with_seeds(tmp_path):
    path = tmp_path / "regression_cases.jsonl"
    assert load_persisted_cases(path) == []

    case = _from_review_case("from_review_cap_005")
    assert append_case(path, case) is True
    assert append_case(path, case) is False  # same id → not duplicated
    assert len(load_persisted_cases(path)) == 1

    merged = load_regression_cases(path)
    assert len(merged) == len(SEED_CASES) + 1
    assert merged[: len(SEED_CASES)] == SEED_CASES  # seeds first, in order
    assert merged[-1].case_id == "from_review_cap_005"


def test_persisted_case_never_shadows_a_seed(tmp_path):
    path = tmp_path / "regression_cases.jsonl"
    # A persisted row that collides with a seed id must not override the built-in defense.
    shadow = _from_review_case(SEED_CASES[0].case_id)
    append_case(path, shadow)

    merged = load_regression_cases(path)
    assert len(merged) == len(SEED_CASES)  # collision dropped, not appended
    assert merged[0] is SEED_CASES[0]  # the seed, not the shadow
