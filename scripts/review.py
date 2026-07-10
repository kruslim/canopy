"""Step 2 of the eval loop — human review of captured traces (docs/07).

Walks you through each captured trace, shows the **full trace** (not just the answer), and
records your verdict as a structured ``ReviewFeedback`` — the error taxonomy, not a thumbs-down.
These labels are the ground truth the judge is calibrated against.

Needs no API key: you are reviewing traces already captured to disk. Records to a JSONL file so
a second pass (a week later) can be scored against the first for self-agreement.

    .venv/bin/python scripts/review.py                         # writes reviews_pass_a.jsonl
    .venv/bin/python scripts/review.py --out reviews_pass_b.jsonl   # a week later, second pass

For each trace: [a]pprove if sound, or [r]eject and name the error type(s). Ctrl-C to stop; your
progress is saved as you go and already-reviewed trace ids are skipped on the next run.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from canopy.evals.schemas import ErrorType, EvalCase, ReviewFeedback, Severity
from canopy.evals.store import append_case
from canopy.evals.trace import Trace
from canopy.readers.fixtures import build_fixture, fixture_names

_ROOT = Path(__file__).resolve().parent.parent
_TRACES = _ROOT / "data" / "evals" / "traces"
_CASES_PATH = _TRACES.parent / "regression_cases.jsonl"  # persisted from_review cases

_ERROR_TYPES = list(ErrorType)
_SEVERITIES = list(Severity)


def _already_reviewed(out_path: Path) -> set[str]:
    if not out_path.exists():
        return set()
    return {
        json.loads(line)["trace_id"] for line in out_path.read_text().splitlines() if line.strip()
    }


def _pick_error_types() -> list[ErrorType]:
    print("  error types (comma-separated numbers):")
    for i, et in enumerate(_ERROR_TYPES):
        print(f"    {i}: {et.value}")
    raw = input("  > ").strip()
    picks = []
    for tok in raw.split(","):
        tok = tok.strip()
        if tok.isdigit() and 0 <= int(tok) < len(_ERROR_TYPES):
            picks.append(_ERROR_TYPES[int(tok)])
    return picks


def _pick_severity() -> Severity | None:
    labels = " / ".join(f"{i}:{s.value}" for i, s in enumerate(_SEVERITIES))
    raw = input(f"  severity ({labels}, blank=none): ").strip()
    return _SEVERITIES[int(raw)] if raw.isdigit() and 0 <= int(raw) < len(_SEVERITIES) else None


def _csv(prompt: str) -> list[str]:
    raw = input(prompt).strip()
    return [tok.strip() for tok in raw.split(",") if tok.strip()]


def _mint_case(trace: Trace, error_types: list[ErrorType]) -> EvalCase | None:
    """Turn a rejected trace into a permanent ``from_review`` regression case.

    A regression case must be *replayable*, so it names a deterministic fixture (resolved below
    the seam) rather than reusing the live source the trace ran against. The reviewer supplies
    the structural ground truth — the outcome the agent should have produced and the signals it
    must (or must not) cite — which the runner then asserts against every future agent version.
    The EvalCase validators reject a contradictory spec, so a bad case fails here, not in CI.
    """
    if input("  mint a regression case from this reject? [y/N]: ").strip().lower() != "y":
        return None

    fixture = input(f"  fixture that reproduces this ({', '.join(fixture_names())}): ").strip()
    try:
        build_fixture(fixture)
    except KeyError as e:
        print(f"  {e}  → skipping case.")
        return None

    outcome = (
        input("  expected outcome [answer/refusal] (blank=answer): ").strip().lower() or "answer"
    )
    if outcome not in ("answer", "refusal"):
        print(f"  '{outcome}' is not a valid outcome → skipping case.")
        return None

    kwargs: dict = dict(
        case_id=f"from_review_{trace.trace_id}",
        question=trace.question,
        source_fixture=fixture,
        expected_outcome=outcome,
        origin="from_review",
        source_trace_id=trace.trace_id,
        error_types_observed=error_types,
    )
    if outcome == "refusal":
        reason = input("  expected refusal reason (blank=none): ").strip() or None
        if reason:
            kwargs["expected_refusal_reason"] = reason
        kwargs["must_not_cite_signals"] = _csv(
            "  signals it must NOT cite (comma-sep, blank=none): "
        )
    else:
        kwargs["must_cite_signals"] = _csv("  signals it MUST cite (comma-sep, blank=none): ")
        kwargs["must_not_cite_signals"] = _csv(
            "  signals it must NOT cite (comma-sep, blank=none): "
        )
        kwargs["must_mention_skipped"] = (
            input("  must the answer flag skipped rules? [y/N]: ").strip().lower() == "y"
        )

    try:
        case = EvalCase(**kwargs)
    except ValueError as e:
        print(f"  case rejected by validator: {e}\n  → skipping case.")
        return None

    if append_case(_CASES_PATH, case):
        print(f"  minted → {case.case_id} ({_CASES_PATH.relative_to(_ROOT)})")
    else:
        print(f"  {case.case_id} already exists in the store → not duplicated.")
    return case


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out", default="reviews_pass_a.jsonl", help="JSONL file under data/evals/."
    )
    parser.add_argument("--reviewer", default="human", help="Reviewer id recorded on each label.")
    args = parser.parse_args()

    out_path = _TRACES.parent / args.out
    if not _TRACES.exists() or not any(_TRACES.glob("*.json")):
        print(f"No captured traces in {_TRACES}. Run scripts/capture.py first.")
        return 1

    done = _already_reviewed(out_path)
    trace_files = sorted(_TRACES.glob("*.json"))
    pending = [f for f in trace_files if f.stem not in done]
    print(f"{len(pending)} trace(s) to review ({len(done)} already done) → {out_path.name}\n")

    with out_path.open("a") as out:
        for f in pending:
            trace = Trace.model_validate_json(f.read_text())
            print("=" * 70)
            print(trace.render())
            print("-" * 70)
            verdict = input("  verdict [a=approve / r=reject / s=skip]: ").strip().lower()
            if verdict == "s":
                continue
            error_types: list[ErrorType] = []
            severity = None
            note = None
            if verdict == "r":
                error_types = _pick_error_types()
                if not error_types:
                    print("  (no error type chosen → recording as approve instead)")
                    verdict = "a"
                else:
                    severity = _pick_severity()
                    note = input("  note (optional): ").strip() or None

            feedback = ReviewFeedback(
                trace_id=trace.trace_id,
                reviewer_id=args.reviewer,
                verdict="approve" if verdict == "a" else "reject",
                error_types=error_types,
                severity=severity,
                reviewer_note=note,
                reviewed_at=datetime.now(),
            )
            out.write(feedback.model_dump_json() + "\n")
            out.flush()
            print(f"  recorded: {feedback.verdict} {[e.value for e in error_types]}")

            # A reject is the flywheel's raw material: offer to turn it into a permanent
            # regression case so the same failure blocks a future merge.
            if feedback.verdict == "reject":
                _mint_case(trace, error_types)
            print()

    print(f"\ndone → {out_path.relative_to(_ROOT)}")
    print(
        "next: run the judge (capture --judge) then  .venv/bin/python scripts/calibrate.py --real"
    )
    print("      and  .venv/bin/python scripts/eval.py  to replay minted cases + diff the baseline")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
