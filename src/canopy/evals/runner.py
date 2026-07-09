"""The regression runner — replay each case against the current agent (docs/07).

    eval set ──► run each case against the agent
                          │
                          ▼
                deterministic fixture (readers.fixtures)
                          │
                          ▼
                assert: outcome, citations, refusal reason  (assertions.py)
                          │
                          ▼
                report: pass rate, regressions vs. last run

This closes the flywheel: a production failure, corrected once by a human, becomes a
``from_review`` case here and permanently defends the codebase. A PR that reintroduces the old
failure flips that case to failing and the CI hard-assertion test blocks the merge.

The runner is model-agnostic: it takes a ``model_for`` factory so the same code runs a live
LLM (one model reused for every case) or a hermetic scripted model per case in CI. The
determinism the suite relies on lives in the *fixture* (the data), which is why the assertions
are stable even when the model is not.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from pydantic import BaseModel, Field

from canopy.agent.graph import run_agent
from canopy.evals.assertions import CaseResult, check_case
from canopy.evals.schemas import EvalCase
from canopy.evals.trace import Trace
from canopy.readers.fixtures import build_fixture

# A factory that yields the model to run a given case against. A live run returns the same
# model for every case (``lambda _case: chat_model``); a hermetic test returns a scripted model
# tailored to each case's expected tool sequence.
ModelFor = Callable[[EvalCase], Any]


class RegressionReport(BaseModel):
    """The outcome of one regression run over a set of cases."""

    results: list[CaseResult] = Field(default_factory=list)

    @property
    def n_total(self) -> int:
        return len(self.results)

    @property
    def n_passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def pass_rate(self) -> float:
        return self.n_passed / self.n_total if self.results else 0.0

    def baseline_map(self) -> dict[str, bool]:
        """A ``{case_id: passed}`` snapshot, to persist and diff a future run against."""
        return {r.case_id: r.passed for r in self.results}

    def regressions(self, baseline: dict[str, bool]) -> list[str]:
        """Cases that passed in ``baseline`` but fail now — the merge-blockers."""
        return [r.case_id for r in self.results if baseline.get(r.case_id) and not r.passed]

    def newly_fixed(self, baseline: dict[str, bool]) -> list[str]:
        """Cases that failed in ``baseline`` and pass now — the flywheel paying off."""
        return [r.case_id for r in self.results if r.passed and baseline.get(r.case_id) is False]

    def render(self) -> str:
        lines = [f"regression: {self.n_passed}/{self.n_total} passed ({self.pass_rate:.0%})", ""]
        for r in self.results:
            mark = "PASS" if r.passed else "FAIL"
            lines.append(f"  [{mark}] {r.case_id}  ({r.outcome})")
            for f in r.failures:
                lines.append(f"         ✗ {f.name}: {f.detail}")
        return "\n".join(lines)


def run_case(case: EvalCase, model: Any, *, max_iterations: int = 8) -> tuple[Trace, CaseResult]:
    """Run one case end to end: fixture → agent → trace → hard assertions."""
    reader = build_fixture(case.source_fixture)
    state = run_agent(case.question, reader, model, max_iterations=max_iterations)
    # A stable trace_id keyed to the case keeps regression baselines diff-able across runs.
    trace = Trace.from_state(state, trace_id=f"trace_{case.case_id}")
    return trace, check_case(case, trace)


def run_regression(
    cases: Sequence[EvalCase],
    model_for: ModelFor,
    *,
    max_iterations: int = 8,
) -> RegressionReport:
    """Replay ``cases`` against the agent and score each with hard assertions."""
    results = [run_case(case, model_for(case), max_iterations=max_iterations)[1] for case in cases]
    return RegressionReport(results=results)
