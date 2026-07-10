"""The growing half of the eval set — persisted ``from_review`` cases (docs/07).

``SEED_CASES`` are the defenses you could imagine on day one; they live in code. The valuable
cases arrive later, one reviewed failure at a time, and they must survive between runs — so
they live on disk as JSONL, one ``EvalCase`` per line, appended by the review tool and loaded
by the runner alongside the seeds.

This is the disk half of the flywheel: ``record_correction`` (the review gate) and
``scripts/review`` mint a ``from_review`` case, ``append_case`` writes it here, and
``load_regression_cases`` hands the runner seeds + persisted, so a corrected failure becomes a
standing regression test that a future agent version is held to.

Like ``tracking.py``, this is pure I/O over a caller-supplied path — the scripts own where the
file lives.
"""

from __future__ import annotations

from pathlib import Path

from canopy.evals.cases import SEED_CASES
from canopy.evals.schemas import EvalCase


def load_persisted_cases(path: Path) -> list[EvalCase]:
    """The ``from_review`` cases minted so far, or empty if none exist yet."""
    if not path.exists():
        return []
    return [
        EvalCase.model_validate_json(line) for line in path.read_text().splitlines() if line.strip()
    ]


def append_case(path: Path, case: EvalCase) -> bool:
    """Persist one minted case. Returns ``False`` (and writes nothing) if its id already
    exists — a regression case is a permanent fixture, not something a second review of the
    same trace should duplicate."""
    if case.case_id in {c.case_id for c in load_persisted_cases(path)}:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(case.model_dump_json() + "\n")
    return True


def load_regression_cases(path: Path) -> tuple[EvalCase, ...]:
    """The full suite the runner replays: the hand-seeded defenses plus every persisted
    ``from_review`` case. Seeds win on an id collision — a persisted case never shadows a
    seed, so the built-in defenses can't be silently overridden from disk."""
    seed_ids = {c.case_id for c in SEED_CASES}
    persisted = [c for c in load_persisted_cases(path) if c.case_id not in seed_ids]
    return (*SEED_CASES, *persisted)
