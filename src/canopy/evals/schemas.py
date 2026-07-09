"""L6 — the eval & human-in-the-loop contracts (docs/07).

Every schema here is deliberately structured, for the same reason Doc 06's answer schema is:
a taxonomy is a thinking harness. A reviewer forced to pick an ``ErrorType`` must decide
*which defense failed*; a thumbs-down lets them hedge. That is the difference between
feedback and data.

The load-bearing design choice is that ``ErrorType`` is **not generic**. Each member maps to
a named weak point in an earlier doc, so every label points at a specific fix — a sentence in
a tool description, a missing validator, a refusal path that didn't trigger. A generic
good/bad signal tells you nothing about which of your defenses failed.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from canopy.agent.contracts import DiagnosticAnswer


class ErrorType(StrEnum):
    """Failure taxonomy, derived from this architecture's known weak points (docs/07).

    Each member names the defense it corresponds to, so a label is a pointer to a fix.
    """

    HALLUCINATED_VALUE = (
        "hallucinated_value"  # cited data that doesn't exist (docs/06 validator gap)
    )
    MISREAD_SIGNAL = "misread_signal"  # wrong interpretation of real data
    OVERCONFIDENT = "overconfident"  # high confidence, weak evidence
    MISSED_FINDING = "missed_finding"  # a rule fired, the answer ignored it
    FALSE_REFUSAL = "false_refusal"  # refused a question it could answer
    MISSED_REFUSAL = "missed_refusal"  # answered a question it couldn't (docs/05 refusal path)
    ABSENCE_AS_NEGATION = "absence_as_negation"  # "no findings" when rules were skipped (docs/03)
    UNIT_ERROR = "unit_error"  # a value reported in the wrong unit, or none
    POINT_READ_AS_SERIES = "point_read_as_series"  # timing analysis on one sample (docs/03)


class Severity(StrEnum):
    """How much a failure matters — phrasing vs. a wrong engineering decision (docs/07)."""

    COSMETIC = "cosmetic"  # phrasing; the answer is right
    MISLEADING = "misleading"  # a careful reader would be misled
    UNSAFE = "unsafe"  # would cause a wrong engineering decision


# Where a failure originated. Attribution is the payoff of the trace (docs/07): a reviewer who
# can see the tool results can say a failure was retrieval, tool use, or generation — not just
# mark it "bad."
FailureStage = Literal["retrieval", "tool_use", "generation", "none"]


class ReviewFeedback(BaseModel):
    """A structured human verdict on one trace. Not a thumbs-down — a diagnosis (docs/07).

    ``verdict`` is the routing decision the review gate acts on; the rest is the data that
    feeds the eval set and the judge calibration.
    """

    trace_id: str
    reviewer_id: str
    verdict: Literal["approve", "correct", "reject"]

    error_types: list[ErrorType] = Field(default_factory=list)
    severity: Severity | None = None

    # Where it went wrong — enables retrieval/tool-use/generation attribution.
    failure_stage: FailureStage | None = None

    # A ``correct`` verdict supplies the answer the agent *should* have given. This becomes
    # the ground truth of the eval case the correction spawns.
    corrected_answer: DiagnosticAnswer | None = None
    reviewer_note: str | None = None

    reviewed_at: datetime

    @model_validator(mode="after")
    def a_correction_needs_an_answer(self) -> ReviewFeedback:
        # "Correct" without a corrected answer is unusable as ground truth — it says the
        # agent was wrong but never says what right looks like.
        if self.verdict == "correct" and self.corrected_answer is None:
            raise ValueError("A 'correct' verdict must supply corrected_answer as ground truth.")
        # A non-approving verdict that names no error type is the thumbs-down this taxonomy
        # exists to prevent: it records dissatisfaction without pointing at a defense.
        if self.verdict != "approve" and not self.error_types:
            raise ValueError(f"A '{self.verdict}' verdict must name at least one error_type.")
        return self


class EvalCase(BaseModel):
    """One regression-suite row: a question, a deterministic fixture, and what "good" means.

    ``source_fixture`` is a *name* resolved below the seam (``readers.fixtures``), never a
    reader — the eval set stays ignorant of which concretion backs a case (Constraint 1). The
    ``must_cite`` / ``must_not_cite`` pair is the mechanical, deterministic half of scoring;
    the fuzzy half is the judge's (docs/07).
    """

    case_id: str
    question: str
    source_fixture: str  # a key into readers.fixtures.build_fixture

    # What "good" looks like — the hard, deterministic assertions.
    expected_outcome: Literal["answer", "refusal"]
    must_cite_signals: list[str] = Field(default_factory=list)
    must_not_cite_signals: list[str] = Field(default_factory=list)  # confabulation guard
    must_mention_skipped: bool = False
    expected_refusal_reason: str | None = None

    # Provenance — how this case entered the suite.
    origin: Literal["handwritten", "from_review"]
    source_trace_id: str | None = None
    error_types_observed: list[ErrorType] = Field(default_factory=list)

    @model_validator(mode="after")
    def refusal_fields_match_outcome(self) -> EvalCase:
        # A refusal reason on an "answer" case (or a citation requirement on a "refusal" case)
        # is a contradiction that would make the assertion unfalsifiable — catch it at authoring
        # time, not at run time.
        if self.expected_outcome == "answer" and self.expected_refusal_reason is not None:
            raise ValueError("An 'answer' case cannot specify expected_refusal_reason.")
        if self.expected_outcome == "refusal" and self.must_cite_signals:
            raise ValueError("A 'refusal' case cannot require cited signals — it cites nothing.")
        if self.origin == "from_review" and self.source_trace_id is None:
            raise ValueError("A 'from_review' case must record the source_trace_id it grew from.")
        return self


class CalibrationReport(BaseModel):
    """The number you report, and everything needed to read it honestly (docs/07).

    The headline is ``judge_human_agreement``. It is meaningless without
    ``inter_human_agreement`` (the ceiling): you cannot expect a judge to agree with humans
    more than humans agree with each other. On a solo project the ceiling is estimated by
    self-agreement — the same subset scored twice — and that limitation is stated, never
    hidden (``single_reviewer_note``).
    """

    n_traces: int
    n_reviewers: int

    inter_human_agreement: float | None  # the ceiling; None when a panel wasn't available
    judge_human_agreement: float  # the headline number
    judge_agreement_by_error_type: dict[ErrorType, float] = Field(default_factory=dict)

    # The honest ceiling proxy for a solo project: score a subset twice, report self-agreement.
    self_agreement: float | None = None
    self_agreement_n: int | None = None

    disagreement_examples: list[str] = Field(default_factory=list)  # trace_ids, for the README
    single_reviewer_note: str | None = None

    @model_validator(mode="after")
    def agreements_are_fractions(self) -> CalibrationReport:
        for name in ("inter_human_agreement", "judge_human_agreement", "self_agreement"):
            v = getattr(self, name)
            if v is not None and not (0.0 <= v <= 1.0):
                raise ValueError(f"{name} must be a fraction in [0, 1], got {v}.")
        return self
