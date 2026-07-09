"""The judge and its calibration (docs/07).

The judge emitting the same ``ErrorType`` taxonomy as the human is what turns scoring into a
set comparison. These tests pin the parsing (structured verdict via a bound tool), the
agreement math (overall and per-error-type), and the honest-ceiling machinery — self-agreement
as a stand-in for the inter-rater ceiling a solo project can't measure.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage

from canopy.evals.judge import (
    build_calibration_report,
    judge_trace,
    labels_from_judge,
    per_type_agreement,
    set_agreement,
)
from canopy.evals.schemas import ErrorType
from canopy.evals.trace import Trace
from canopy.model.signals import SignalSource
from conftest import ScriptedModel, ai_call

H, OV = ErrorType.HALLUCINATED_VALUE, ErrorType.OVERCONFIDENT


def _trace(tid: str) -> Trace:
    return Trace(trace_id=tid, question="q", source=SignalSource.SYNTHETIC, outcome="answer")


def test_judge_parses_a_structured_verdict():
    model = ScriptedModel(
        [
            ai_call(
                "judge_verdict",
                {"error_types": ["overconfident"], "severity": "misleading", "rationale": "thin"},
            )
        ]
    )
    verdict = judge_trace(model, _trace("t1"))
    assert verdict.trace_id == "t1"
    assert verdict.error_types == [OV]
    assert verdict.severity == "misleading"


def test_judge_degrades_to_empty_verdict_without_a_tool_call():
    # A judge that answers in prose instead of the tool must not crash the calibration run.
    model = ScriptedModel([AIMessage(content="looks fine to me")])
    verdict = judge_trace(model, _trace("t2"))
    assert verdict.error_types == []


def test_set_agreement_is_exact_match_fraction():
    human = {"t1": {H}, "t2": set(), "t3": {OV}}
    judge = {"t1": {H}, "t2": set(), "t3": set()}  # disagrees only on t3
    assert set_agreement(human, judge) == 2 / 3


def test_per_type_agreement_separates_the_reliable_from_the_judgment_call():
    human = {"t1": {H}, "t2": set(), "t3": {OV}}
    judge = {"t1": {H}, "t2": set(), "t3": set()}
    by_type = per_type_agreement(human, judge)
    # Hallucination is agreed on every trace; overconfidence disagrees on one of three.
    assert by_type[H] == 1.0
    assert by_type[OV] == 2 / 3


def test_calibration_report_reports_the_number_and_its_honest_ceiling():
    human = {"t1": {H}, "t2": set(), "t3": {OV}}
    judge = {"t1": {H}, "t2": set(), "t3": set()}
    # Self-agreement: the same subset scored twice, diverging on one trace — the solo-project
    # stand-in for the inter-rater ceiling.
    self_a = {"t1": {H}, "t2": set(), "t3": {OV}}
    self_b = {"t1": {H}, "t2": {OV}, "t3": {OV}}

    report = build_calibration_report(
        human,
        judge,
        self_pass_a=self_a,
        self_pass_b=self_b,
        single_reviewer_note="Solo project: no panel, so self-agreement stands in for the ceiling.",
    )

    assert report.n_traces == 3
    assert report.judge_human_agreement == 2 / 3
    assert report.self_agreement == 2 / 3
    assert report.self_agreement_n == 3
    assert report.inter_human_agreement is None  # no panel
    assert report.disagreement_examples == ["t3"]
    assert report.judge_agreement_by_error_type[H] == 1.0
    assert report.single_reviewer_note


def test_labels_from_judge_roundtrips_error_types():
    model = ScriptedModel(
        [ai_call("judge_verdict", {"error_types": ["hallucinated_value"], "rationale": "x"})]
    )
    verdict = judge_trace(model, _trace("t9"))
    assert labels_from_judge([verdict]) == {"t9": {H}}
