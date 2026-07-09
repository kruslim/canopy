"""Step 3 of the eval loop — compute the LLM-judge calibration report (docs/07).

Two modes:

* **seed** (default) — reads the hand-authored ``data/evals/calibration_labels.json``. This is
  the illustrative number the README ships with; it demonstrates the machinery on a solo project
  before any real reviews exist.
* **real** (``--real``) — reads the labels you actually collected: human review pass A
  (``reviews_pass_a.jsonl``), the judge labels (``judge_labels.jsonl``), and an optional second
  pass (``reviews_pass_b.jsonl``) for the self-agreement ceiling. This is the number that
  actually means something once you have real traces.

Both need no API key (they read recorded labels), so the calibration is fully reproducible.

    .venv/bin/python scripts/calibrate.py            # seed labels — the shipped 85% / 90%
    .venv/bin/python scripts/calibrate.py --real     # your collected labels
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from canopy.evals.judge import build_calibration_report
from canopy.evals.schemas import ErrorType

_ROOT = Path(__file__).resolve().parent.parent
_EVALS = _ROOT / "data" / "evals"
_LABELS = _EVALS / "calibration_labels.json"
_REPORT = _EVALS / "calibration_report.json"

_NOTE = (
    "Solo project: no reviewer panel exists, so inter-rater agreement cannot be measured. "
    "Self-agreement (the same subset scored twice, one week apart) stands in as the ceiling "
    "proxy. Ground-truth labels are seeded by hand and firm up as real from_review cases land."
)


def _labels(records: list[dict], key: str) -> dict[str, set[ErrorType]]:
    return {r["trace_id"]: {ErrorType(e) for e in r[key]} for r in records}


def _jsonl_labels(path: Path) -> dict[str, set[ErrorType]]:
    """Read {trace_id -> error_type set} from a JSONL file of ReviewFeedback/JudgeVerdict rows."""
    out: dict[str, set[ErrorType]] = {}
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        out[row["trace_id"]] = {ErrorType(e) for e in row.get("error_types", [])}
    return out


def _seed_report():
    data = json.loads(_LABELS.read_text())
    records = data["traces"]
    human_a = _labels(records, "human_a")
    return build_calibration_report(
        human_a,
        _labels(records, "judge"),
        self_pass_a=human_a,
        self_pass_b=_labels(records, "human_b"),
        single_reviewer_note=_NOTE,
    )


def _real_report(pass_a: Path, pass_b: Path | None, judge: Path):
    for required in (pass_a, judge):
        if not required.exists():
            raise SystemExit(
                f"Missing {required.relative_to(_ROOT)}. "
                "Run capture.py --judge and review.py first."
            )
    human_a = _jsonl_labels(pass_a)
    human_b = _jsonl_labels(pass_b) if pass_b and pass_b.exists() else None
    return build_calibration_report(
        human_a,
        _jsonl_labels(judge),
        self_pass_a=human_a if human_b else None,
        self_pass_b=human_b,
        single_reviewer_note=_NOTE,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--real", action="store_true", help="Use collected labels, not seed labels."
    )
    parser.add_argument("--pass-a", default="reviews_pass_a.jsonl")
    parser.add_argument("--pass-b", default="reviews_pass_b.jsonl")
    parser.add_argument("--judge-labels", default="judge_labels.jsonl")
    args = parser.parse_args()

    if args.real:
        report = _real_report(
            _EVALS / args.pass_a, _EVALS / args.pass_b, _EVALS / args.judge_labels
        )
        mode = "real (collected labels)"
    else:
        report = _seed_report()
        mode = "seed (illustrative labels)"

    _REPORT.write_text(report.model_dump_json(indent=2))
    print(f"mode: {mode}")

    if report.n_traces == 0:
        print(
            "No overlapping trace ids between human and judge labels — nothing to score. "
            "Make sure capture.py --judge and review.py ran over the same captured traces."
        )
        return 1

    print("── LLM-judge calibration ──────────────────────")
    print(f"traces scored:            {report.n_traces}")
    print(f"judge–human agreement:    {report.judge_human_agreement:.0%}   ← the headline")
    if report.self_agreement is not None:
        print(
            f"self-agreement (ceiling): {report.self_agreement:.0%}   "
            f"(n={report.self_agreement_n}, one week apart)"
        )
    print("agreement by error type:")
    for etype, agree in sorted(report.judge_agreement_by_error_type.items(), key=lambda kv: -kv[1]):
        print(f"    {agree:.0%}  {etype.value}")
    if report.disagreement_examples:
        print(f"disagreement examples:    {', '.join(report.disagreement_examples)}")
    print(f"\nwrote {_REPORT.relative_to(_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
