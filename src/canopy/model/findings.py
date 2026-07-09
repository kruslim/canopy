"""Structured findings emitted by domain rules.

A rule consumes ``SignalSeries`` and emits ``Finding``s. ``evidence`` is **mandatory** on
every finding: a rule that asserts without citing the samples it examined is a rule the
agent will happily launder into a hallucination (``docs/02-architecture-and-data-model.md``).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from canopy.model.signals import SignalSample


class Finding(BaseModel):
    """One structured observation produced by a diagnostic rule."""

    rule_id: str = Field(..., description="Stable identifier of the rule that produced this.")
    severity: Literal["info", "warning", "violation"]
    message: str = Field(..., description="Human-readable statement of what was observed.")
    evidence: list[SignalSample] = Field(
        ...,
        description=(
            "The actual samples the rule examined. Mandatory and may not be empty — a "
            "finding must always cite the data that supports it."
        ),
        min_length=1,
    )
    confidence: Literal["high", "medium", "low"] = Field(
        ...,
        description=(
            "How much to trust this finding. A timing rule handed a single-sample point "
            "read returns 'low' rather than silently passing."
        ),
    )
