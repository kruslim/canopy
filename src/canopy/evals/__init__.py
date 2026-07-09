"""L6 — Evals & human-in-the-loop (above the seam) — docs/07.

The review gate, the structured feedback taxonomy, the eval set that grows from corrections,
the regression runner, and the calibrated LLM-judge. Nothing here names the data source: eval
cases select a fixture by *name*, resolved to a concrete reader below the seam
(``readers.fixtures``), so this layer never learns which concretion, seed, or channel subset
backed a run (Constraint 1, enforced by ``tests/test_seam.py``).
"""

from __future__ import annotations

from canopy.evals.assertions import AssertionResult, CaseResult, check_case
from canopy.evals.cases import SEED_CASES, SEED_CASES_BY_ID
from canopy.evals.judge import (
    JudgeVerdict,
    build_calibration_report,
    judge_trace,
    labels_from_feedback,
    labels_from_judge,
    score_traces,
    set_agreement,
)
from canopy.evals.review import ReviewState, build_review_graph, run_review
from canopy.evals.runner import RegressionReport, run_case, run_regression
from canopy.evals.schemas import (
    CalibrationReport,
    ErrorType,
    EvalCase,
    ReviewFeedback,
    Severity,
)
from canopy.evals.trace import ToolInvocation, Trace

__all__ = [
    "AssertionResult",
    "CaseResult",
    "check_case",
    "SEED_CASES",
    "SEED_CASES_BY_ID",
    "JudgeVerdict",
    "build_calibration_report",
    "judge_trace",
    "labels_from_feedback",
    "labels_from_judge",
    "score_traces",
    "set_agreement",
    "ReviewState",
    "build_review_graph",
    "run_review",
    "RegressionReport",
    "run_case",
    "run_regression",
    "CalibrationReport",
    "ErrorType",
    "EvalCase",
    "ReviewFeedback",
    "Severity",
    "ToolInvocation",
    "Trace",
]
