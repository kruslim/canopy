"""Doc 06's validator suite — hand-written dicts, no model calls, fast.

These are the structural guarantees: an uncited claim cannot serialize, a citation of an
unexamined signal cannot validate, and exhaustion produces an honest code-built answer.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from pydantic import ValidationError

from canopy.agent.context import compaction_updates
from canopy.agent.contracts import AnswerPayload, DiagnosticAnswer, degraded_answer
from canopy.agent.parsing import strip_markdown_fences
from canopy.model.signals import SignalSource

CITATION = {
    "signal": "EngineRPM",
    "timestamp": "2026-01-01T00:00:00",
    "value": 1500.0,
    "unit": "rpm",
}


def _claim(**overrides) -> dict:
    claim = {
        "statement": "EngineRPM stayed within its typical band.",
        "citations": [CITATION],
        "confidence": "high",
    }
    claim.update(overrides)
    return claim


def _payload(**overrides) -> dict:
    payload = {
        "summary": "Engine speed behaved normally over the window.",
        "claims": [_claim()],
        "findings_referenced": [],
        "signals_examined": ["EngineRPM"],
    }
    payload.update(overrides)
    return payload


def test_golden_answer_validates():
    answer = AnswerPayload.model_validate(_payload())
    assert answer.claims[0].citations[0].unit == "rpm"
    assert answer.could_not_determine == []


def test_uncited_claim_is_structurally_impossible():
    with pytest.raises(ValidationError) as excinfo:
        AnswerPayload.model_validate(_payload(claims=[_claim(citations=[])]))
    assert "citations" in str(excinfo.value)


def test_citing_an_unexamined_signal_fails_and_names_it():
    bad = _payload(signals_examined=["VehicleSpeed"])  # cites EngineRPM, examined neither
    with pytest.raises(ValidationError) as excinfo:
        AnswerPayload.model_validate(bad)
    assert "EngineRPM" in str(excinfo.value)
    assert "never retrieved" in str(excinfo.value)


def test_low_confidence_claim_must_state_why():
    with pytest.raises(ValidationError):
        AnswerPayload.model_validate(
            _payload(claims=[_claim(confidence="low", statement="EngineRPM seemed odd.")])
        )
    # With a stated reason it passes — the heuristic looks for 'because' (docs/06).
    AnswerPayload.model_validate(
        _payload(
            claims=[
                _claim(
                    confidence="low",
                    statement="EngineRPM assessment is tentative because only one sample exists.",
                )
            ]
        )
    )


def test_degraded_answer_is_an_honest_machine_readable_failure():
    answer = degraded_answer("Is it healthy?", ["EngineRPM"], SignalSource.SYNTHETIC)
    assert isinstance(answer, DiagnosticAnswer)
    assert answer.claims == []
    assert answer.could_not_determine == ["Is it healthy?"]
    assert answer.signals_examined == ["EngineRPM"]
    assert answer.source == SignalSource.SYNTHETIC


# ── The markdown-fence problem (docs/06) ────────────────────────────────────────────────


def test_fenced_json_is_stripped():
    payload = {"summary": "ok"}
    fenced = f"```json\n{json.dumps(payload)}\n```"
    assert json.loads(strip_markdown_fences(fenced)) == payload


def test_bare_fence_and_plain_text_pass_through_sensibly():
    assert strip_markdown_fences('```\n{"a": 1}\n```') == '{"a": 1}'
    assert strip_markdown_fences('{"a": 1}') == '{"a": 1}'
    # A fence in the middle of prose is content, not wrapping.
    prose = "See ```code``` for details."
    assert strip_markdown_fences(prose) == prose


# ── Context compaction (docs/05) ────────────────────────────────────────────────────────


def _series_payload(n: int) -> str:
    t0 = datetime(2026, 1, 1)
    return json.dumps(
        {
            "series": {
                "name": "EngineRPM",
                "unit": "rpm",
                "source": "synthetic",
                "samples": [
                    {
                        "name": "EngineRPM",
                        "value": 1000.0 + i,
                        "unit": "rpm",
                        "timestamp": (t0 + timedelta(seconds=i)).isoformat(),
                        "source": "synthetic",
                        "quality": "good",
                    }
                    for i in range(n)
                ],
            },
            "truncated": False,
            "actual_sample_rate_hz": 10.0,
        }
    )


def _tool_message(i: int) -> ToolMessage:
    return ToolMessage(
        content=_series_payload(50),
        tool_call_id=f"call_{i}",
        name="get_signal",
        id=f"msg_{i}",
    )


def test_compaction_collapses_oldest_tool_results_and_keeps_recent_ones():
    messages = [AIMessage(content="", id="ai_0")] + [_tool_message(i) for i in range(5)]
    updates = compaction_updates(messages, budget_chars=2_000)

    assert updates, "over budget, so something must compact"
    updated_ids = {m.id for m in updates}
    # The two most recent tool results are untouchable.
    assert "msg_4" not in updated_ids and "msg_3" not in updated_ids
    # The oldest compacts first, in place (same id), down to a one-liner with the shape.
    assert "msg_0" in updated_ids
    oldest = next(m for m in updates if m.id == "msg_0")
    assert str(oldest.content).startswith("[compacted]")
    assert "50 samples" in str(oldest.content)
    assert "rpm" in str(oldest.content)


def test_compaction_is_a_no_op_under_budget():
    messages = [_tool_message(0)]
    assert compaction_updates(messages, budget_chars=10_000_000) == []
