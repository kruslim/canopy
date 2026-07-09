"""The review gate is a real LangGraph interrupt (docs/07).

These drive the gate the way a UI would: run to the interrupt, hand the reviewer the trace,
resume with a verdict. The three verdicts route differently — approve ends, correct mints a
from_review eval case, reject re-runs the agent with the reviewer's note — and the reject retry
is bounded. That routing *is* the flywheel's hinge, so it is tested directly.
"""

from __future__ import annotations

from datetime import datetime

from canopy.evals.review import run_review
from conftest import T0, T20, ScriptedModel, ai_call

_ANSWER = {
    "summary": "Engine speed stayed normal.",
    "claims": [
        {
            "statement": "EngineRPM normal.",
            "citations": [{"signal": "EngineRPM", "timestamp": T0, "value": 1500.0, "unit": "rpm"}],
            "confidence": "high",
        }
    ],
    "findings_referenced": [],
    "signals_examined": ["EngineRPM"],
}


def _agent_run():
    """One well-formed agent run: retrieve then answer."""
    return [
        ai_call("get_signal", {"name": "EngineRPM", "start": T0, "end": T20}),
        ai_call("submit_answer", _ANSWER),
    ]


def _verdict(payload, **fields):
    base = {
        "trace_id": payload["trace_id"],
        "reviewer_id": "kr",
        "reviewed_at": datetime(2026, 7, 8).isoformat(),
    }
    base.update(fields)
    return base


def test_approve_ends_without_minting_a_case():
    model = ScriptedModel(_agent_run())
    state = run_review(
        model,
        "clean_full",
        "Did engine speed stay normal?",
        lambda p: _verdict(p, verdict="approve"),
        thread_id="approve",
    )
    assert state.verdict == "approve"
    assert state.eval_case is None


def test_correct_mints_a_from_review_eval_case_with_ground_truth():
    model = ScriptedModel(_agent_run())

    def reviewer(p):
        return _verdict(
            p,
            verdict="correct",
            error_types=["overconfident"],
            severity="misleading",
            corrected_answer={**_ANSWER, "source": "synthetic"},
        )

    state = run_review(
        model, "clean_full", "Did engine speed stay normal?", reviewer, thread_id="correct"
    )

    assert state.verdict == "correct"
    case = state.eval_case
    assert case is not None
    assert case.origin == "from_review"
    assert case.source_trace_id == state.trace.trace_id
    assert case.source_fixture == "clean_full"  # replayable — the flywheel is closed
    assert case.must_cite_signals == ["EngineRPM"]  # ground truth from the corrected answer
    assert "overconfident" in case.error_types_observed


def test_reject_retries_with_feedback_then_approves():
    # Two full agent runs scripted: the original, then the retry after the reject.
    model = ScriptedModel(_agent_run() + _agent_run())
    calls = {"n": 0}

    def reviewer(p):
        calls["n"] += 1
        if calls["n"] == 1:
            return _verdict(
                p,
                verdict="reject",
                error_types=["overconfident"],
                reviewer_note="Lower the confidence; the evidence is thin.",
            )
        return _verdict(p, verdict="approve")

    state = run_review(
        model,
        "clean_full",
        "Did engine speed stay normal?",
        reviewer,
        thread_id="reject-approve",
        max_rejects=1,
    )

    assert calls["n"] == 2  # reviewed twice: reject, then approve
    assert state.verdict == "approve"
    assert state.reject_count == 1
    # The reviewer's note was folded into the retry as guidance.
    assert any("Lower the confidence" in n for n in state.feedback_notes)


def test_reject_is_bounded_and_terminates():
    model = ScriptedModel(_agent_run() + _agent_run())

    def reviewer(p):
        return _verdict(
            p, verdict="reject", error_types=["overconfident"], reviewer_note="still not convinced"
        )

    state = run_review(
        model,
        "clean_full",
        "Did engine speed stay normal?",
        reviewer,
        thread_id="reject-exhaust",
        max_rejects=1,
    )

    # One retry allowed, then the gate gives up rather than looping forever.
    assert state.verdict == "reject"
    assert state.reject_count == 1
