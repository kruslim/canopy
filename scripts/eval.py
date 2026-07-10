"""Run the regression suite against a live agent, and track it run-over-run (docs/07).

The hard-assertion tier also runs hermetically in CI (``tests/test_eval_runner.py`` drives a
scripted model, no key). This script is the *live* replay: it points the seed cases — plus
every ``from_review`` case reviewers have minted (``data/evals/regression_cases.jsonl``) — at
a real LLM, so you can watch the current agent against every defense, and optionally judge
each trace.

It is also the ratchet. Each run is diffed against the last accepted **baseline**
(``data/evals/baseline.json``) and appended to the **history** trend line
(``data/evals/history.jsonl``):

    .venv/bin/python scripts/eval.py                       # run + diff vs baseline
    .venv/bin/python scripts/eval.py --judge               # also score each trace
    .venv/bin/python scripts/eval.py --update-baseline     # accept this run as the new bar

With a baseline present, the exit code gates on **regressions only** — a case that was already
failing (a known bug you haven't fixed yet) does not block, but a case that *was* passing and
now fails does. Without a baseline, every case must pass. So a release is blocked exactly when
this run is worse than the last one you accepted.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

# Reuse the exact provider wiring the ask CLI uses, so live evals and live asks agree.
from ask import _build_model  # type: ignore
from dotenv import load_dotenv

from canopy.evals.judge import judge_trace
from canopy.evals.runner import RegressionReport, run_case
from canopy.evals.store import load_regression_cases
from canopy.evals.tracking import HistoryRow, append_history, load_baseline, save_baseline

_ROOT = Path(__file__).resolve().parent.parent
_EVALS = _ROOT / "data" / "evals"
_CASES_PATH = _EVALS / "regression_cases.jsonl"  # persisted from_review cases
_BASELINE_PATH = _EVALS / "baseline.json"
_HISTORY_PATH = _EVALS / "history.jsonl"


def _git_sha() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        return out.stdout.strip() or None
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=("gemini", "anthropic"), default="gemini")
    parser.add_argument("--model", default=None)
    parser.add_argument(
        "--judge", action="store_true", help="Also score each trace with the LLM-judge."
    )
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="Accept this run's pass/fail as the new baseline every future run is diffed "
        "against. This is how you deliberately move the bar — e.g. after fixing a bug and "
        "landing the from_review case that guards it.",
    )
    args = parser.parse_args()

    model = _build_model(args.provider, args.model)
    cases = load_regression_cases(_CASES_PATH)

    results = []
    judge_flags: Counter[str] = Counter()
    for case in cases:
        trace, result = run_case(case, model)
        results.append(result)
        mark = "PASS" if result.passed else "FAIL"
        tag = "" if case.origin == "handwritten" else "  (from_review)"
        print(f"[{mark}] {case.case_id}{tag}  ({trace.outcome})")
        for failure in result.failures:
            print(f"        ✗ {failure.name}: {failure.detail}")
        if args.judge:
            verdict = judge_trace(model, trace)
            for e in verdict.error_types:
                judge_flags[e.value] += 1
            flags = ", ".join(e.value for e in verdict.error_types) or "sound"
            print(f"        judge: {flags}")

    report = RegressionReport(results=results)
    print(
        f"\n{report.n_passed}/{report.n_total} hard-assertion cases passed ({report.pass_rate:.0%})"
    )

    # Diff against the last accepted bar — the "are we improving?" signal.
    baseline = load_baseline(_BASELINE_PATH)
    regressions = report.regressions(baseline)
    newly_fixed = report.newly_fixed(baseline)
    if baseline:
        if regressions:
            print(f"\n⚠ REGRESSED vs baseline ({len(regressions)}): {', '.join(regressions)}")
        if newly_fixed:
            print(f"✓ NEWLY FIXED vs baseline ({len(newly_fixed)}): {', '.join(newly_fixed)}")
        if not regressions and not newly_fixed:
            print("\n= no change vs baseline")
    else:
        print("\n(no baseline yet — run with --update-baseline to set the bar)")

    # Record this run on the trend line, whether or not we accept it as the new baseline.
    append_history(
        _HISTORY_PATH,
        HistoryRow(
            timestamp=datetime.now().isoformat(timespec="seconds"),
            git_sha=_git_sha(),
            provider=args.provider,
            model=args.model,
            n_passed=report.n_passed,
            n_total=report.n_total,
            pass_rate=report.pass_rate,
            regressions=regressions,
            newly_fixed=newly_fixed,
            judge_error_types=dict(judge_flags),
        ),
    )

    if args.update_baseline:
        save_baseline(_BASELINE_PATH, report)
        print(
            f"\nbaseline updated → {_BASELINE_PATH.relative_to(_ROOT)}  "
            f"({report.n_passed}/{report.n_total})"
        )
        # An explicit accept succeeds by definition — you are declaring this the new bar.
        return 0

    # Gate. With a baseline, block only on regressions (a case that was already failing must
    # not block forever — only a newly broken one does). Without a baseline, everything passes.
    if baseline:
        return 1 if regressions else 0
    return 0 if report.n_passed == report.n_total else 1


if __name__ == "__main__":
    sys.exit(main())
