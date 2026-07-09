"""L3 — MCP server (above the seam).

Nothing here may name the data source or import ``readers/`` concretions directly;
data is reached only through the ``SignalReader`` protocol and ``domain/``
(docs/02, enforced by ``tests/test_seam.py``). The active reader is selected below the
seam by ``readers.build_reader`` and injected into the server.
"""

from canopy.mcp.server import build_server, main, run_stdio

__all__ = ["build_server", "run_stdio", "main"]
