"""Hard assertions are the deterministic tier — they must be exactly right (docs/07).

These build ``Trace`` objects by hand (no agent, no model) to pin each assertion's behavior in
isolation: the confabulation guard, the outcome check that rejects a degraded run, the
skipped-rule acknowledgment. This is the tier that runs in CI on every commit, so its logic is
tested without any LLM in the loop.
"""

from __future__ import annotations

from canopy.agent.contracts import Citation, Claim, DiagnosticAnswer, Refusal
from canopy.evals.assertions import check_case
from canopy.evals.schemas import EvalCase
from canopy.evals.trace import Trace
from canopy.model.signals import SignalSource

_TS = "2026-01-01T00:00:00"


def _answer(signal="EngineRPM") -> DiagnosticAnswer:
    return DiagnosticAnswer(
        summary="ok",
        claims=[
            Claim(
                statement="normal",
                citations=[Citation(signal=signal, timestamp=_TS, value=1.0, unit="rpm")],
                confidence="high",
            )
        ],
        findings_referenced=[],
        signals_examined=[signal],
        source=SignalSource.SYNTHETIC,
    )


def _answer_trace(**kw) -> Trace:
    defaults = dict(
        trace_id="t",
        question="q",
        source=SignalSource.SYNTHETIC,
        outcome="answer",
        answer=_answer(),
        signals_touched=["EngineRPM"],
    )
    defaults.update(kw)
    return Trace(**defaults)


def test_outcome_mismatch_fails():
    case = EvalCase(
        case_id="c",
        question="q",
        source_fixture="clean_full",
        expected_outcome="refusal",
        expected_refusal_reason="signal_unavailable",
        origin="handwritten",
    )
    result = check_case(case, _answer_trace())
    assert not result.passed
    assert any(a.name == "outcome" and not a.passed for a in result.assertions)


def test_degraded_outcome_satisfies_neither_answer_nor_refusal():
    case = EvalCase(
        case_id="c",
        question="q",
        source_fixture="clean_full",
        expected_outcome="answer",
        origin="handwritten",
    )
    result = check_case(case, _answer_trace(outcome="degraded"))
    assert not result.passed  # the agent failed to express itself; not a pass


def test_must_cite_passes_when_signal_is_cited():
    case = EvalCase(
        case_id="c",
        question="q",
        source_fixture="clean_full",
        expected_outcome="answer",
        must_cite_signals=["EngineRPM"],
        origin="handwritten",
    )
    assert check_case(case, _answer_trace()).passed


def test_must_cite_fails_when_signal_absent():
    case = EvalCase(
        case_id="c",
        question="q",
        source_fixture="clean_full",
        expected_outcome="answer",
        must_cite_signals=["CoolantTemp"],
        origin="handwritten",
    )
    assert not check_case(case, _answer_trace()).passed


def test_confabulation_guard_fails_if_forbidden_signal_was_touched():
    # Even if never *cited*, a forbidden signal that reached signals_touched was laundered in.
    case = EvalCase(
        case_id="c",
        question="q",
        source_fixture="clean_full",
        expected_outcome="answer",
        must_not_cite_signals=["RearCameraActivation"],
        origin="handwritten",
    )
    trace = _answer_trace(signals_touched=["EngineRPM", "RearCameraActivation"])
    result = check_case(case, trace)
    assert not result.passed
    assert any("must_not_cite" in a.name and not a.passed for a in result.assertions)


def test_confabulation_guard_allows_a_grounded_refusal_to_name_the_missing_signal():
    # A refusal legitimately lists the missing signal in signals_required — that is not a leak.
    refusal = Refusal(
        question="q",
        reason="signal_unavailable",
        source_connected=SignalSource.SYNTHETIC,
        signals_required=["RearCameraActivation"],
        signals_available=["EngineRPM", "VehicleSpeed"],
    )
    trace = Trace(
        trace_id="t",
        question="q",
        source=SignalSource.SYNTHETIC,
        outcome="refusal",
        refusal=refusal,
        signals_available=["EngineRPM", "VehicleSpeed"],
    )
    case = EvalCase(
        case_id="c",
        question="q",
        source_fixture="clean_full",
        expected_outcome="refusal",
        expected_refusal_reason="signal_unavailable",
        must_not_cite_signals=["RearCameraActivation"],
        origin="handwritten",
    )
    assert check_case(case, trace).passed


def test_must_mention_skipped_requires_both_skip_and_acknowledgment():
    case = EvalCase(
        case_id="c",
        question="q",
        source_fixture="hs1_only",
        expected_outcome="answer",
        must_mention_skipped=True,
        origin="handwritten",
    )
    # Skipped present but the answer says nothing about it → fail.
    silent = _answer_trace(skipped=[{"rule_id": "correlation.x", "reason": "unavailable"}])
    assert not check_case(case, silent).passed

    # Skipped present and the answer declares the gap → pass.
    ack = DiagnosticAnswer(
        summary="ok",
        claims=[],
        findings_referenced=[],
        signals_examined=[],
        could_not_determine=["cooling health"],
        source=SignalSource.SYNTHETIC,
    )
    acknowledged = _answer_trace(
        answer=ack,
        signals_touched=[],
        skipped=[{"rule_id": "correlation.x", "reason": "unavailable"}],
    )
    assert check_case(case, acknowledged).passed
