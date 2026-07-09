"""The reviewable trace — what makes review *fast* instead of guesswork (docs/07).

Doc 05 tracked ``tools_called``, ``signals_touched``, ``findings`` and ``skipped`` in the
graph state precisely so this phase could render them. A reviewer who sees that
``run_diagnostic_rules`` returned an empty ``findings`` list next to three ``skipped`` entries
immediately understands *why* the answer was overconfident — and can attribute the failure to
retrieval, tool use, or generation rather than just marking it "bad."

``Trace`` is a serializable snapshot of a terminal ``CanopyState``: the same object the human
reviewer reads, the judge scores, and the eval store persists. It carries no LangChain message
objects — those don't serialize cleanly and the reviewer doesn't need them; it carries the
reconstructed (tool, inputs, outputs) sequence instead.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field

from canopy.agent.contracts import DEGRADED_SUMMARY, DiagnosticAnswer, Refusal
from canopy.agent.graph import REFUSE_TOOL, SUBMIT_ANSWER_TOOL
from canopy.agent.state import CanopyState
from canopy.model.findings import Finding
from canopy.model.signals import SignalSource

Outcome = Literal["answer", "refusal", "degraded"]


class ToolInvocation(BaseModel):
    """One tool call as the reviewer sees it: what was asked, and what came back."""

    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)
    is_error: bool = False


class Trace(BaseModel):
    """A reviewable, serializable snapshot of one agent run."""

    trace_id: str
    question: str
    source: SignalSource
    outcome: Outcome

    # The retrieval/tool-use record, in order — the spine of failure attribution.
    tool_invocations: list[ToolInvocation] = Field(default_factory=list)

    # The provenance carried in state (docs/05).
    tools_called: list[str] = Field(default_factory=list)
    signals_touched: list[str] = Field(default_factory=list)
    signals_available: list[str] | None = None
    findings: list[Finding] = Field(default_factory=list)
    skipped: list[dict[str, str]] = Field(default_factory=list)

    # Exactly one is set, matching ``outcome`` (degraded is an ``answer`` the code built).
    answer: DiagnosticAnswer | None = None
    refusal: Refusal | None = None

    # Loop telemetry — lets a reviewer see a degraded/exhausted run for what it is.
    iteration: int = 0
    forced_final: bool = False
    validation_retries: int = 0

    @classmethod
    def from_state(cls, state: CanopyState, trace_id: str) -> Trace:
        """Build the snapshot from a terminal ``CanopyState``.

        Tool invocations are reconstructed by pairing each assistant tool-call with its
        tool-result message. The two virtual answer-channel tools (``submit_answer``,
        ``refuse``) are excluded: they are the *outcome*, already captured in ``answer`` /
        ``refusal``, not part of the retrieval trace a reviewer attributes failures with.
        """
        results_by_id: dict[str, Any] = {}
        for msg in state.messages:
            call_id = getattr(msg, "tool_call_id", None)
            if call_id is not None:
                results_by_id[call_id] = msg

        invocations: list[ToolInvocation] = []
        for msg in state.messages:
            for call in getattr(msg, "tool_calls", None) or []:
                if call["name"] in (SUBMIT_ANSWER_TOOL, REFUSE_TOOL):
                    continue
                result_msg = results_by_id.get(call["id"])
                payload: dict[str, Any] = {}
                if result_msg is not None:
                    try:
                        payload = json.loads(result_msg.content)
                    except (json.JSONDecodeError, TypeError):
                        payload = {"raw": str(getattr(result_msg, "content", ""))}
                invocations.append(
                    ToolInvocation(
                        name=call["name"],
                        arguments=call.get("args", {}) or {},
                        result=payload,
                        is_error="error" in payload,
                    )
                )

        return cls(
            trace_id=trace_id,
            question=state.question,
            source=_source_of(state),
            outcome=_classify(state),
            tool_invocations=invocations,
            tools_called=list(state.tools_called),
            signals_touched=list(state.signals_touched),
            signals_available=state.signals_available,
            findings=list(state.findings),
            skipped=list(state.skipped),
            answer=state.answer,
            refusal=state.refusal,
            iteration=state.iteration,
            forced_final=state.forced_final,
            validation_retries=state.validation_retries,
        )

    @property
    def has_skipped_rules(self) -> bool:
        """True when a rule could not be run — the ABSENCE_AS_NEGATION trigger (docs/03)."""
        return bool(self.skipped)

    def render(self) -> str:
        """A plain-text rendering of the full trace — the reviewer UI (docs/07).

        Deliberately shows the whole story, not just the answer: the question, every tool
        call with inputs and outputs, the skipped rules, and the outcome. Trace visibility is
        what lets a reviewer attribute a failure rather than guess at it.
        """
        lines = [
            f"trace {self.trace_id}  [{self.outcome.upper()}]  source={self.source}",
            f"Q: {self.question}",
            "",
            "── tool calls ─────────────────────────────",
        ]
        if not self.tool_invocations:
            lines.append("  (none — the agent answered or refused without retrieving data)")
        for i, inv in enumerate(self.tool_invocations, start=1):
            flag = " ⚠ error" if inv.is_error else ""
            lines.append(f"  {i}. {inv.name}({_short(inv.arguments)}){flag}")
            lines.append(f"       → {_short(inv.result)}")

        lines += ["", "── provenance ─────────────────────────────"]
        lines.append(f"  signals touched:   {', '.join(self.signals_touched) or '(none)'}")
        lines.append(
            f"  signals available: {', '.join(self.signals_available or []) or '(unknown)'}"
        )
        lines.append(f"  findings:          {len(self.findings)}")
        if self.skipped:
            skipped = "; ".join(s.get("rule_id", "?") for s in self.skipped)
            lines.append(f"  ⚠ SKIPPED rules:   {skipped}")
            lines.append("    (empty findings + skipped rules = 'we did not look', not 'healthy')")
        if self.forced_final:
            lines.append("  ⚠ forced final turn (iteration cap tripped)")
        if self.validation_retries:
            lines.append(f"  validation retries: {self.validation_retries}")

        lines += ["", "── outcome ────────────────────────────────"]
        if self.refusal is not None:
            lines.append(f"  REFUSAL ({self.refusal.reason}): {self.refusal.suggestion or ''}")
        elif self.answer is not None:
            lines.append(f"  {self.answer.summary}")
            for claim in self.answer.claims:
                cited = ", ".join(f"{c.signal}={c.value}{c.unit}" for c in claim.citations)
                lines.append(f"    • [{claim.confidence}] {claim.statement}  ⟵ {cited}")
            if self.answer.could_not_determine:
                lines.append(f"  could not determine: {'; '.join(self.answer.could_not_determine)}")
        return "\n".join(lines)

    def to_judge_payload(self) -> dict[str, Any]:
        """The dict the LLM-judge sees. Includes ``skipped`` and the tool trace, not just the
        answer — a judge shown only the final text cannot detect ABSENCE_AS_NEGATION (docs/07).
        """
        return {
            "question": self.question,
            "outcome": self.outcome,
            "tool_invocations": [inv.model_dump(mode="json") for inv in self.tool_invocations],
            "signals_touched": self.signals_touched,
            "signals_available": self.signals_available,
            "skipped": self.skipped,
            "findings": [f.model_dump(mode="json") for f in self.findings],
            "answer": self.answer.model_dump(mode="json") if self.answer else None,
            "refusal": self.refusal.model_dump(mode="json") if self.refusal else None,
        }


def _classify(state: CanopyState) -> Outcome:
    if state.refusal is not None:
        return "refusal"
    if state.answer is not None and state.answer.summary == DEGRADED_SUMMARY:
        return "degraded"
    if state.answer is not None:
        return "answer"
    # Neither set is a bug upstream; record it as degraded so it still lands reviewable.
    return "degraded"


def _source_of(state: CanopyState) -> SignalSource:
    if state.answer is not None:
        return state.answer.source
    if state.refusal is not None:
        return state.refusal.source_connected
    return SignalSource.SYNTHETIC


def _short(obj: Any, limit: int = 160) -> str:
    text = json.dumps(obj, default=str)
    return text if len(text) <= limit else text[: limit - 1] + "…"
