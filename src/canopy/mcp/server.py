"""L3 — the Canopy MCP server (above the seam).

A thin adapter (docs/04): it translates JSON-RPC protocol messages into calls on the Doc-03
tool layer and nothing more. There is no domain logic here — if there were, it would belong
below the seam.

Three design commitments this module makes concrete:

* **Schemas are Pydantic, not hand-written.** Every tool advertises
  ``InputModel.model_json_schema()``, so the ``Field(description=...)`` text authored in the
  tool layer travels over the wire to the model verbatim (docs/04).
* **Reader selection is invisible above the seam.** The active ``SignalReader`` is built by
  ``readers.build_reader`` (below the seam) from ``CANOPY_SOURCE`` and injected here; this
  module never names a source and never branches on the reader's type (Constraint 1).
* **Tool errors vs. protocol errors are different animals** (docs/04). An unknown *signal*
  is a tool error: the handler returns ``isError: true`` with a recovery-bearing payload the
  model reads and self-corrects from. An unknown *tool name* is a protocol error: the client
  asked for something never advertised, so we raise ``McpError`` and the framework returns a
  JSON-RPC error the model never sees.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable

import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from mcp.shared.exceptions import McpError
from pydantic import ValidationError

from canopy.readers import build_reader
from canopy.readers.base import SignalReader

# The four tools in canonical wire order come from the shared registry (one authority for
# name/description/schema/handler, also consumed by the agent's tool node — docs/05).
from canopy.tools.registry import TOOLS, TOOLS_BY_NAME

SERVER_NAME = "canopy"


def _text_result(payload: dict, *, is_error: bool) -> types.ServerResult:
    """Wrap a JSON-serializable payload as a single-text-block ``CallToolResult``."""
    return types.ServerResult(
        types.CallToolResult(
            content=[types.TextContent(type="text", text=json.dumps(payload))],
            isError=is_error,
        )
    )


def _invalid_arguments_payload(name: str, exc: ValidationError) -> dict:
    """Shape a Pydantic validation failure as a recovery-bearing tool error.

    Bad arguments are something the *model* produced and can fix on the next turn (a
    malformed time range, a missing field), so they are a tool error, not a protocol error:
    the model sees the payload and corrects itself.
    """
    return {
        "error": "invalid_arguments",
        "tool": name,
        "message": f"Arguments did not validate against the schema for {name!r}.",
        "details": [
            {"field": ".".join(str(p) for p in err["loc"]), "problem": err["msg"]}
            for err in exc.errors()
        ],
        "hint": "Re-read the tool's input schema and supply arguments matching it exactly.",
    }


def build_server(reader: SignalReader) -> Server:
    """Build the MCP server bound to a single injected ``reader``.

    The reader is captured by closure and held for the server's life (docs/04: "state to
    hold: which SignalReader is active"). Everything else is stateless per call.
    """
    server: Server = Server(SERVER_NAME)

    @server.list_tools()
    async def _list_tools() -> list[types.Tool]:
        # Discovery: each tool's JSON Schema is derived from its Pydantic input model so the
        # parameter descriptions authored in the tool layer reach the model unchanged.
        return [
            types.Tool(
                name=spec.name,
                description=spec.description,
                inputSchema=spec.input_model.model_json_schema(),
            )
            for spec in TOOLS
        ]

    async def _dispatch(req: types.CallToolRequest) -> types.ServerResult:
        name = req.params.name
        arguments = req.params.arguments or {}

        spec = TOOLS_BY_NAME.get(name)
        if spec is None:
            # Protocol error: the client invoked a tool that was never advertised. The model
            # cannot act on this, so it must not reach the model as a tool result — raise and
            # let the framework return a JSON-RPC error response instead (docs/04).
            raise McpError(
                types.ErrorData(
                    code=types.METHOD_NOT_FOUND,
                    message=f"Unknown tool: {name!r}. Call tools/list to discover valid names.",
                )
            )

        try:
            inp = spec.input_model.model_validate(arguments)
        except ValidationError as exc:
            return _text_result(_invalid_arguments_payload(name, exc), is_error=True)

        result = spec.invoke(reader, inp)

        # The dict/model split IS the tool-error signal: a handler returns a plain dict only
        # when it caught a below-seam raise (e.g. UnknownSignalError -> unknown_signal payload
        # carrying available_signals + hint). Surface it with isError so the model recovers.
        if isinstance(result, dict):
            return _text_result(result, is_error=bool(result.get("error")))

        return _text_result(result.model_dump(mode="json"), is_error=False)

    # Register the call handler directly (rather than via @server.call_tool) so a raised
    # McpError propagates to the framework as a JSON-RPC error instead of being swallowed
    # into an isError tool result — that is what keeps protocol errors distinct from tool
    # errors (docs/04).
    server.request_handlers[types.CallToolRequest] = _dispatch

    return server


async def run_stdio(build: Callable[[], SignalReader] = build_reader) -> None:
    """Serve over stdio: build the env-selected reader, run, release on shutdown.

    stdio is the deliberate transport choice for Canopy (docs/04): local, single-client, no
    auth/ports/TLS, and exactly what Claude Desktop launches.
    """
    reader = build()
    server = build_server(reader)
    try:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )
    finally:
        # Release the reader if it holds anything (a serial port, a file handle). Synthetic
        # holds nothing; a future ObdReader will (docs/04 lifecycle step 4).
        close: Callable[[], Awaitable[None]] | Callable[[], None] | None = getattr(
            reader, "close", None
        )
        if close is not None:
            maybe = close()
            if hasattr(maybe, "__await__"):
                await maybe


def main() -> None:
    """Console entry point: ``python -m canopy.mcp``."""
    import anyio

    anyio.run(run_stdio)


if __name__ == "__main__":
    main()
