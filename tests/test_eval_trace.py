"""The trace is the reviewable snapshot the whole phase rests on (docs/07).

If the trace can't distinguish a validated answer from a refusal from a degraded exhaustion, or
can't surface that a rule was skipped, then the reviewer is guessing and the judge is blind to
ABSENCE_AS_NEGATION. These tests pin those distinctions.
"""

from __future__ import annotations

from canopy.agent.graph import run_agent
from canopy.evals.trace import Trace
from canopy.readers.fixtures import build_fixture
from canopy.readers.synthetic import SyntheticReader
from conftest import T0, T20, ScriptedModel, ai_call

_VALID_ANSWER = {
    "summary": "Engine speed stayed in its normal band.",
    "claims": [
        {
            "statement": "EngineRPM remained normal across the window.",
            "citations": [{"signal": "EngineRPM", "timestamp": T0, "value": 1500.0, "unit": "rpm"}],
            "confidence": "high",
        }
    ],
    "findings_referenced": [],
    "signals_examined": ["EngineRPM"],
}


def _trace_for(model, reader, question) -> Trace:
    state = run_agent(question, reader, model)
    return Trace.from_state(state, trace_id="t")


def test_answer_trace_reconstructs_tool_calls_and_classifies_answer():
    model = ScriptedModel(
        [
            ai_call("get_signal", {"name": "EngineRPM", "start": T0, "end": T20}),
            ai_call("submit_answer", _VALID_ANSWER),
        ]
    )
    trace = _trace_for(model, SyntheticReader(), "How did engine speed behave?")

    assert trace.outcome == "answer"
    # The virtual answer-channel tool is excluded; the data tool and its result are present.
    assert [inv.name for inv in trace.tool_invocations] == ["get_signal"]
    assert "series" in trace.tool_invocations[0].result
    assert trace.signals_touched == ["EngineRPM"]


def test_refusal_trace_classifies_refusal_and_carries_no_answer():
    model = ScriptedModel(
        [ai_call("refuse", {"reason": "signal_unavailable", "signals_required": ["X"]})]
    )
    trace = _trace_for(model, SyntheticReader(), "Is X above threshold?")

    assert trace.outcome == "refusal"
    assert trace.answer is None and trace.refusal is not None


def test_degraded_exhaustion_is_not_classified_as_a_clean_answer():
    uncited = {
        "summary": "Looks fine.",
        "claims": [{"statement": "All good.", "citations": [], "confidence": "high"}],
        "findings_referenced": [],
        "signals_examined": [],
    }
    model = ScriptedModel([ai_call("submit_answer", uncited) for _ in range(3)])
    trace = _trace_for(model, SyntheticReader(), "Healthy?")

    # A code-built degraded answer is its own outcome — it must not read as a real answer.
    assert trace.outcome == "degraded"
    assert trace.answer is not None  # still reviewable, just honestly labelled


def test_skipped_rules_surface_in_the_trace_and_render():
    model = ScriptedModel(
        [
            ai_call("run_diagnostic_rules", {"start": T0, "end": T20}),
            ai_call(
                "submit_answer",
                {
                    "summary": "The cooling rule could not run on this source.",
                    "claims": [],
                    "findings_referenced": [],
                    "signals_examined": [],
                    "could_not_determine": ["cooling-system health"],
                },
            ),
        ]
    )
    trace = _trace_for(model, build_fixture("hs1_only"), "Any cooling problems?")

    assert trace.has_skipped_rules
    assert "SKIPPED" in trace.render()
    # The judge payload carries skipped so it can detect absence-as-negation.
    assert trace.to_judge_payload()["skipped"]
