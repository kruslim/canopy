"""Run-over-run tracking for the regression suite — the ratchet's memory (docs/07).

The regression *report* (``runner.py``) already knows how to diff itself against a prior
baseline (``regressions``, ``newly_fixed``). What it lacked was a place to *keep* that
baseline and a record of every run, so "are we improving?" is a file you can tail instead of
a number you hold in your head. This module is that memory.

Two artifacts, both plain JSON on disk:

- **baseline** (``baseline.json``) — a ``{case_id: passed}`` snapshot of the last *accepted*
  run. The next run diffs against it: a case that passed here but fails now is a regression
  (it blocks); a case that failed here but passes now is the flywheel paying off. You move the
  bar deliberately with ``--update-baseline``, never silently.
- **history** (``history.jsonl``) — one appended row per run: when, which commit, the pass
  rate, and (when the judge ran) which error types it flagged. This is the trend line.

Everything here is pure I/O over paths the caller supplies — no clock, no git, no network — so
it is trivially unit-testable and the scripts stay the only place that touches the
environment. The caller stamps the timestamp and git SHA and hands them in.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

from canopy.evals.runner import RegressionReport


def load_baseline(path: Path) -> dict[str, bool]:
    """The last accepted ``{case_id: passed}`` snapshot, or empty if there is none yet."""
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def save_baseline(path: Path, report: RegressionReport) -> None:
    """Accept this run as the new bar every future run is diffed against."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report.baseline_map(), indent=2, sort_keys=True) + "\n")


class HistoryRow(BaseModel):
    """One row of the trend line — a single regression run, stamped for later reading.

    ``judge_error_types`` is optional: a run without ``--judge`` still records its pass rate,
    it just leaves the judge column empty. Judge *agreement* is deliberately absent — that is
    the calibration harness's number (it needs human labels), not something an eval run knows.
    """

    timestamp: str  # ISO-8601, supplied by the caller (the script owns the clock)
    git_sha: str | None = None
    provider: str | None = None
    model: str | None = None

    n_passed: int
    n_total: int
    pass_rate: float

    # The diff against the baseline this run was measured against — the "did we move?" signal.
    regressions: list[str] = Field(default_factory=list)
    newly_fixed: list[str] = Field(default_factory=list)

    # How many traces the judge flagged with each error type this run (only when --judge ran).
    judge_error_types: dict[str, int] = Field(default_factory=dict)


def append_history(path: Path, row: HistoryRow) -> None:
    """Append one run to the trend line. ``tail history.jsonl`` is the chart."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(row.model_dump_json() + "\n")


def load_history(path: Path) -> list[HistoryRow]:
    """Every recorded run, oldest first."""
    if not path.exists():
        return []
    return [
        HistoryRow.model_validate_json(line)
        for line in path.read_text().splitlines()
        if line.strip()
    ]
