"""The review gate — a LangGraph interrupt, and the flywheel's hinge (docs/07).

When the agent produces a consequential output it does not ship; it lands in a queue and waits
for a human.

    run_agent ──► human_review (INTERRUPT) ──┬── approve ──► END
                                             ├── correct ──► END (+ from_review eval case)
                                             └── reject  ──► run_agent   [retry with feedback]

This is the reason Doc 05 built a *graph* rather than a ``while`` loop: graphs support
interrupts — pause execution, persist state through a checkpointer, resume later on human
input. A hand-rolled loop cannot pause and be resumed by an external reviewer without
re-running everything.

The interrupt payload is the **full trace**, not just the answer (``Trace.render()`` +
structured dump), because trace visibility is what lets a reviewer attribute a failure to
retrieval, tool use, or generation. A ``correct`` verdict does not merely fix one answer — it
mints a permanent ``from_review`` regression case, which is the moment a one-time human
correction becomes a standing defense.

The gate runs against a *named fixture* (resolved below the seam), never an arbitrary reader:
only a reproducible source can become a replayable regression case, so the flywheel is closed
by construction.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from pydantic import BaseModel, Field

from canopy.agent.graph import run_agent
from canopy.evals.schemas import EvalCase, ReviewFeedback
from canopy.evals.trace import Trace
from canopy.readers.fixtures import build_fixture

# A reviewer: shown the interrupt payload (rendered trace + structured dump), returns a
# ReviewFeedback-shaped dict. In production this is a UI; in tests and scripts it is a callable.
Reviewer = Callable[[dict[str, Any]], dict[str, Any]]


class ReviewState(BaseModel):
    question: str
    source_fixture: str
    max_iterations: int = 8

    # Reject-retry control. A rejection re-runs the agent with the reviewer's note appended as
    # guidance; bounded so a stubborn disagreement can't loop forever.
    reject_count: int = 0
    max_rejects: int = 1
    feedback_notes: list[str] = Field(default_factory=list)

    trace: Trace | None = None
    feedback: ReviewFeedback | None = None
    verdict: str | None = None
    eval_case: EvalCase | None = None  # minted by a 'correct' verdict


def _augmented_question(state: ReviewState) -> str:
    if not state.feedback_notes:
        return state.question
    guidance = "\n".join(f"- {note}" for note in state.feedback_notes)
    return (
        f"{state.question}\n\n"
        f"A reviewer rejected your previous attempt with this guidance:\n{guidance}\n"
        f"Address it in this answer."
    )


def build_review_graph(model: Any) -> Any:
    """Compile the review gate. ``model`` is any chat model (or a scripted fake in tests)."""

    def run_agent_node(state: ReviewState) -> dict:
        # On a reject re-entry, feedback carries the note; fold it into guidance, count the
        # rejection, and clear it so the next review starts from a clean slate.
        notes = list(state.feedback_notes)
        reject_count = state.reject_count
        if state.feedback is not None and state.feedback.verdict == "reject":
            reject_count += 1
            if state.feedback.reviewer_note:
                notes.append(state.feedback.reviewer_note)

        pending = ReviewState(**{**state.model_dump(), "feedback_notes": notes})
        reader = build_fixture(state.source_fixture)
        result = run_agent(
            _augmented_question(pending), reader, model, max_iterations=state.max_iterations
        )
        trace = Trace.from_state(result, trace_id=f"review_{state.source_fixture}_{reject_count}")
        return {
            "trace": trace,
            "feedback_notes": notes,
            "reject_count": reject_count,
            "feedback": None,
            "verdict": None,
        }

    def human_review_node(state: ReviewState) -> dict:
        # The graph pauses here. The checkpointer persists state; the reviewer is handed the
        # full trace and, whenever they get to it, resumes with a verdict.
        assert state.trace is not None
        resume = interrupt(
            {
                "trace_id": state.trace.trace_id,
                "render": state.trace.render(),
                "trace": state.trace.model_dump(mode="json"),
            }
        )
        feedback = ReviewFeedback.model_validate(resume)
        return {"feedback": feedback, "verdict": feedback.verdict}

    def route_from_review(state: ReviewState) -> str:
        verdict = state.verdict
        if verdict == "approve":
            return END
        if verdict == "correct":
            return "record_correction"
        # reject: retry only while budget remains, else give up and keep the last trace.
        if state.reject_count < state.max_rejects:
            return "run_agent"
        return END

    def record_correction_node(state: ReviewState) -> dict:
        # A correction becomes a permanent from_review regression case. The reviewer's
        # corrected answer supplies the ground truth: the signals it cites become the
        # must_cite assertions a future agent version is held to.
        assert state.trace is not None and state.feedback is not None
        corrected = state.feedback.corrected_answer
        cited = sorted(
            {c.signal for claim in (corrected.claims if corrected else []) for c in claim.citations}
        )
        case = EvalCase(
            case_id=f"from_review_{state.trace.trace_id}",
            question=state.question,
            source_fixture=state.source_fixture,
            expected_outcome="answer",
            must_cite_signals=cited,
            origin="from_review",
            source_trace_id=state.trace.trace_id,
            error_types_observed=list(state.feedback.error_types),
        )
        return {"eval_case": case}

    graph: StateGraph = StateGraph(ReviewState)
    graph.add_node("run_agent", run_agent_node)
    graph.add_node("human_review", human_review_node)
    graph.add_node("record_correction", record_correction_node)

    graph.add_edge(START, "run_agent")
    graph.add_edge("run_agent", "human_review")
    graph.add_conditional_edges("human_review", route_from_review)
    graph.add_edge("record_correction", END)

    return graph.compile(checkpointer=MemorySaver())


def run_review(
    model: Any,
    source_fixture: str,
    question: str,
    reviewer: Reviewer,
    *,
    thread_id: str = "review",
    max_iterations: int = 8,
    max_rejects: int = 1,
) -> ReviewState:
    """Drive one question through the review gate to a terminal verdict.

    ``reviewer`` is called once per interrupt with the trace payload and returns a
    ReviewFeedback-shaped dict. Returns the terminal ``ReviewState`` — ``verdict`` set, and
    ``eval_case`` populated when the verdict was ``correct``.
    """
    graph = build_review_graph(model)
    config = {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": 4 * max_iterations + 24,
    }
    state = ReviewState(
        question=question,
        source_fixture=source_fixture,
        max_iterations=max_iterations,
        max_rejects=max_rejects,
    )
    result: dict = graph.invoke(state, config)
    while "__interrupt__" in result:
        payload = result["__interrupt__"][0].value
        feedback = reviewer(payload)
        result = graph.invoke(Command(resume=feedback), config)
    return ReviewState.model_validate(result)
