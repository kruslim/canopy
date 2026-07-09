"""L4/L5 — Agent orchestration & structured outputs (above the seam).

The LangGraph loop (docs/05) plus the validated answer contracts (docs/06). Nothing here
names the data source or imports ``readers/`` concretions directly; data is reached only
through the ``SignalReader`` protocol via the tool layer (docs/02, enforced by
``tests/test_seam.py``).

Entry point: ``run_agent(question, reader, model)`` → terminal ``CanopyState`` carrying
exactly one of ``answer`` (a validated ``DiagnosticAnswer``) or ``refusal`` (a grounded
``Refusal``), plus the tool-call trace either way.
"""

from canopy.agent.contracts import (
    AnswerPayload,
    Citation,
    Claim,
    DiagnosticAnswer,
    Refusal,
    RefusalPayload,
    degraded_answer,
)
from canopy.agent.graph import REFUSE_TOOL, SUBMIT_ANSWER_TOOL, build_graph, run_agent
from canopy.agent.state import CanopyState

__all__ = [
    "AnswerPayload",
    "Citation",
    "Claim",
    "DiagnosticAnswer",
    "Refusal",
    "RefusalPayload",
    "degraded_answer",
    "CanopyState",
    "build_graph",
    "run_agent",
    "SUBMIT_ANSWER_TOOL",
    "REFUSE_TOOL",
]
