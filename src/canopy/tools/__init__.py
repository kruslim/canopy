"""L2 — Tool design & schemas (above the seam).

Four tools wrap the domain logic below, each a schema + a description written as a *prompt
fragment* (the model reads the description to decide) + a handler. Nothing here names the
data source or imports ``readers/`` concretions: handlers speak only the ``SignalReader``
protocol and the ``domain/`` layer (docs/02, enforced by ``tests/test_seam.py``).

Ordered by cost — cheap orienting tools first, so the model reads them as the things to
call before expensive analysis:

1. ``list_available_signals`` — what exists (call first)
2. ``summarize_session``      — structural overview (cheap orienting call)
3. ``get_signal``             — retrieve one timeseries
4. ``run_diagnostic_rules``   — the expensive interpretive call
"""

from canopy.tools.diagnose import (
    RunDiagnosticRulesInput,
    RunDiagnosticRulesOutput,
    run_diagnostic_rules,
)
from canopy.tools.get_signal import GetSignalInput, GetSignalOutput, get_signal
from canopy.tools.list_signals import (
    ListAvailableSignalsInput,
    ListAvailableSignalsOutput,
    list_available_signals,
)
from canopy.tools.summarize import (
    CoverageGap,
    SummarizeSessionInput,
    SummarizeSessionOutput,
    summarize_session,
)

__all__ = [
    "list_available_signals",
    "ListAvailableSignalsInput",
    "ListAvailableSignalsOutput",
    "get_signal",
    "GetSignalInput",
    "GetSignalOutput",
    "run_diagnostic_rules",
    "RunDiagnosticRulesInput",
    "RunDiagnosticRulesOutput",
    "summarize_session",
    "SummarizeSessionInput",
    "SummarizeSessionOutput",
    "CoverageGap",
]
