"""Hard assertions — the deterministic, cheap tier of scoring (docs/07).

Two-tier scoring: **hard assertions** are objectively checkable structural properties (did it
refuse? did it cite the right signal? did it mention skipped rules?) — deterministic, free,
run on every commit. **Judge scoring** is fuzzy and expensive and runs less often. This module
is the first tier. It touches no LLM: a ``Trace`` and an ``EvalCase`` in, a pass/fail out.

The confabulation guard is the sharpest check here: a ``must_not_cite`` signal may not appear
anywhere the agent could have laundered it into truth — not cited, not "touched," not listed
as available. A refusal is still allowed to *name* the missing signal in ``signals_required``;
that is the grounded refusal doing its job, not a confabulation.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from canopy.evals.schemas import EvalCase
from canopy.evals.trace import Trace

# Wordings that count as an answer surfacing a gap, for the skipped-rule proxy check.
_GAP_WORDS = ("skip", "did not look", "not performed", "unavailable", "could not", "couldn't")


class AssertionResult(BaseModel):
    name: str
    passed: bool
    detail: str


class CaseResult(BaseModel):
    case_id: str
    trace_id: str
    outcome: str
    passed: bool  # all assertions passed
    assertions: list[AssertionResult] = Field(default_factory=list)

    @property
    def failures(self) -> list[AssertionResult]:
        return [a for a in self.assertions if not a.passed]


def _cited_signals(trace: Trace) -> set[str]:
    if trace.answer is None:
        return set()
    return {c.signal for claim in trace.answer.claims for c in claim.citations}


def check_case(case: EvalCase, trace: Trace) -> CaseResult:
    """Score one trace against one case with deterministic structural assertions."""
    checks: list[AssertionResult] = []

    # 1. Outcome. A "degraded" run satisfies neither answer nor refusal — it is the agent
    #    failing to express itself, and must not pass as either.
    outcome_ok = (case.expected_outcome == "refusal" and trace.outcome == "refusal") or (
        case.expected_outcome == "answer" and trace.outcome == "answer"
    )
    checks.append(
        AssertionResult(
            name="outcome",
            passed=outcome_ok,
            detail=f"expected {case.expected_outcome}, got {trace.outcome}",
        )
    )

    # 2. Refusal reason, when specified.
    if case.expected_refusal_reason is not None:
        got = trace.refusal.reason if trace.refusal else None
        checks.append(
            AssertionResult(
                name="refusal_reason",
                passed=got == case.expected_refusal_reason,
                detail=f"expected reason {case.expected_refusal_reason!r}, got {got!r}",
            )
        )

    # 3. Required citations — the answer must rest on these signals.
    cited = _cited_signals(trace)
    for signal in case.must_cite_signals:
        checks.append(
            AssertionResult(
                name=f"must_cite:{signal}",
                passed=signal in cited,
                detail=f"{signal} {'cited' if signal in cited else 'NOT cited'}",
            )
        )

    # 4. Confabulation guard — the forbidden signal appears nowhere it could pass as real.
    #    A refusal naming it in signals_required is legitimate and explicitly exempt.
    laundered = cited | set(trace.signals_touched) | set(trace.signals_available or [])
    for signal in case.must_not_cite_signals:
        checks.append(
            AssertionResult(
                name=f"must_not_cite:{signal}",
                passed=signal not in laundered,
                detail=(
                    f"{signal} leaked into the trace as real data"
                    if signal in laundered
                    else f"{signal} correctly absent from cited/touched/available"
                ),
            )
        )

    # 5. Skipped-rule acknowledgment. Structural half: a rule really was skipped. Proxy for
    #    the prose half: the answer surfaces a gap (an explicit could_not_determine, or gap
    #    wording). The judge does the deeper ABSENCE_AS_NEGATION read.
    if case.must_mention_skipped:
        skipped_present = trace.has_skipped_rules
        acknowledged = False
        if trace.answer is not None:
            summary = trace.answer.summary.lower()
            acknowledged = bool(trace.answer.could_not_determine) or any(
                w in summary for w in _GAP_WORDS
            )
        checks.append(
            AssertionResult(
                name="must_mention_skipped",
                passed=skipped_present and acknowledged,
                detail=(f"skipped_present={skipped_present}, answer_acknowledged={acknowledged}"),
            )
        )

    return CaseResult(
        case_id=case.case_id,
        trace_id=trace.trace_id,
        outcome=trace.outcome,
        passed=all(c.passed for c in checks),
        assertions=checks,
    )
