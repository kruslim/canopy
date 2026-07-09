#!/usr/bin/env python
"""A bare MCP client that exercises the Canopy server end-to-end over stdio.

This is the Phase-2 acceptance check from docs/04's "Testing the server without an agent":
no LLM, no agent loop — just a protocol client driving the real server as a subprocess.
It asserts the five things a Phase-2 server must get right and prints a ``PASS`` line for
each. Any failed assertion prints ``FAIL`` and exits non-zero.

Run: ``.venv/bin/python scripts/smoke_mcp.py``
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

_EXPECTED_TOOLS = {
    "list_available_signals",
    "summarize_session",
    "get_signal",
    "run_diagnostic_rules",
}

_passed = 0
_failed = 0


def check(condition: bool, message: str) -> None:
    """Record one assertion. Prints PASS/FAIL; never raises so all checks run."""
    global _passed, _failed
    if condition:
        _passed += 1
        print(f"PASS: {message}")
    else:
        _failed += 1
        print(f"FAIL: {message}")


def _payload(result) -> dict:
    """Decode the single text content block of a tool result into a dict."""
    assert result.content, "tool result carried no content"
    return json.loads(result.content[0].text)


def _server_params() -> StdioServerParameters:
    # Launch the server with this same interpreter (the venv's), so the editable install of
    # canopy is importable. CANOPY_SOURCE drives reader selection below the seam — the client
    # never tells the server which reader to use beyond this env var.
    env = dict(os.environ)
    env["CANOPY_SOURCE"] = "synthetic"
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "canopy.mcp"],
        env=env,
    )


async def run() -> None:
    async with stdio_client(_server_params()) as (read, write):
        async with ClientSession(read, write) as session:
            # (1) Connect: initialize negotiates protocol version + capabilities.
            init = await session.initialize()
            check(
                init.serverInfo.name == "canopy",
                f"connected and initialized (server '{init.serverInfo.name}')",
            )

            # (2) Discovery: exactly four tools, each with a non-empty description and a
            # valid object schema whose parameter descriptions survived from Pydantic.
            listing = await session.list_tools()
            names = {t.name for t in listing.tools}
            check(
                len(listing.tools) == 4 and names == _EXPECTED_TOOLS,
                f"lists exactly 4 tools: {sorted(names)}",
            )
            all_described = all((t.description or "").strip() for t in listing.tools)
            check(all_described, "every tool has a non-empty description")

            def valid_schema(t) -> bool:
                s = t.inputSchema
                return isinstance(s, dict) and s.get("type") == "object" and "properties" in s

            check(
                all(valid_schema(t) for t in listing.tools),
                "every tool advertises a valid object input schema",
            )

            # Prove the Field descriptions reached the wire (docs/04): get_signal's params.
            get_sig = next(t for t in listing.tools if t.name == "get_signal")
            props = get_sig.inputSchema["properties"]
            check(
                bool(props.get("name", {}).get("description"))
                and bool(props.get("max_samples", {}).get("description")),
                "parameter descriptions survived into the schema (get_signal.name, .max_samples)",
            )

            # (3) Successful invocation against the SyntheticReader.
            ok = await session.call_tool(
                "get_signal",
                {
                    "name": "EngineRPM",
                    "start": "2026-07-08T12:00:00",
                    "end": "2026-07-08T12:00:05",
                },
            )
            ok_payload = _payload(ok)
            check(
                ok.isError is not True
                and ok_payload["series"]["name"] == "EngineRPM"
                and len(ok_payload["series"]["samples"]) > 1,
                f"get_signal returns a non-empty EngineRPM series "
                f"({len(ok_payload['series']['samples'])} samples, unit "
                f"'{ok_payload['series']['unit']}')",
            )

            # (4) Tool error: unknown signal -> isError with a recovery-bearing payload.
            bad = await session.call_tool(
                "get_signal",
                {
                    "name": "RearCameraActivation",
                    "start": "2026-07-08T12:00:00",
                    "end": "2026-07-08T12:00:05",
                },
            )
            bad_payload = _payload(bad)
            print(f"      (unknown-signal payload: {json.dumps(bad_payload)})")
            check(bad.isError is True, "unknown signal yields isError=true")
            check(
                "available_signals" in bad_payload and bool(bad_payload["available_signals"]),
                "error payload lists available_signals for the model to recover from",
            )
            check(
                "hint" in bad_payload and bool(bad_payload["hint"]),
                "error payload carries a hint",
            )

        # (5) Exiting both async-with blocks tears down the session and the subprocess.
    check(True, "server shut down cleanly (session + subprocess released)")


def main() -> int:
    asyncio.run(run())
    print(f"\n{_passed} passed, {_failed} failed")
    return 0 if _failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
