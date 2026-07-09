"""L4 — the graph state (docs/05).

Note what is tracked beyond ``messages``: ``tools_called`` and ``signals_touched`` are the
**trace**. The Phase 4 human reviewer needs to see which tools ran and what they returned so
a failure can be attributed to retrieval, tool use, or generation — not just observed as
"the answer was bad." The trace is built here, in Phase 3, because Phase 4 cannot
retroactively invent it.

What must *not* live in state: raw sample arrays. They are summarized into findings and
compacted out of old messages (context.py) — context management as an active discipline.
"""

from __future__ import annotations

from typing import Annotated

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field

from canopy.agent.contracts import DiagnosticAnswer, Refusal
from canopy.model.findings import Finding


class CanopyState(BaseModel):
    messages: Annotated[list[AnyMessage], add_messages] = Field(default_factory=list)
    question: str = ""

    # Loop control
    iteration: int = 0
    max_iterations: int = 8
    forced_final: bool = False  # the cap tripped and the degraded-honest turn was taken
    validation_retries: int = 0
    max_validation_retries: int = 2

    # Provenance — everything the answer rests on
    tools_called: list[str] = Field(default_factory=list)
    signals_touched: list[str] = Field(default_factory=list)
    signals_available: list[str] | None = None  # from the last list_available_signals result
    findings: list[Finding] = Field(default_factory=list)

    # Outcome — exactly one of these is set at END
    answer: DiagnosticAnswer | None = None
    refusal: Refusal | None = None
