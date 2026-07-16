"""Reader selection — *below the seam*, in ``readers/``.

The MCP server (and any future host) must choose a concrete reader without ever naming
one above the seam. All that knowledge — which env value maps to which concretion — lives
here, below the seam, so ``mcp/`` can ask for "the configured reader" and receive a bare
``SignalReader`` with no idea what it is (docs/02, docs/04).

``CANOPY_SOURCE`` drives the choice. Only ``synthetic`` is wired today; ``obd`` and
``can_log`` arrive in later phases and are rejected with a clear message until then, rather
than silently falling back to synthetic (which would hide a misconfiguration).
"""

from __future__ import annotations

import os

from canopy.readers.base import SignalReader
from canopy.readers.synthetic import SyntheticReader

_ENV_VAR = "CANOPY_SOURCE"
_DEFAULT_SOURCE = "synthetic"

# Sources named in docs/04 but not yet implemented. Listed so the error message can tell a
# caller their config is recognized-but-future rather than simply wrong.
_PLANNED_SOURCES = ("obd", "can_log")

# Demo scenarios a host may request. A scenario is *not* a source — it selects a
# ground-truth condition the (synthetic) source reproduces, so a host (e.g. the web UI)
# can show a healthy bus or a known anomaly without ever naming a concretion. The mapping
# from scenario to the concrete reader's construction stays here, below the seam. ``None``
# and ``"normal"`` both mean "no injected anomaly".
_SCENARIOS: dict[str, str | None] = {
    "normal": None,
    "overheat": "overheat",  # coolant climbs under moderate load — the classic overheat
}


def build_reader(source: str | None = None, scenario: str | None = None) -> SignalReader:
    """Construct the reader selected by ``CANOPY_SOURCE`` (or the ``source`` override).

    ``scenario`` optionally selects a ground-truth condition for the synthetic source
    (e.g. ``"overheat"``); the caller passes a plain string and never learns which reader,
    or which anomaly preset, backs it. Returns a ``SignalReader``. The caller above the
    seam holds the protocol, never the concretion, and must not branch on which one it got.
    """
    chosen = (source or os.environ.get(_ENV_VAR) or _DEFAULT_SOURCE).strip().lower()

    if scenario is not None and scenario.strip().lower() not in _SCENARIOS:
        raise ValueError(
            f"Unknown scenario {scenario!r}. Known: {', '.join(_SCENARIOS)}."
        )
    anomaly = _SCENARIOS.get((scenario or "normal").strip().lower())

    if chosen == "synthetic":
        return SyntheticReader(anomaly=anomaly)

    if chosen in _PLANNED_SOURCES:
        raise ValueError(
            f"{_ENV_VAR}={chosen!r} is planned but not yet implemented. "
            f"Set {_ENV_VAR}={_DEFAULT_SOURCE!r} for now."
        )

    raise ValueError(
        f"Unknown {_ENV_VAR}={chosen!r}. Known: {_DEFAULT_SOURCE}, {', '.join(_PLANNED_SOURCES)}."
    )
