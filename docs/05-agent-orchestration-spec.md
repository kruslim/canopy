# 05 — Agent Orchestration Spec

**Phase:** 3
**Status when done:** a natural-language question produces a validated answer with a visible tool-call trace — *and* an out-of-scope question produces a graceful refusal rather than a hallucination.

This is the core GenAI document. If you understand only one thing deeply, make it this one. It is the single most probable interview topic for these roles.

---

## The agent loop, stated plainly

You must be able to draw this on a whiteboard, unprompted, from memory.

```
        ┌─────────────────────────────────┐
        │  1. Model receives:             │
        │     • system prompt             │
        │     • conversation history      │
        │     • tool schemas + descriptions│
        └───────────────┬─────────────────┘
                        ▼
        ┌─────────────────────────────────┐
        │  2. Model decides                │
        │     "answer" or "call tool(s)"   │
        └───────────────┬─────────────────┘
                        ▼
                 ┌──────────────┐
                 │ tool call?   │
                 └──┬────────┬──┘
                yes │        │ no
                    ▼        └──────────┐
        ┌─────────────────────────┐     │
        │  3. Your code executes  │     │
        │     the tool            │     │
        └───────────┬─────────────┘     │
                    ▼                   │
        ┌─────────────────────────┐     │
        │  4. Result appended to  │     │
        │     conversation as a   │     │
        │     tool-result message │     │
        └───────────┬─────────────┘     │
                    │                   │
                    └───────► back to 1 │
                                        ▼
                         ┌──────────────────────┐
                         │  5. Validate output  │
                         │     against schema   │
                         │     (Doc 06)         │
                         └──────────┬───────────┘
                                    ▼
                              final answer
```

**The three things people get wrong when explaining this:**

1. **The model does not execute the tool.** It emits a *structured request* to call a tool. Your code executes it. The model never touches your data source. This distinction matters for security and for reasoning about failure.

2. **The loop is driven by the model, not by you.** You do not decide how many tools to call or in what order. You provide schemas and descriptions; the model plans. Your control is exercised through *tool design* (Doc 03) and the *system prompt*, not through imperative sequencing. This is what "orchestration" actually means and why it feels alien to control-flow-minded engineers.

3. **Tool results re-enter as context.** Each result is appended to the conversation. The model on iteration N+1 sees everything from iterations 1..N. This is why uncapped tool output destroys agents — the context fills with samples and the model loses the thread.

---

## Where the loop can fail

Name these, because you will be asked. Each has a mitigation already built in the earlier docs.

| Failure | Cause | Mitigation | Doc |
|---|---|---|---|
| **Infinite loop** | Model keeps calling tools, never answers | Hard iteration cap; forced-answer turn | this doc |
| **Tool errors** | Unknown signal, bad range | Structured error result with recovery hint | 03, 04 |
| **Wrong tool called** | Vague description | Negative space in descriptions; cheap orienting tool | 03 |
| **Context blowup** | Uncapped tool output | `max_samples` cap + `truncated` flag | 03 |
| **Hallucinated answer** | Model lacks the data, invents it | `list_available_signals` + explicit refusal path | this doc |
| **Silent bad reasoning** | Point read treated as timeseries | `actual_sample_rate_hz` + description forbidding it | 03 |
| **Malformed final output** | Model returns prose where schema expected | Pydantic validation + retry | 06 |

That table is a strong interview artifact on its own. Most candidates can name one or two.

---

## LangGraph specifically

LangGraph models the agent as a **state graph**: nodes are steps, edges are transitions, and a shared state object flows through.

Why a graph rather than a `while` loop? Because you get explicit, inspectable control flow: conditional edges, checkpointing, interrupts for human review (which Doc 07 depends on), and a trace you can replay. A hand-rolled loop is fine to *understand* the mechanics — and you should write one once — but the graph is what makes Phase 4 possible.

### State

```python
from typing import Annotated, Literal
from langgraph.graph import add_messages
from pydantic import BaseModel


class CanopyState(BaseModel):
    messages: Annotated[list, add_messages]

    # Loop control
    iteration: int = 0
    max_iterations: int = 8

    # Provenance — everything the answer rests on
    tools_called: list[str] = []
    signals_touched: set[str] = set()
    findings: list[Finding] = []

    # Outcome
    answer: DiagnosticAnswer | None = None    # Doc 06
    refusal_reason: str | None = None
```

Note what's tracked beyond `messages`. `tools_called` and `signals_touched` are the **trace**. Doc 07's human reviewer needs to see *which tools ran and what they returned*, so a failure can be attributed to retrieval, tool use, or generation — not just observed as "the answer was bad." Build the trace in Phase 3; you will need it in Phase 4.

### Nodes

```
  agent      → LLM call with tools bound; emits answer or tool calls
  tools      → executes requested tools via the MCP client
  validate   → Pydantic-check the final answer (Doc 06)
  refuse     → construct a grounded refusal
```

### Edges

```
  START      → agent
  agent      → (conditional) tools | validate | refuse
  tools      → agent                     [the cycle]
  validate   → (conditional) END | agent [retry on schema failure]
  refuse     → END
```

The `tools → agent` edge is the loop. The `validate → agent` edge is the retry (Doc 06).

---

## Termination: three ways the loop ends

**1. The model answers.** It stops requesting tools and produces a final response. Normal path.

**2. The iteration cap trips.** `iteration >= max_iterations`. Do **not** simply error out. Take one final turn with the tools *unbound* and a system message saying: *"You have reached the tool-call limit. Answer using only what you have already retrieved, and explicitly state what you could not determine."*

This converts a hard failure into a degraded but honest answer. It is a meaningfully better design than raising, and it is the kind of detail that reads as production experience.

**3. The refusal path.** Covered next, and it's the one that matters most.

Set `max_iterations = 8` as a starting point. Log the actual distribution. If real questions routinely need six, your tools are too granular — consider a coarser tool.

---

## The refusal path — the most valuable thing in this project

Doc 01 established the structural fact: **OBD will never expose rear-camera activation timing.** The question is unanswerable with an OBD source, no matter how good the agent is.

The correct behavior is to say so. The failure mode — inventing a plausible latency figure — is exactly the danger these systems pose in a compliance context.

Note that most portfolios only demonstrate the happy path. This is the detail that reads as production thinking. It is also the concrete instantiation of the "trustworthiness" bullet on the job postings.

### How it is engineered (not hoped for)

The refusal must be **grounded in a tool result**, never in the model's self-knowledge. Models are bad at knowing what they don't know; they are much better at reading a list and noticing an absence.

Mechanism, in order:

1. **`list_available_signals` exists and is described as "call this first."** (Doc 03)
2. **The system prompt makes checking mandatory** before asserting any signal-specific claim.
3. **Error results carry `available_signals` and a `hint`**, so even a wrong guess produces the grounding data. (Doc 03, 04)
4. **`run_diagnostic_rules` returns `skipped`**, so "we didn't look" is distinguishable from "nothing is wrong." (Doc 03)
5. **The `refuse` node** produces a structured refusal citing the source and what it lacks.

### The refusal object

```python
class Refusal(BaseModel):
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
    suggestion: str | None
```

A refusal that says *"I can't answer that"* is weak. A refusal that says *"Rear-camera activation timing requires a body-control signal not present on an OBD-II connection, which exposes only emissions-related parameters. Connect a CAN log with an appropriate DBC. Available signals: EngineRPM, VehicleSpeed, ..."* is a **product**.

### Test it as a first-class case

```python
def test_refuses_camera_question_on_obd_source():
    result = agent.invoke(
        "Did the rear camera activate within 2 seconds in run 47?",
        source=ObdReader(),
    )
    assert result.answer is None
    assert result.refusal_reason == "signal_unavailable"
    assert "RearCamera" not in str(result.answer)   # no confabulated signal
```

This test should exist before the happy-path test. It is the one that would actually catch a regression that matters.

---

## The system prompt

The system prompt is not where you put domain knowledge — that lives in tools and rules. It is where you put **epistemic policy.**

Elements, each earning its place:

- **Role.** "You are a vehicle diagnostics assistant operating over a live data source."
- **Grounding mandate.** "Every factual claim about a signal must be supported by a tool result. Never state a value you did not retrieve."
- **Check-first rule.** "Before claiming a signal is unavailable, call `list_available_signals`. Before analyzing timing, verify `actual_sample_rate_hz` is not null."
- **Absence vs. negation.** "An empty findings list with a non-empty `skipped` list means the check was not performed, not that the system is healthy. Say so."
- **Refusal license.** "If the connected source cannot provide the required signal, refuse clearly and explain what source would be needed. A refusal is a correct answer."
- **Confidence discipline.** "Report `confidence: low` findings as tentative. Do not upgrade them."

That fifth bullet — explicitly licensing refusal — matters. Models are trained toward helpfulness and will strain to produce *something*. Telling it that refusal is a success state changes behavior measurably.

Keep it short. A system prompt that restates every tool description is redundant and eats context. Say the policy; let the tools say the mechanics.

---

## Multi-turn state

The postings name "context and conversation state management" explicitly. The interesting question is what persists across turns.

- **`messages`** — obviously, subject to a windowing strategy once long.
- **`signals_touched`** — lets the agent say "as I mentioned, coolant temp was elevated" without re-querying.
- **`findings`** — accumulated; a follow-up question shouldn't re-run rules.
- **Session time range** — if turn 1 established "run 47," turn 3 shouldn't ask again.

**What must not persist:** raw sample arrays. Summarize them into findings and discard. This is context management as an active discipline, not an accident.

A concrete policy worth implementing and describing: when `messages` exceeds a token budget, compact the oldest tool results into a one-line summary (`"get_signal(EngineRPM, t0..t1) → 200 samples, 800–3200 rpm, no anomalies"`) and drop the arrays. The findings survive; the bulk does not.

---

## Write the loop by hand once, before using LangGraph

Non-negotiable, because it is the self-test from Doc 00.

Implement a `while` loop: call the model with tools, check for tool calls, execute them, append results, repeat until no tool calls or the cap trips. Fifty lines. Then throw it away and use LangGraph.

Doing this is the difference between *"I used LangGraph"* and *"I understand what LangGraph is doing for me."* Only one of those survives a follow-up question. Keep the hand-rolled version in the repo as `agent/reference_loop.py` with a comment explaining why it's there — reviewers notice.

---

## Definition of done — Phase 3

- [ ] Hand-rolled loop written, understood, committed as reference
- [ ] LangGraph graph with `agent`, `tools`, `validate`, `refuse` nodes
- [ ] Iteration cap with a **forced-answer degraded turn**, not an exception
- [ ] Refusal path grounded in `list_available_signals`, not model self-knowledge
- [ ] `Refusal` object names the missing signal and the source that would provide it
- [ ] Refusal test written **before** the happy-path test
- [ ] Trace captured: `tools_called`, `signals_touched`, findings
- [ ] Point-read guard: agent does not perform timing analysis on OBD data
- [ ] Context compaction policy implemented for long conversations
- [ ] Seam test still passes
- [ ] **You can rebuild the loop from a blank file without looking**

That last box is the real gate. If you cannot, you have found exactly what to study, and this should not go on your resume yet.

---

## Questions to be ready for

> *"Walk me through what happens when the agent uses a tool."*

The model receives tool schemas and descriptions alongside the conversation. It emits a structured tool-call request — it does not execute anything. My code executes the tool, appends the result to the conversation as a tool-result message, and calls the model again. It now sees the result and decides whether to call another tool or answer. The loop continues until it answers or hits my iteration cap, at which point I take one final turn with tools unbound and ask it to answer honestly from what it has.

> *"What happens if two tools return conflicting data?"*

Both results land in context and the model reconciles them. That is the honest answer, and it is also why every `Finding` carries `evidence` — the model can cite which samples support which claim, and a human reviewer can adjudicate. I don't silently pick a winner in code, because that hides the conflict from the reviewer who needs to see it.

> *"How do you stop it looping forever?"*

Hard iteration cap at eight. But rather than erroring, the cap triggers a final turn with tools unbound and an instruction to answer from retrieved data and explicitly state what could not be determined. A degraded honest answer beats a stack trace.

> *"How do you know it isn't hallucinating?"*

Structurally, I make the refusal path easier than confabulation. There is a cheap `list_available_signals` tool the system prompt requires it to call before asserting availability; every error result carries the available-signal list; and `run_diagnostic_rules` distinguishes "skipped" from "clean." The model doesn't have to know what it doesn't know — it reads a list and notices an absence. Then I verify it with an eval set built from real observed failures, which is Phase 4.
