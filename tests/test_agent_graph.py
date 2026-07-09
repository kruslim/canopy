"""Phase 3 loop tests — hermetic, driven by a scripted model. No network, no key, no cost.

The refusal test comes first, deliberately (docs/05): it is the one that would catch a
regression that matters. The happy path follows.

``ScriptedModel`` satisfies the only interface the graph needs —
``bind_tools(defs).invoke(messages) -> AIMessage`` — and records which tool names were
bound per invocation, so the forced-turn test can assert the data tools were unbound.
"""

from __future__ import annotations

from itertools import count

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from canopy.agent import REFUSE_TOOL, SUBMIT_ANSWER_TOOL, run_agent
from canopy.agent.prompts import FORCED_ANSWER_PROMPT
from canopy.model.signals import SignalSource
from canopy.readers.synthetic import SyntheticReader

T0 = "2026-01-01T00:00:00"
T20 = "2026-01-01T00:00:20"

_ids = count(1)


def ai_call(tool: str, args: dict) -> AIMessage:
    """An assistant turn that requests one tool call."""
    return AIMessage(
        content="",
        tool_calls=[{"name": tool, "args": args, "id": f"call_{next(_ids)}"}],
    )


class _Bound:
    def __init__(self, parent: ScriptedModel, tool_names: list[str]) -> None:
        self.parent = parent
        self.tool_names = tool_names

    def invoke(self, messages: list) -> AIMessage:
        self.parent.invocations.append({"tools": self.tool_names, "messages": list(messages)})
        assert self.parent.responses, "script exhausted: the graph asked for more turns"
        return self.parent.responses.pop(0)


class ScriptedModel:
    def __init__(self, responses: list[AIMessage]) -> None:
        self.responses = list(responses)
        self.invocations: list[dict] = []

    def bind_tools(self, tools: list[dict]) -> _Bound:
        return _Bound(self, [t["name"] for t in tools])


GET_RPM = {"name": "EngineRPM", "start": T0, "end": T20}

VALID_ANSWER = {
    "summary": "Engine speed stayed within its typical operating band over the window.",
    "claims": [
        {
            "statement": "EngineRPM remained in a normal range across the sampled window.",
            "citations": [
                {
                    "signal": "EngineRPM",
                    "timestamp": T0,
                    "value": 1500.0,
                    "unit": "rpm",
                }
            ],
            "confidence": "high",
        }
    ],
    "findings_referenced": [],
    "signals_examined": ["EngineRPM"],
}


# ── The refusal path — written before the happy path, on purpose (docs/05) ──────────────


def test_refuses_camera_question_instead_of_confabulating():
    """The headline behavior: a question the source cannot answer produces a grounded
    refusal naming what is missing and what IS available — never an invented number."""
    model = ScriptedModel(
        [
            ai_call("list_available_signals", {}),
            ai_call(
                REFUSE_TOOL,
                {
                    "reason": "signal_unavailable",
                    "signals_required": ["RearCameraActivation"],
                    "suggestion": "Connect a capture that includes body-control signals.",
                },
            ),
        ]
    )
    reader = SyntheticReader()
    state = run_agent("Did the rear camera activate within 2 seconds in run 47?", reader, model)

    assert state.answer is None
    assert state.refusal is not None
    assert state.refusal.reason == "signal_unavailable"
    assert state.refusal.signals_required == ["RearCameraActivation"]
    assert state.refusal.source_connected == SignalSource.SYNTHETIC
    # Grounded in the tool result: the available list is the source's real list, and the
    # missing signal is not smuggled into it.
    assert set(state.refusal.signals_available) == set(reader.available_signals())
    assert "RearCameraActivation" not in state.refusal.signals_available
    # Refusal is its own terminal type — it never passes through answer validation.
    assert state.validation_retries == 0


def test_refusal_signals_available_is_code_filled_even_without_the_list_tool():
    """If the model refuses without having called list_available_signals, the grounding
    still comes from code, never from model self-knowledge."""
    model = ScriptedModel(
        [ai_call(REFUSE_TOOL, {"reason": "signal_unavailable", "signals_required": ["X"]})]
    )
    reader = SyntheticReader()
    state = run_agent("Is signal X above threshold?", reader, model)

    assert state.refusal is not None
    assert set(state.refusal.signals_available) == set(reader.available_signals())


# ── The happy path ───────────────────────────────────────────────────────────────────────


def test_answers_with_validated_structure_and_visible_trace():
    model = ScriptedModel(
        [ai_call("get_signal", GET_RPM), ai_call(SUBMIT_ANSWER_TOOL, VALID_ANSWER)]
    )
    state = run_agent("How did engine speed behave?", SyntheticReader(), model)

    assert state.refusal is None
    assert state.answer is not None
    assert state.answer.claims[0].citations[0].signal == "EngineRPM"
    # source is filled by code from the active reader, never by the model (docs/06).
    assert state.answer.source == SignalSource.SYNTHETIC
    # The trace — what Phase 4's reviewer attributes failures with.
    assert state.tools_called == ["get_signal"]
    assert state.signals_touched == ["EngineRPM"]
    assert state.validation_retries == 0


def test_findings_from_rules_are_harvested_into_the_trace():
    model = ScriptedModel(
        [
            ai_call("run_diagnostic_rules", {"start": T0, "end": T20}),
            ai_call(
                SUBMIT_ANSWER_TOOL,
                {
                    "summary": "Coolant temperature climbs while load stays moderate.",
                    "claims": [],
                    "findings_referenced": ["coolant_load_correlation"],
                    "signals_examined": ["CoolantTemp", "EngineLoad"],
                    "could_not_determine": [],
                },
            ),
        ]
    )
    state = run_agent("Any problems?", SyntheticReader(seed=3, anomaly="overheat"), model)

    assert state.answer is not None
    assert state.findings, "the fired rule's findings must land in state"
    assert all(f.evidence for f in state.findings)
    # Evidence signals count as touched: the rule examined them on the agent's behalf.
    assert "CoolantTemp" in state.signals_touched


# ── Termination: the iteration cap ──────────────────────────────────────────────────────


def test_iteration_cap_forces_a_final_turn_with_data_tools_unbound():
    degraded = {
        "summary": "Analysis incomplete: the tool budget was reached before conclusions.",
        "claims": [],
        "findings_referenced": [],
        "signals_examined": ["EngineRPM"],
        "could_not_determine": ["full behavior of EngineRPM over the window"],
    }
    model = ScriptedModel(
        [
            ai_call("get_signal", GET_RPM),
            ai_call("get_signal", GET_RPM),
            ai_call(SUBMIT_ANSWER_TOOL, degraded),
        ]
    )
    state = run_agent(
        "Exhaustively characterize everything.", SyntheticReader(), model, max_iterations=2
    )

    # The final invocation had only the answer channels bound — no data tools.
    assert model.invocations[-1]["tools"] == [SUBMIT_ANSWER_TOOL, REFUSE_TOOL]
    # The degraded-honest instruction actually reached the model.
    assert any(
        isinstance(m, HumanMessage) and m.content == FORCED_ANSWER_PROMPT
        for m in model.invocations[-1]["messages"]
    )
    # Degraded but honest: an answer, with the gap declared — not an exception.
    assert state.answer is not None
    assert state.answer.could_not_determine
    assert state.forced_final is True


# ── Validation as a turn, not an error (docs/06) ────────────────────────────────────────


def test_validation_failure_feeds_back_field_name_and_escape_instruction():
    uncited = {
        "summary": "Engine speed looked normal.",
        "claims": [
            {
                "statement": "EngineRPM was normal.",
                "citations": [],  # structurally impossible — must bounce
                "confidence": "high",
            }
        ],
        "findings_referenced": [],
        "signals_examined": ["EngineRPM"],
    }
    model = ScriptedModel(
        [
            ai_call("get_signal", GET_RPM),
            ai_call(SUBMIT_ANSWER_TOOL, uncited),
            ai_call(SUBMIT_ANSWER_TOOL, VALID_ANSWER),
        ]
    )
    state = run_agent("How did engine speed behave?", SyntheticReader(), model)

    assert state.answer is not None
    assert state.validation_retries == 1
    feedback = [
        m
        for m in state.messages
        if isinstance(m, ToolMessage) and "failed validation" in str(m.content)
    ]
    assert feedback, "the validation error must re-enter the conversation"
    text = str(feedback[0].content)
    assert "citations" in text  # names the failing field
    assert "could_not_determine" in text  # the escape instruction (docs/06)


def test_confabulated_citation_is_caught_against_the_trace():
    """The model can lie in signals_examined; it cannot lie to the trace."""
    confabulated = {
        "summary": "The rear camera activated promptly.",
        "claims": [
            {
                "statement": "RearCameraActivation occurred within 2 seconds.",
                "citations": [
                    {
                        "signal": "RearCameraActivation",
                        "timestamp": T0,
                        "value": 1.0,
                        "unit": "bool",
                    }
                ],
                "confidence": "high",
            }
        ],
        "findings_referenced": [],
        "signals_examined": ["RearCameraActivation"],  # consistent lie
    }
    model = ScriptedModel(
        [
            ai_call(SUBMIT_ANSWER_TOOL, confabulated),
            ai_call(
                REFUSE_TOOL,
                {"reason": "signal_unavailable", "signals_required": ["RearCameraActivation"]},
            ),
        ]
    )
    state = run_agent("Did the rear camera activate?", SyntheticReader(), model)

    feedback = [
        m
        for m in state.messages
        if isinstance(m, ToolMessage) and "never retrieved" in str(m.content)
    ]
    assert feedback, "the trace cross-check must catch the confabulation"
    # Given the escape, the model legally withdrew into a refusal.
    assert state.answer is None
    assert state.refusal is not None


def test_retry_exhaustion_degrades_to_a_code_built_answer_not_an_exception():
    uncited = {
        "summary": "Looks fine.",
        "claims": [{"statement": "All good.", "citations": [], "confidence": "high"}],
        "findings_referenced": [],
        "signals_examined": [],
    }
    model = ScriptedModel(
        [
            ai_call(SUBMIT_ANSWER_TOOL, uncited),
            ai_call(SUBMIT_ANSWER_TOOL, uncited),
            ai_call(SUBMIT_ANSWER_TOOL, uncited),
        ]
    )
    question = "Is everything healthy?"
    state = run_agent(question, SyntheticReader(), model)

    assert state.validation_retries == 3  # two retries burned, third failure exhausts
    assert state.answer is not None
    assert state.answer.claims == []
    assert question in state.answer.could_not_determine
    assert state.answer.source == SignalSource.SYNTHETIC


def test_prose_final_reply_is_nudged_into_the_structured_channel():
    model = ScriptedModel(
        [
            AIMessage(content="Everything looks fine to me!"),
            ai_call(
                SUBMIT_ANSWER_TOOL,
                {
                    "summary": "No data was retrieved; nothing can be asserted.",
                    "claims": [],
                    "findings_referenced": [],
                    "signals_examined": [],
                    "could_not_determine": ["engine health"],
                },
            ),
        ]
    )
    state = run_agent("Is the engine healthy?", SyntheticReader(), model)

    assert state.answer is not None
    assert state.validation_retries == 1
