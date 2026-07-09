"""Tool 3 — ``run_diagnostic_rules``. Run the domain rule set and return cited findings.

The load-bearing sentence of this tool's description (docs/03): an empty ``findings`` list
next to a non-empty ``skipped`` list means "we didn't look," not "nothing is wrong." That
distinction — absence of evidence vs. evidence of absence — is exactly the reasoning error
that makes an AI system dangerous in a compliance context, so it is stated to the model
rather than left to inference. The skip logic itself lives in ``domain/registry`` so every
caller inherits it.

Every ``Finding`` carries non-empty ``evidence`` (Constraint 4): a claim with no cited
samples is a hallucination waiting to launder itself through the agent.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from canopy.domain.registry import run_rules
from canopy.model.findings import Finding
from canopy.readers.base import SignalReader

DESCRIPTION = (
    "Runs the domain diagnostic rule set over a time range and returns structured "
    "findings, each citing the specific data samples that support it.\n\n"
    "Every finding includes `evidence` — the actual samples the rule examined — and a "
    "`confidence` level. A finding with confidence 'low' usually means the rule ran against "
    "insufficient data (for example, a timing rule given a single-sample point read). "
    "Report low-confidence findings as tentative; never present them as established fact.\n\n"
    "Rules requiring signals the current source cannot provide are SKIPPED, not failed. "
    "Check `skipped` before concluding that no problems exist: an empty findings list with "
    "a non-empty skipped list means 'we didn't look,' not 'nothing is wrong.'"
)


class RunDiagnosticRulesInput(BaseModel):
    start: datetime
    end: datetime
    rule_ids: list[str] | None = Field(
        default=None,
        description=(
            "Specific rules to run. Omit to run all rules applicable to the available "
            "signals. Rules whose required signals are unavailable are skipped and reported "
            "in `skipped`."
        ),
    )


class RunDiagnosticRulesOutput(BaseModel):
    findings: list[Finding]
    rules_run: list[str]
    skipped: list[dict[str, str]]


def run_diagnostic_rules(
    reader: SignalReader,
    inp: RunDiagnosticRulesInput,
) -> RunDiagnosticRulesOutput:
    result = run_rules(reader, inp.start, inp.end, inp.rule_ids)
    return RunDiagnosticRulesOutput(
        findings=result.findings,
        rules_run=result.rules_run,
        skipped=result.skipped,
    )
