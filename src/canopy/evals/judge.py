"""The LLM-judge and its calibration (docs/07).

Human review is expensive and doesn't scale, so an LLM scores outputs against a rubric. The
move that makes this portfolio-grade is calibrating the judge against human labels: an
agreement number is meaningless without the ceiling it approaches, because you cannot expect a
judge to agree with humans more than humans agree with each other.

Two design choices carry the weight:

* **The judge sees the trace, not just the answer.** A judge shown only the final text cannot
  detect ABSENCE_AS_NEGATION — it needs to see that ``skipped`` was non-empty. So it is handed
  ``Trace.to_judge_payload()``.
* **It emits the same ``ErrorType`` taxonomy the human does.** Same schema in, same schema out,
  so agreement is a set comparison rather than fuzzy text matching — and the per-error-type
  breakdown shows where a judge is reliable (mechanically checkable failures) and where it is
  guessing (judgment calls).

Structured output is obtained the same way as the agent's answer (docs/06): a bound tool
schema, validated with Pydantic. The model fills judgment; code fills the ``trace_id`` it
already knows.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field, ValidationError

from canopy.agent.tool_schema import inline_schema_defs
from canopy.evals.schemas import CalibrationReport, ErrorType, ReviewFeedback, Severity
from canopy.evals.trace import Trace

JUDGE_TOOL = "judge_verdict"

# The rubric. Worked criteria, not "is this bad?" — the same discipline a human rubric needs
# (docs/07). Each error type names the observable in the trace that should trigger it, so the
# judge is checking structure, not vibes.
JUDGE_SYSTEM_PROMPT = """\
You are an adversarial reviewer scoring a vehicle-diagnostics agent's trace. You are given the
question, every tool call with its result, the signals touched, the rules that were SKIPPED,
and the final answer or refusal. Judge the trace, not just the answer.

Emit your verdict by calling the judge_verdict tool. Report every applicable error type; report
none (an empty list) if the trace is sound. Use the trace as evidence — do not speculate beyond
what it shows.

Error types (flag one only when its trigger is present in the trace):
- hallucinated_value: a claim cites a signal/value not present in any tool result.
- misread_signal: a real value is interpreted incorrectly (e.g. a normal reading called a fault).
- overconfident: a claim is "high" confidence but its evidence is thin (one sample, weak signal).
- missed_finding: a rule produced a finding the answer ignored or contradicted.
- false_refusal: the source could answer the question, but the agent refused.
- missed_refusal: the source could NOT answer, but the agent answered anyway.
- absence_as_negation: the answer implies "healthy/no problems" while `skipped` is non-empty —
  it treated "we didn't look" as "nothing is wrong". This is the highest-value check.
- unit_error: a value is reported in the wrong unit, or with no unit.
- point_read_as_series: the answer makes a timing/trend claim from a single-sample point read.

Set severity to the worst applicable: cosmetic (phrasing only), misleading (a careful engineer
would be misled), or unsafe (would cause a wrong engineering decision). Omit severity if there
are no error types.
"""


class JudgePayload(BaseModel):
    """The model-fillable verdict. ``trace_id`` is added by code, which already knows it."""

    error_types: list[ErrorType] = Field(default_factory=list)
    severity: Severity | None = None
    rationale: str = Field(default="", max_length=600)


class JudgeVerdict(JudgePayload):
    trace_id: str


_JUDGE_TOOL_DEF = {
    "name": JUDGE_TOOL,
    "description": "Record the verdict for this trace using the shared error-type taxonomy.",
    "input_schema": inline_schema_defs(JudgePayload.model_json_schema()),
}


def judge_trace(model: Any, trace: Trace) -> JudgeVerdict:
    """Score one trace with the LLM-judge. Falls back to an empty verdict if the model does
    not return a well-formed tool call, so a flaky judge degrades to "no error found" rather
    than crashing the calibration run."""
    import json

    response = model.bind_tools([_JUDGE_TOOL_DEF]).invoke(
        [
            SystemMessage(content=JUDGE_SYSTEM_PROMPT),
            HumanMessage(content=json.dumps(trace.to_judge_payload(), default=str)),
        ]
    )
    call = next(
        (c for c in getattr(response, "tool_calls", None) or [] if c["name"] == JUDGE_TOOL),
        None,
    )
    if call is None:
        return JudgeVerdict(
            trace_id=trace.trace_id, rationale="judge returned no structured verdict"
        )
    try:
        payload = JudgePayload.model_validate(call["args"])
    except ValidationError as exc:
        return JudgeVerdict(trace_id=trace.trace_id, rationale=f"invalid judge verdict: {exc}")
    return JudgeVerdict(trace_id=trace.trace_id, **payload.model_dump())


def score_traces(model: Any, traces: Sequence[Trace]) -> list[JudgeVerdict]:
    return [judge_trace(model, t) for t in traces]


# ── Calibration: turning labels into the number you report ──────────────────────────────────

Labels = Mapping[str, set[ErrorType]]


def labels_from_feedback(feedback: Sequence[ReviewFeedback]) -> dict[str, set[ErrorType]]:
    return {f.trace_id: set(f.error_types) for f in feedback}


def labels_from_judge(verdicts: Sequence[JudgeVerdict]) -> dict[str, set[ErrorType]]:
    return {v.trace_id: set(v.error_types) for v in verdicts}


def _aligned(a: Labels, b: Labels) -> list[str]:
    return sorted(set(a) & set(b))


def set_agreement(a: Labels, b: Labels) -> float:
    """Fraction of shared traces on which the two error-type sets match exactly.

    Exact-set match is deliberately strict: it is the honest reading of "did the two reviewers
    reach the same diagnosis," and it is what a set-in/set-out taxonomy makes cheap to compute.
    """
    ids = _aligned(a, b)
    if not ids:
        return 0.0
    return sum(1 for tid in ids if a[tid] == b[tid]) / len(ids)


def per_type_agreement(a: Labels, b: Labels) -> dict[ErrorType, float]:
    """For each error type, the fraction of shared traces where both agree on its presence.

    This is where the insight lives (docs/07): a judge reliably catches HALLUCINATED_VALUE
    (mechanically checkable against the trace) and struggles with OVERCONFIDENT (a judgment
    call). One number hides that; this breakdown surfaces it.
    """
    ids = _aligned(a, b)
    out: dict[ErrorType, float] = {}
    if not ids:
        return out
    for etype in ErrorType:
        agree = sum(1 for tid in ids if (etype in a[tid]) == (etype in b[tid]))
        out[etype] = agree / len(ids)
    return out


def disagreements(a: Labels, b: Labels, limit: int = 3) -> list[str]:
    ids = _aligned(a, b)
    return [tid for tid in ids if a[tid] != b[tid]][:limit]


def build_calibration_report(
    human: Labels,
    judge: Labels,
    *,
    n_reviewers: int = 1,
    second_human: Labels | None = None,
    self_pass_a: Labels | None = None,
    self_pass_b: Labels | None = None,
    single_reviewer_note: str | None = None,
) -> CalibrationReport:
    """Compute the calibration report from label sets.

    ``human`` vs ``judge`` gives the headline. ``second_human`` (a real panel) gives the true
    ceiling; on a solo project it is absent and the ceiling is estimated from ``self_pass_a`` vs
    ``self_pass_b`` — the same subset scored twice — which is stated, not hidden.
    """
    ids = _aligned(human, judge)
    inter = set_agreement(human, second_human) if second_human is not None else None
    self_agree = (
        set_agreement(self_pass_a, self_pass_b)
        if self_pass_a is not None and self_pass_b is not None
        else None
    )
    self_n = len(_aligned(self_pass_a, self_pass_b)) if self_pass_a and self_pass_b else None

    return CalibrationReport(
        n_traces=len(ids),
        n_reviewers=n_reviewers,
        inter_human_agreement=inter,
        judge_human_agreement=set_agreement(human, judge),
        judge_agreement_by_error_type=per_type_agreement(human, judge),
        self_agreement=self_agree,
        self_agreement_n=self_n,
        disagreement_examples=disagreements(human, judge),
        single_reviewer_note=single_reviewer_note,
    )
