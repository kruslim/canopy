"""The canonical tool registry — the single authority on what tools exist.

Extracted from the MCP server in Phase 3 because a second consumer arrived: the agent's
tool-execution node needs exactly the same (name, description, input schema, handler)
tuples the server advertises over the wire. Two hand-maintained lists would drift; the
first drift would be a tool the agent can call but the server never advertises (or vice
versa), which is precisely the class of bug that is invisible until a demo.

Order matters: tools are listed in the cost order the model should read them (docs/03) —
cheap orienting calls first, expensive interpretation last.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel

from canopy.readers.base import SignalReader
from canopy.tools.diagnose import DESCRIPTION as DIAGNOSE_DESCRIPTION
from canopy.tools.diagnose import RunDiagnosticRulesInput, run_diagnostic_rules
from canopy.tools.get_signal import DESCRIPTION as GET_SIGNAL_DESCRIPTION
from canopy.tools.get_signal import GetSignalInput, get_signal
from canopy.tools.list_signals import DESCRIPTION as LIST_SIGNALS_DESCRIPTION
from canopy.tools.list_signals import ListAvailableSignalsInput, list_available_signals
from canopy.tools.summarize import DESCRIPTION as SUMMARIZE_DESCRIPTION
from canopy.tools.summarize import SummarizeSessionInput, summarize_session

# A handler takes the injected reader plus a validated input model and returns either a
# Pydantic output model (success) or a plain ``dict`` (a structured tool-error payload,
# e.g. ``unknown_signal``). The dict/model split is the tool-error signal for every caller.
ToolFn = Callable[[SignalReader, BaseModel], BaseModel | dict]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_model: type[BaseModel]
    invoke: ToolFn


TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="list_available_signals",
        description=LIST_SIGNALS_DESCRIPTION,
        input_model=ListAvailableSignalsInput,
        invoke=list_available_signals,
    ),
    ToolSpec(
        name="summarize_session",
        description=SUMMARIZE_DESCRIPTION,
        input_model=SummarizeSessionInput,
        invoke=summarize_session,
    ),
    ToolSpec(
        name="get_signal",
        description=GET_SIGNAL_DESCRIPTION,
        input_model=GetSignalInput,
        invoke=get_signal,
    ),
    ToolSpec(
        name="run_diagnostic_rules",
        description=DIAGNOSE_DESCRIPTION,
        input_model=RunDiagnosticRulesInput,
        invoke=run_diagnostic_rules,
    ),
)

TOOLS_BY_NAME: dict[str, ToolSpec] = {spec.name: spec for spec in TOOLS}
