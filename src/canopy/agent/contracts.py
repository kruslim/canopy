"""L5 — the structured-output contracts (docs/06).

The schema is a thinking harness, not just a serialization format: a model forced to fill
``confidence`` and ``citations`` must decide those things explicitly, where free text lets
it hedge fluently. Two validators here are structural, not advisory:

* ``min_length=1`` on citations makes an uncited claim **impossible to serialize**.
  Grounding enforced by the type system, not by hoping the system prompt worked.
* ``signals_must_have_been_examined`` cross-references every citation against the signals
  the answer says it examined. The deeper check — examined signals vs. the *trace* of what
  was actually retrieved — lives in the validate node (graph.py), because only the graph
  state knows what really happened.

Split of authority (docs/06): the model fills the fields that require judgment; the code
fills the fields that require facts it already has. ``source`` is a fact the code knows, so
``AnswerPayload`` (what the model fills) excludes it and ``DiagnosticAnswer`` (what the
system emits) adds it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from canopy.model.signals import SignalSource


class Citation(BaseModel):
    """Every claim points at data. No exceptions."""

    signal: str
    timestamp: datetime
    value: float
    unit: str


class Claim(BaseModel):
    statement: str = Field(..., max_length=300)
    citations: list[Citation] = Field(
        ...,
        min_length=1,
        description="The specific retrieved samples this statement rests on. Never empty.",
    )
    confidence: Literal["high", "medium", "low"]

    @model_validator(mode="after")
    def low_confidence_needs_reason(self) -> Claim:
        # A heuristic, not a proof: catches laziness, not adversarial output (docs/06).
        if self.confidence == "low" and "because" not in self.statement.lower():
            raise ValueError("A low-confidence claim must state why confidence is low.")
        return self


class AnswerPayload(BaseModel):
    """The model-fillable part of the final answer — everything except ``source``."""

    summary: str = Field(..., max_length=500)
    claims: list[Claim]
    findings_referenced: list[str] = Field(
        default_factory=list, description="rule_ids of findings the answer relies on."
    )
    signals_examined: list[str]
    could_not_determine: list[str] = Field(
        default_factory=list,
        description="Questions or sub-questions the available data could not answer.",
    )

    @model_validator(mode="after")
    def signals_must_have_been_examined(self) -> AnswerPayload:
        cited = {c.signal for claim in self.claims for c in claim.citations}
        missing = cited - set(self.signals_examined)
        if missing:
            raise ValueError(f"Cited signals never retrieved: {sorted(missing)}")
        return self


class DiagnosticAnswer(AnswerPayload):
    """The system's final answer: the model's payload plus code-known provenance."""

    source: SignalSource


class Refusal(BaseModel):
    """A grounded 'the data cannot answer that' — a correct outcome, not a failure.

    Distinct from a validation exhaustion (the agent failing to express itself) and never
    routed through ``DiagnosticAnswer`` validation: refusal is its own terminal type
    (docs/06). ``signals_available`` is filled by code from a tool result, never from the
    model's self-knowledge — models are bad at knowing what they don't know, but good at
    reading a list and noticing an absence (docs/05).
    """

    question: str
    reason: Literal[
        "signal_unavailable",
        "insufficient_sample_rate",
        "time_range_not_covered",
        "channel_not_captured",
    ]
    source_connected: SignalSource
    signals_required: list[str]
    signals_available: list[str]
    suggestion: str | None = None


class RefusalPayload(BaseModel):
    """The model-fillable part of a refusal. Question, source, and the available-signal
    list are facts the code already has, so the model is not asked for them."""

    reason: Literal[
        "signal_unavailable",
        "insufficient_sample_rate",
        "time_range_not_covered",
        "channel_not_captured",
    ]
    signals_required: list[str] = Field(
        ...,
        description="The signal names the question would need, none of which are available.",
    )
    suggestion: str | None = Field(
        default=None,
        description="What data source or capture would make the question answerable.",
    )


# The exact summary of a code-built degraded answer. Exposed as a constant so the Phase 4
# trace can classify an outcome as "degraded" (exhaustion) vs. a genuine "answer" without
# re-deriving the string in two places (evals/trace.py).
DEGRADED_SUMMARY = "The agent could not produce a valid structured answer."


def degraded_answer(
    question: str, signals_examined: list[str], source: SignalSource
) -> DiagnosticAnswer:
    """The code-built honest failure used when validation retries are exhausted.

    Never raise instead: a crash produces nothing reviewable, while this flows into the
    Phase 4 review queue like any other answer and becomes an eval case (docs/06).
    """
    return DiagnosticAnswer(
        summary=DEGRADED_SUMMARY,
        claims=[],
        findings_referenced=[],
        signals_examined=signals_examined,
        could_not_determine=[question],
        source=source,
    )
