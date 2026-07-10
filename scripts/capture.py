"""Step 1 of the eval loop — capture real agent traces to disk (docs/07).

Runs the live agent over a set of questions against the configured data source and writes each
run's ``Trace`` to ``data/evals/traces/<trace_id>.json``. These persisted traces are the raw
material the human reviews (``scripts/review.py``) and the judge scores — the real data that
turns the seeded calibration number into a trustworthy one.

Needs a provider key in ``.env`` (copy ``.env.example``); the agent calls a real model.

    .venv/bin/python scripts/capture.py                       # default question set
    .venv/bin/python scripts/capture.py --questions qs.txt    # one question per line
    .venv/bin/python scripts/capture.py --judge               # also record judge labels
"""

from __future__ import annotations

import argparse
from pathlib import Path

from ask import _build_model  # same provider wiring as the ask CLI
from dotenv import load_dotenv

from canopy.agent.graph import run_agent
from canopy.evals.judge import judge_trace
from canopy.evals.trace import Trace
from canopy.readers import build_reader

_ROOT = Path(__file__).resolve().parent.parent
_TRACES = _ROOT / "data" / "evals" / "traces"
_JUDGE_LABELS = _ROOT / "data" / "evals" / "judge_labels.jsonl"

# A spread of answerable and unanswerable questions, so a capture exercises both the answer and
# the grounded-refusal paths. Override with --questions for your own set.
_DEFAULT_QUESTIONS = [
    "Did engine speed stay within its normal operating range?",
    "Is the engine overheating, and what is the evidence?",
    "How is engine load behaving over the session?",
    "What was the coolant temperature trend?",
    "Are there any cooling-system problems in this session?",
    "Did the rear camera activate within 2 seconds of reverse?",  # unanswerable → refusal
    "What is the tire pressure right now?",  # unanswerable → refusal
    "Summarize the session.",
]


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=("gemini", "anthropic"), default="gemini")
    parser.add_argument("--model", default=None)
    parser.add_argument("--questions", type=Path, default=None, help="File: one question per line.")
    parser.add_argument(
        "--judge", action="store_true", help="Also score each trace with the judge."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing capture. A capture regenerates every trace from a LIVE "
        "model, so re-running it silently replaces the traces your reviews are keyed to and "
        "desyncs the eval set. This flag DISCARDS the current traces and judge labels and "
        "starts clean; it is required once traces already exist.",
    )
    args = parser.parse_args()

    if args.questions is not None:
        questions = [q.strip() for q in args.questions.read_text().splitlines() if q.strip()]
    else:
        questions = _DEFAULT_QUESTIONS

    # A frozen trace set is the unit of review: traces, human labels, and judge labels must all
    # describe the SAME run. Because the agent is non-deterministic, re-capturing over an existing
    # set is the one action that breaks that invariant — so refuse it unless --force is explicit.
    _TRACES.mkdir(parents=True, exist_ok=True)
    existing = sorted(_TRACES.glob("*.json"))
    if existing and not args.force:
        raise SystemExit(
            f"{len(existing)} trace(s) already in {_TRACES.relative_to(_ROOT)}. Re-capturing "
            "regenerates every trace from a live model, which would overwrite the traces your "
            "reviews are keyed to and silently desync the eval set. Review the existing traces "
            "with scripts/review.py, or pass --force to discard this capture and start clean."
        )
    if args.force:
        for f in existing:
            f.unlink()
        _JUDGE_LABELS.unlink(missing_ok=True)  # a fresh capture owns a fresh, matching label set

    model = _build_model(args.provider, args.model)

    # "w", not "a": one capture run produces exactly one complete, self-consistent label set.
    # Appending was what stacked two runs' labels into the same file.
    with _JUDGE_LABELS.open("w") if args.judge else _nullctx() as judge_out:
        for i, question in enumerate(questions):
            reader = build_reader()  # fresh reader per run; source chosen by CANOPY_SOURCE
            trace_id = f"cap_{i:03d}"
            state = run_agent(question, reader, model)
            trace = Trace.from_state(state, trace_id=trace_id)
            (_TRACES / f"{trace_id}.json").write_text(trace.model_dump_json(indent=2))
            print(f"[{trace.outcome:8}] {trace_id}  {question}")
            if args.judge:
                verdict = judge_trace(model, trace)
                judge_out.write(verdict.model_dump_json() + "\n")
                flags = ", ".join(e.value for e in verdict.error_types) or "sound"
                print(f"            judge: {flags}")

    print(f"\nwrote {len(questions)} traces to {_TRACES.relative_to(_ROOT)}")
    if args.judge:
        print(f"wrote judge labels to {_JUDGE_LABELS.relative_to(_ROOT)}")
    print("next: review them with  .venv/bin/python scripts/review.py")
    return 0


class _nullctx:
    def __enter__(self):
        return None

    def __exit__(self, *exc):
        return False


if __name__ == "__main__":
    raise SystemExit(main())
