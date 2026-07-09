"""L4 — the agent loop as a LangGraph state graph (docs/05).

Nodes and edges, exactly as specced:

    START → agent → (conditional) tools | validate | refuse
    tools → agent                      [the cycle]
    validate → (conditional) END | agent   [retry on schema failure]
    refuse → END

Why a graph rather than a ``while`` loop: explicit, inspectable control flow — conditional
edges, checkpointing, interrupts for human review (Phase 4 depends on that), and a trace
that can be replayed. The hand-rolled equivalent lives in ``reference_loop.py`` because
understanding what the graph does for you is the point, not a substitute for it.

Termination is engineered, not hoped for (docs/05):

1. the model answers (via the ``submit_answer`` tool — structured output arrives through
   the tool-call channel, docs/06);
2. the iteration cap trips → one final turn with the data tools unbound and an instruction
   to answer honestly from what was retrieved. The answer/refuse channels stay bound,
   because the final answer itself travels as a tool call;
3. the grounded refusal path.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from canopy.agent.context import compaction_updates
from canopy.agent.contracts import (
    AnswerPayload,
    DiagnosticAnswer,
    Refusal,
    RefusalPayload,
    degraded_answer,
)
from canopy.agent.executor import ToolExecutor
from canopy.agent.prompts import (
    FORCED_ANSWER_PROMPT,
    NOT_STRUCTURED_FEEDBACK,
    SYSTEM_PROMPT,
    VALIDATION_FEEDBACK_TEMPLATE,
)
from canopy.agent.state import CanopyState
from canopy.model.findings import Finding
from canopy.readers.base import SignalReader

SUBMIT_ANSWER_TOOL = "submit_answer"
REFUSE_TOOL = "refuse"

# The two virtual tools. The model fills only the judgment fields (docs/06): provenance
# (``source``), the question, and the available-signal list are facts the code already
# knows and injects itself.
_SUBMIT_ANSWER_DEF = {
    "name": SUBMIT_ANSWER_TOOL,
    "description": (
        "Deliver the final structured answer. Every claim must cite at least one "
        "retrieved sample. List anything the data could not determine in "
        "could_not_determine rather than guessing."
    ),
    "input_schema": AnswerPayload.model_json_schema(),
}
_REFUSE_DEF = {
    "name": REFUSE_TOOL,
    "description": (
        "Decline to answer because the connected data source cannot provide the required "
        "signal(s). A grounded refusal is a correct final answer. Only use after checking "
        "list_available_signals."
    ),
    "input_schema": RefusalPayload.model_json_schema(),
}


def _tool_calls(message: Any) -> list[dict]:
    return getattr(message, "tool_calls", None) or []


def build_graph(model: Any, executor: ToolExecutor):
    """Compile the agent graph over a bound chat ``model`` and a tool ``executor``.

    ``model`` needs only ``bind_tools(defs).invoke(messages) -> AIMessage`` — satisfied by
    any LangChain chat model, and by a scripted fake in tests (no network, no key).
    """

    def agent_node(state: CanopyState) -> dict:
        # Compaction applies to what the model sees *now* and persists via the reducer
        # (replacement messages carry the original ids).
        compacted = compaction_updates(state.messages)
        replacements = {m.id: m for m in compacted}
        history = [replacements.get(m.id, m) for m in state.messages]

        updates: list[Any] = list(compacted)
        forced = state.iteration >= state.max_iterations

        if forced and not state.forced_final:
            # The cap converts to a degraded-honest turn, never an exception (docs/05).
            nudge = HumanMessage(content=FORCED_ANSWER_PROMPT)
            history = [*history, nudge]
            updates.append(nudge)

        if forced:
            tools = [_SUBMIT_ANSWER_DEF, _REFUSE_DEF]  # data tools unbound
        else:
            tools = [*executor.definitions(), _SUBMIT_ANSWER_DEF, _REFUSE_DEF]

        response: AIMessage = model.bind_tools(tools).invoke(
            [SystemMessage(content=SYSTEM_PROMPT), *history]
        )
        updates.append(response)
        return {
            "messages": updates,
            "iteration": state.iteration + 1,
            "forced_final": forced or state.forced_final,
        }

    def route_from_agent(state: CanopyState) -> Literal["tools", "validate", "refuse"]:
        names = {call["name"] for call in _tool_calls(state.messages[-1])}
        if SUBMIT_ANSWER_TOOL in names:
            return "validate"
        if REFUSE_TOOL in names:
            return "refuse"
        if names:
            return "tools"
        # Prose where a structured answer belongs: the validate node turns it into
        # feedback and a bounded retry rather than accepting or crashing.
        return "validate"

    def tools_node(state: CanopyState) -> dict:
        """Execute the requested tools and harvest the trace as results stream past.

        The trace (``tools_called``, ``signals_touched``, ``findings``) is read straight
        from the payloads here — the one place every tool result flows through — so the
        validate node and the Phase 4 reviewer get provenance for free.
        """
        new_messages: list[ToolMessage] = []
        tools_called = list(state.tools_called)
        signals = list(state.signals_touched)
        findings = list(state.findings)
        available = state.signals_available

        for call in _tool_calls(state.messages[-1]):
            payload = executor.execute(call["name"], call["args"])
            tools_called.append(call["name"])

            if "series" in payload:
                name = payload["series"]["name"]
                if name not in signals:
                    signals.append(name)
            if "findings" in payload:
                for raw in payload["findings"]:
                    finding = Finding.model_validate(raw)
                    findings.append(finding)
                    for sample in finding.evidence:
                        if sample.name not in signals:
                            signals.append(sample.name)
            if "signals" in payload:
                available = [s["name"] for s in payload["signals"]]

            new_messages.append(
                ToolMessage(
                    content=json.dumps(payload),
                    tool_call_id=call["id"],
                    name=call["name"],
                )
            )

        return {
            "messages": new_messages,
            "tools_called": tools_called,
            "signals_touched": signals,
            "findings": findings,
            "signals_available": available,
        }

    def _validation_failure(state: CanopyState, feedback: str, tool_call_id: str | None) -> dict:
        retries = state.validation_retries + 1
        if retries > state.max_validation_retries:
            # Exhausted: a code-built honest failure, never an exception. It flows into
            # the Phase 4 review queue like any other answer (docs/06).
            answer = degraded_answer(state.question, list(state.signals_touched), executor.source)
            messages: list[Any] = []
            if tool_call_id:
                messages.append(
                    ToolMessage(
                        content="Validation failed and retries are exhausted.",
                        tool_call_id=tool_call_id,
                        name=SUBMIT_ANSWER_TOOL,
                    )
                )
            return {"messages": messages, "validation_retries": retries, "answer": answer}

        # Validation failure is a *turn*, not an error: the Pydantic message goes back to
        # the model with the field name and the escape instruction (docs/06).
        message: Any
        if tool_call_id:
            message = ToolMessage(
                content=feedback, tool_call_id=tool_call_id, name=SUBMIT_ANSWER_TOOL
            )
        else:
            message = HumanMessage(content=feedback)
        return {"messages": [message], "validation_retries": retries}

    def validate_node(state: CanopyState) -> dict:
        last = state.messages[-1]
        submit = next((c for c in _tool_calls(last) if c["name"] == SUBMIT_ANSWER_TOOL), None)
        if submit is None:
            return _validation_failure(state, NOT_STRUCTURED_FEEDBACK, tool_call_id=None)

        errors: list[str] = []
        payload: AnswerPayload | None = None
        try:
            payload = AnswerPayload.model_validate(submit["args"])
        except ValidationError as exc:
            errors = [
                f"  {'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors()
            ]

        if payload is not None:
            # The highest-value validator in the project (docs/06): every cited signal
            # must appear in the trace of signals actually retrieved. The in-model
            # validator checks citations against what the answer *says* it examined;
            # this checks against what actually happened.
            cited = {c.signal for claim in payload.claims for c in claim.citations}
            untraced = cited - set(state.signals_touched)
            if untraced:
                errors.append(
                    f"  signals_examined: Cited signals never retrieved: {sorted(untraced)}"
                )

        if errors:
            feedback = VALIDATION_FEEDBACK_TEMPLATE.format(errors="\n".join(errors))
            return _validation_failure(state, feedback, tool_call_id=submit["id"])

        answer = DiagnosticAnswer(**payload.model_dump(), source=executor.source)
        ack = ToolMessage(
            content="Answer accepted.", tool_call_id=submit["id"], name=SUBMIT_ANSWER_TOOL
        )
        return {"messages": [ack], "answer": answer}

    def route_from_validate(state: CanopyState) -> Literal["agent", "__end__"]:
        return END if state.answer is not None else "agent"

    def refuse_node(state: CanopyState) -> dict:
        """Construct the grounded refusal. The available-signal list comes from a tool
        result (state) or straight from the source — never from the model, which is bad
        at knowing what it doesn't know (docs/05)."""
        call = next((c for c in _tool_calls(state.messages[-1]) if c["name"] == REFUSE_TOOL), None)
        try:
            payload = RefusalPayload.model_validate(call["args"] if call else {})
        except ValidationError:
            payload = RefusalPayload(reason="signal_unavailable", signals_required=[])

        if state.signals_available is not None:
            available = state.signals_available
        else:
            available = executor.available_signals()

        refusal = Refusal(
            question=state.question,
            reason=payload.reason,
            source_connected=executor.source,
            signals_required=payload.signals_required,
            signals_available=available,
            suggestion=payload.suggestion,
        )
        messages: list[Any] = []
        if call:
            messages.append(
                ToolMessage(content="Refusal recorded.", tool_call_id=call["id"], name=REFUSE_TOOL)
            )
        return {"messages": messages, "refusal": refusal}

    graph: StateGraph = StateGraph(CanopyState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tools_node)
    graph.add_node("validate", validate_node)
    graph.add_node("refuse", refuse_node)

    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", route_from_agent)
    graph.add_edge("tools", "agent")
    graph.add_conditional_edges("validate", route_from_validate)
    graph.add_edge("refuse", END)

    return graph.compile()


def run_agent(
    question: str,
    reader: SignalReader,
    model: Any,
    *,
    max_iterations: int = 8,
) -> CanopyState:
    """Ask one natural-language question; return the terminal state.

    Exactly one of ``state.answer`` / ``state.refusal`` is set on return, and the trace
    (``tools_called``, ``signals_touched``, ``findings``) shows how it got there.
    """
    executor = ToolExecutor(reader)
    graph = build_graph(model, executor)
    initial = CanopyState(
        messages=[HumanMessage(content=question)],
        question=question,
        max_iterations=max_iterations,
    )
    # Worst case per iteration is agent + tools (2 graph steps) plus validation retries;
    # the default recursion limit of 25 is too tight for max_iterations=8, so size it.
    result = graph.invoke(initial, config={"recursion_limit": 4 * max_iterations + 16})
    return CanopyState.model_validate(result)
