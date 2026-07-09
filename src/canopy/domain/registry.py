"""The rule registry and orchestrator — *below the seam*, in ``domain/``.

The single most valuable behaviour here is the distinction between **absence of evidence**
and **evidence of absence** (docs/03). A rule whose required signals the current source
cannot provide is *skipped*, not failed: it lands in ``skipped`` with a reason, so an empty
``findings`` list next to a non-empty ``skipped`` list reads as "we didn't look," never as
"nothing is wrong." Keeping that logic here — not in the tool — means every caller inherits
it for free.

Rules remain pure: each declares the signals it needs and receives them already read, as a
``{name: SignalSeries}`` map. The orchestrator owns all reader interaction, so a rule never
learns where its data came from.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from canopy.domain.rules.correlation import RULE_ID as CORRELATION_RULE_ID
from canopy.domain.rules.correlation import coolant_load_correlation
from canopy.model.findings import Finding
from canopy.model.signals import SignalSeries
from canopy.readers.base import SignalReader


@dataclass(frozen=True)
class Rule:
    """One registered diagnostic rule.

    ``required_signals`` is what lets the orchestrator skip a rule cleanly when the source
    cannot supply its inputs. ``evaluate`` is pure: it takes the read series and returns
    findings, and never touches a reader.
    """

    rule_id: str
    required_signals: tuple[str, ...]
    evaluate: Callable[[dict[str, SignalSeries]], list[Finding]]


def _eval_coolant_load(series: dict[str, SignalSeries]) -> list[Finding]:
    return coolant_load_correlation(series["CoolantTemp"], series["EngineLoad"])


# The registry. New rules are added here; nothing else changes.
REGISTRY: tuple[Rule, ...] = (
    Rule(
        rule_id=CORRELATION_RULE_ID,
        required_signals=("CoolantTemp", "EngineLoad"),
        evaluate=_eval_coolant_load,
    ),
)


@dataclass(frozen=True)
class RuleRunResult:
    """Outcome of a rule run. Mirrors the ``run_diagnostic_rules`` tool output shape."""

    findings: list[Finding] = field(default_factory=list)
    rules_run: list[str] = field(default_factory=list)
    skipped: list[dict[str, str]] = field(default_factory=list)


def _select(rule_ids: list[str] | None) -> tuple[Rule, ...]:
    if rule_ids is None:
        return REGISTRY
    wanted = set(rule_ids)
    return tuple(rule for rule in REGISTRY if rule.rule_id in wanted)


def run_rules(
    reader: SignalReader,
    start: datetime,
    end: datetime,
    rule_ids: list[str] | None = None,
) -> RuleRunResult:
    """Run applicable rules over ``[start, end]``.

    A rule whose required signals are not all available is skipped (with a reason) rather
    than run against missing data. Rules that run always cite evidence via their findings.
    """
    available = set(reader.available_signals())
    result = RuleRunResult()

    for rule in _select(rule_ids):
        missing = [s for s in rule.required_signals if s not in available]
        if missing:
            result.skipped.append(
                {
                    "rule_id": rule.rule_id,
                    "reason": (f"requires signal(s) {', '.join(missing)}, unavailable from source"),
                }
            )
            continue

        series = {name: reader.read(name, start, end) for name in rule.required_signals}
        result.findings.extend(rule.evaluate(series))
        result.rules_run.append(rule.rule_id)

    return result
