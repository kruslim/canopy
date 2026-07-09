"""The agent loop, hand-rolled. Deliberately kept in the repo (docs/05).

This file exists to prove the graph in ``graph.py`` is understood, not just used: the
difference between "I used LangGraph" and "I know what LangGraph is doing for me." It is
the whole loop in ~50 lines against the raw provider SDK — no graph, no framework, none of
the production defenses (no validation retry, no compaction, no refusal object). Nothing
imports it; do not add features to it. If it stops matching your mental model, rebuild it
from a blank file — that is the Doc 00 self-test.

The mechanics, plainly: the model never executes anything. It emits a structured request;
*this code* runs the tool, appends the result to the conversation, and calls the model
again. The loop ends when the model stops asking for tools or the cap trips — and the cap
takes one final turn with the tools unbound rather than raising, so the failure mode is a
degraded honest answer instead of a stack trace.
"""

from __future__ import annotations

import json

from canopy.agent.executor import ToolExecutor
from canopy.agent.prompts import FORCED_ANSWER_PROMPT, SYSTEM_PROMPT
from canopy.readers.base import SignalReader


def hand_rolled_loop(question: str, reader: SignalReader, max_iterations: int = 8) -> str:
    from anthropic import Anthropic  # local import: nothing else in the package needs it

    client = Anthropic()
    executor = ToolExecutor(reader)
    messages: list[dict] = [{"role": "user", "content": question}]

    for iteration in range(max_iterations + 1):
        forced = iteration == max_iterations
        if forced:
            messages.append({"role": "user", "content": FORCED_ANSWER_PROMPT})

        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            tools=[] if forced else executor.definitions(),
            messages=messages,
        )
        messages.append({"role": "assistant", "content": response.content})

        tool_uses = [block for block in response.content if block.type == "tool_use"]
        if not tool_uses:  # the model answered — normal termination
            return "".join(block.text for block in response.content if block.type == "text")

        # Execute every requested tool; results re-enter as context for the next turn.
        results = [
            {
                "type": "tool_result",
                "tool_use_id": use.id,
                "content": json.dumps(executor.execute(use.name, use.input)),
            }
            for use in tool_uses
        ]
        messages.append({"role": "user", "content": results})

    raise AssertionError("unreachable: the forced turn has no tools, so it cannot loop")
