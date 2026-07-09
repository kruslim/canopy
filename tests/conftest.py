"""Shared test scaffolding: a scripted chat model so the whole eval suite is hermetic.

Phase 4 exercises the agent, the review gate, and the judge — all of which take a chat model.
Driving them with a scripted model (no network, no key, no cost) is what lets the regression
suite and the calibration math run in CI deterministically. The determinism the eval harness
relies on lives in the *fixtures* (the data); the model is scripted so the *behavior* under
test is fixed too.

``ScriptedModel`` satisfies the only interface the graphs need:
``bind_tools(defs).invoke(messages) -> AIMessage``.
"""

from __future__ import annotations

from itertools import count

import pytest
from langchain_core.messages import AIMessage

T0 = "2026-01-01T00:00:00"
T20 = "2026-01-01T00:00:20"

_ids = count(1)


def ai_call(tool: str, args: dict) -> AIMessage:
    """An assistant turn requesting exactly one tool call."""
    return AIMessage(
        content="", tool_calls=[{"name": tool, "args": args, "id": f"call_{next(_ids)}"}]
    )


class _Bound:
    def __init__(self, parent: ScriptedModel, tool_names: list[str]) -> None:
        self.parent = parent
        self.tool_names = tool_names

    def invoke(self, messages: list) -> AIMessage:
        self.parent.invocations.append({"tools": self.tool_names, "messages": list(messages)})
        assert self.parent.responses, "script exhausted: a graph asked for more turns than scripted"
        return self.parent.responses.pop(0)


class ScriptedModel:
    def __init__(self, responses: list[AIMessage]) -> None:
        self.responses = list(responses)
        self.invocations: list[dict] = []

    def bind_tools(self, tools: list[dict]) -> _Bound:
        return _Bound(self, [t["name"] for t in tools])


@pytest.fixture
def ai():
    """The single-tool-call assistant-turn factory."""
    return ai_call


@pytest.fixture
def make_model():
    """Factory building a ScriptedModel from a list of scripted AIMessage responses."""
    return ScriptedModel
