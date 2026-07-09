"""Tool 1 — ``list_available_signals``. The most important tool, most often forgotten.

It is the mechanism by which the agent can *know what it cannot answer* (docs/03): asked
about rear-camera timing over a source that has no such signal, the agent discovers its own
ignorance from a tool result rather than confabulating from self-knowledge.

The handler speaks only the ``SignalReader`` protocol — never a concretion, never the name
of a data source (Constraint 1).
"""

from __future__ import annotations

from pydantic import BaseModel

from canopy.model.signals import SignalDescriptor, SignalSource
from canopy.readers.base import SignalReader

DESCRIPTION = (
    "Returns the complete list of signals available from the currently connected data "
    "source, with units and typical ranges.\n\n"
    "Call this FIRST whenever you are unsure whether a signal exists. Signal availability "
    "depends entirely on the data source, so the only reliable way to know what you can "
    "answer is to ask.\n\n"
    "If the signal a user asks about does not appear in this list, it is NOT available: do "
    "not attempt to retrieve it, do not estimate it, and do not substitute a related "
    "signal. Tell the user the signal is unavailable and say which source is connected."
)


class ListAvailableSignalsInput(BaseModel):
    """No parameters. Returns everything the current data source exposes."""


class ListAvailableSignalsOutput(BaseModel):
    source: SignalSource
    signals: list[SignalDescriptor]


def list_available_signals(
    reader: SignalReader,
    _input: ListAvailableSignalsInput | None = None,
) -> ListAvailableSignalsOutput:
    return ListAvailableSignalsOutput(
        source=reader.source,
        signals=[reader.describe(name) for name in reader.available_signals()],
    )
