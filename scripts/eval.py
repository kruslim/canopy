"""Run the regression suite against a live agent (docs/07).

The hard-assertion tier also runs hermetically in CI (``tests/test_eval_runner.py`` drives a
scripted model, no key). This script is the *live* replay: it points the same seed cases at a
real LLM so you can watch the current agent's behavior against every seeded defense, and
optionally have the LLM-judge score each trace.

    .venv/bin/python scripts/eval.py
    .venv/bin/python scripts/eval.py --provider anthropic --model claude-sonnet-4-6 --judge

Exits non-zero if any hard assertion fails, so it can gate a release when a key is available.
"""

from __future__ import annotations

import argparse
import sys

# Reuse the exact provider wiring the ask CLI uses, so live evals and live asks agree.
from ask import _build_model  # type: ignore
from dotenv import load_dotenv

from canopy.evals.cases import SEED_CASES
from canopy.evals.judge import judge_trace
from canopy.evals.runner import run_case


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=("gemini", "anthropic"), default="gemini")
    parser.add_argument("--model", default=None)
    parser.add_argument(
        "--judge", action="store_true", help="Also score each trace with the LLM-judge."
    )
    args = parser.parse_args()

    model = _build_model(args.provider, args.model)

    n_pass = 0
    for case in SEED_CASES:
        trace, result = run_case(case, model)
        mark = "PASS" if result.passed else "FAIL"
        n_pass += int(result.passed)
        print(f"[{mark}] {case.case_id}  ({trace.outcome})")
        for failure in result.failures:
            print(f"        ✗ {failure.name}: {failure.detail}")
        if args.judge:
            verdict = judge_trace(model, trace)
            flags = ", ".join(e.value for e in verdict.error_types) or "sound"
            print(f"        judge: {flags}")

    total = len(SEED_CASES)
    print(f"\n{n_pass}/{total} hard-assertion cases passed")
    return 0 if n_pass == total else 1


if __name__ == "__main__":
    sys.exit(main())
