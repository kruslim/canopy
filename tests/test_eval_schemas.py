"""The Phase 4 contracts enforce their own integrity (docs/07).

Each validator here guards a way the eval data could become untrustworthy — a correction with
no ground truth, a dissatisfied verdict that names no defense, a case whose assertions
contradict its expected outcome. Untrustworthy eval data poisons everything downstream (the
judge calibration, the regression suite, the README number), so these are caught at authoring
time, not run time.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from canopy.agent.contracts import DiagnosticAnswer
from canopy.evals.schemas import (
    CalibrationReport,
    ErrorType,
    EvalCase,
    ReviewFeedback,
    Severity,
)
from canopy.model.signals import SignalSource

_ANSWER = DiagnosticAnswer(
    summary="Engine speed normal.",
    claims=[],
    findings_referenced=[],
    signals_examined=["EngineRPM"],
    source=SignalSource.SYNTHETIC,
)


def _feedback(**overrides) -> dict:
    base = dict(
        trace_id="t1",
        reviewer_id="kr",
        verdict="approve",
        reviewed_at=datetime(2026, 7, 8),
    )
    base.update(overrides)
    return base


def test_approve_needs_no_error_type():
    fb = ReviewFeedback(**_feedback(verdict="approve"))
    assert fb.error_types == []


def test_correct_verdict_requires_a_corrected_answer():
    with pytest.raises(ValidationError, match="corrected_answer"):
        ReviewFeedback(**_feedback(verdict="correct", error_types=[ErrorType.OVERCONFIDENT]))


def test_correct_with_ground_truth_is_valid():
    fb = ReviewFeedback(
        **_feedback(
            verdict="correct",
            error_types=[ErrorType.MISSED_FINDING],
            corrected_answer=_ANSWER,
        )
    )
    assert fb.corrected_answer is _ANSWER


def test_non_approve_verdict_must_name_a_defense():
    # A reject with no error type is the thumbs-down the taxonomy exists to forbid.
    with pytest.raises(ValidationError, match="error_type"):
        ReviewFeedback(**_feedback(verdict="reject"))


def test_eval_case_answer_cannot_carry_a_refusal_reason():
    with pytest.raises(ValidationError, match="expected_refusal_reason"):
        EvalCase(
            case_id="c",
            question="q",
            source_fixture="clean_full",
            expected_outcome="answer",
            expected_refusal_reason="signal_unavailable",
            origin="handwritten",
        )


def test_eval_case_refusal_cannot_require_citations():
    with pytest.raises(ValidationError, match="cited signals"):
        EvalCase(
            case_id="c",
            question="q",
            source_fixture="clean_full",
            expected_outcome="refusal",
            must_cite_signals=["EngineRPM"],
            origin="handwritten",
        )


def test_from_review_case_must_record_its_source_trace():
    with pytest.raises(ValidationError, match="source_trace_id"):
        EvalCase(
            case_id="c",
            question="q",
            source_fixture="clean_full",
            expected_outcome="answer",
            origin="from_review",
        )


def test_calibration_agreements_must_be_fractions():
    with pytest.raises(ValidationError, match="fraction"):
        CalibrationReport(
            n_traces=10,
            n_reviewers=1,
            inter_human_agreement=None,
            judge_human_agreement=1.4,
        )


def test_severity_and_error_type_are_the_shared_taxonomy():
    # Same enum the judge emits — agreement is a set comparison because the vocabulary matches.
    assert set(Severity) == {Severity.COSMETIC, Severity.MISLEADING, Severity.UNSAFE}
    assert ErrorType.ABSENCE_AS_NEGATION in set(ErrorType)
