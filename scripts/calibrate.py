"""Compute the LLM-judge calibration report from labelled traces (docs/07).

Loads ``data/evals/calibration_labels.json`` — human review pass A, a second pass B one week
later, and the judge's labels for the same traces — and computes the number the README leads
with: how often the judge agrees with human review, read against the ceiling of how often the
(solo) reviewer agrees with themselves.

    .venv/bin/python scripts/calibrate.py

Writes ``data/evals/calibration_report.json`` and prints a human-readable summary. This uses
recorded labels, so it needs no API key and is fully reproducible — the honest artifact for a
solo project, where the ground truth is seeded by hand and grows as real reviews land.
"""

from __future__ import annotations

import json
from pathlib import Path

from canopy.evals.judge import build_calibration_report
from canopy.evals.schemas import ErrorType

_ROOT = Path(__file__).resolve().parent.parent
_LABELS = _ROOT / "data" / "evals" / "calibration_labels.json"
_REPORT = _ROOT / "data" / "evals" / "calibration_report.json"

_NOTE = (
    "Solo project: no reviewer panel exists, so inter-rater agreement cannot be measured. "
    "Self-agreement (the same subset scored twice, one week apart) stands in as the ceiling "
    "proxy. Ground-truth labels are seeded by hand and firm up as real from_review cases land."
)


def _labels(records: list[dict], key: str) -> dict[str, set[ErrorType]]:
    return {r["trace_id"]: {ErrorType(e) for e in r[key]} for r in records}


def main() -> int:
    data = json.loads(_LABELS.read_text())
    records = data["traces"]

    human_a = _labels(records, "human_a")
    human_b = _labels(records, "human_b")
    judge = _labels(records, "judge")

    report = build_calibration_report(
        human_a,
        judge,
        self_pass_a=human_a,
        self_pass_b=human_b,
        single_reviewer_note=_NOTE,
    )

    _REPORT.write_text(report.model_dump_json(indent=2))

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
