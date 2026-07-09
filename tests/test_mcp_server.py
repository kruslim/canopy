"""Phase 2 MCP server tests — the docs/04 "Testing the server without an agent" list.

A real ``ClientSession`` drives the real ``Server`` over the SDK's in-memory transport:
initialize, discover, invoke, and shut down — no subprocess, no LLM. The subprocess/stdio
equivalent (the same server launched as ``python -m canopy.mcp`` the way Claude Desktop
launches it) lives in ``scripts/smoke_mcp.py``.

Covers: discovery, schema round-trip, successful invocation, the tool-error/protocol-error
distinction (docs/04's two error classes), lifecycle, and the env-driven reader factory.
"""

from __future__ import annotations

import json

import pytest
from mcp import types
from mcp.shared.exceptions import McpError
from mcp.shared.memory import create_connected_server_and_client_session

from canopy.mcp import build_server
from canopy.readers import build_reader
from canopy.readers.synthetic import SyntheticReader
from canopy.tools import (
    GetSignalInput,
    ListAvailableSignalsInput,
    RunDiagnosticRulesInput,
    SummarizeSessionInput,
)

pytestmark = pytest.mark.anyio

T0 = "2026-01-01T00:00:00"
T1 = "2026-01-01T00:00:10"

# One valid example invocation per tool. Used both for the schema round-trip test (the
# example must validate against the Pydantic model the schema was derived from) and for
# the invocation test (the same example must succeed over the wire).
_EXAMPLES: dict[str, tuple[type, dict]] = {
    "list_available_signals": (ListAvailableSignalsInput, {}),
    "summarize_session": (SummarizeSessionInput, {"start": T0, "end": T1}),
    "get_signal": (
        GetSignalInput,
        {"name": "EngineRPM", "start": T0, "end": T1, "max_samples": 50},
    ),
    "run_diagnostic_rules": (RunDiagnosticRulesInput, {"start": T0, "end": T1}),
}


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def session():
    server = build_server(SyntheticReader(seed=1))
    async with create_connected_server_and_client_session(server) as client:
        yield client


def _payload(result: types.CallToolResult) -> dict:
    assert result.content, "tool result carried no content"
    block = result.content[0]
    assert isinstance(block, types.TextContent)
    return json.loads(block.text)


# ------------------------------------------------------------------------------- discovery
async def test_discovery_lists_four_described_tools(session):
    listing = await session.list_tools()
    assert {t.name for t in listing.tools} == set(_EXAMPLES)
    assert all((t.description or "").strip() for t in listing.tools)
    for tool in listing.tools:
        schema = tool.inputSchema
        assert schema.get("type") == "object"
        assert "properties" in schema


async def test_advertised_schemas_are_the_pydantic_schemas(session):
    # Round-trip: what went over the wire is exactly model_json_schema() — nothing
    # hand-written, nothing lost in between (docs/04 "do not hand-write JSON Schema").
    listing = await session.list_tools()
    for tool in listing.tools:
        model, _ = _EXAMPLES[tool.name]
        assert tool.inputSchema == model.model_json_schema()


async def test_parameter_descriptions_reach_the_wire(session):
    # The Field(description=...) text authored in the tool layer is protocol payload.
    listing = await session.list_tools()
    get_sig = next(t for t in listing.tools if t.name == "get_signal")
    props = get_sig.inputSchema["properties"]
    assert props["name"].get("description")
    assert props["max_samples"].get("description")


def test_example_inputs_validate_against_their_models():
    for model, example in _EXAMPLES.values():
        model.model_validate(example)  # raises on mismatch


# ------------------------------------------------------------------------------ invocation
async def test_every_tool_invokes_successfully(session):
    for name, (_, example) in _EXAMPLES.items():
        result = await session.call_tool(name, example)
        assert result.isError is not True, f"{name} failed: {_payload(result)}"
        assert _payload(result)  # non-empty JSON payload


async def test_get_signal_returns_a_series(session):
    result = await session.call_tool("get_signal", {"name": "EngineRPM", "start": T0, "end": T1})
    payload = _payload(result)
    assert result.isError is not True
    assert payload["series"]["name"] == "EngineRPM"
    assert payload["series"]["unit"] == "rpm"
    assert len(payload["series"]["samples"]) > 1
    # The citation invariant survives serialization: every sample carries its unit.
    assert all(s["unit"] == "rpm" for s in payload["series"]["samples"])


# ----------------------------------------------------------- tool errors (model-recoverable)
async def test_unknown_signal_is_a_tool_error_with_recovery_payload(session):
    result = await session.call_tool(
        "get_signal", {"name": "RearCameraActivation", "start": T0, "end": T1}
    )
    payload = _payload(result)
    assert result.isError is True
    assert payload["error"] == "unknown_signal"
    assert payload["available_signals"], "recovery info must travel with the error"
    assert payload["hint"]


async def test_invalid_arguments_is_a_tool_error_with_field_details(session):
    # Schema-violating arguments are something the model produced and can fix, so they
    # come back as isError with field-level detail — not as a protocol error.
    result = await session.call_tool(
        "get_signal",
        {"name": "EngineRPM", "start": T0, "end": T1, "max_samples": 5000},
    )
    payload = _payload(result)
    assert result.isError is True
    assert payload["error"] == "invalid_arguments"
    assert any("max_samples" in d["field"] for d in payload["details"])
    assert payload["hint"]


# ------------------------------------------------------------- protocol errors (our bug)
async def test_unknown_tool_is_a_protocol_error_not_a_tool_result(session):
    # A tool name that was never advertised is the client's bug, not the model's. It must
    # surface as a JSON-RPC error (McpError on the client), never as an isError result the
    # model would be asked to reason about (docs/04's two error classes).
    with pytest.raises(McpError) as excinfo:
        await session.call_tool("read_dtc_codes", {})
    assert excinfo.value.error.code == types.METHOD_NOT_FOUND
    assert "read_dtc_codes" in excinfo.value.error.message


# ------------------------------------------------------------------------------- lifecycle
async def test_lifecycle_initialize_call_shutdown():
    # Full pass through docs/04's lifecycle: initialize (the fixture-less path, so the
    # teardown is exercised inside the test), list, call, clean shutdown.
    server = build_server(SyntheticReader(seed=2))
    async with create_connected_server_and_client_session(server) as client:
        listing = await client.list_tools()
        assert len(listing.tools) == 4
        result = await client.call_tool("list_available_signals", {})
        assert result.isError is not True
    # Exiting the context tears down the session and cancels the server task; reaching
    # here without hanging or raising is the assertion.


# -------------------------------------------------------------------- reader factory (env)
def test_build_reader_defaults_to_synthetic(monkeypatch):
    monkeypatch.delenv("CANOPY_SOURCE", raising=False)
    assert isinstance(build_reader(), SyntheticReader)


def test_build_reader_honors_env_var(monkeypatch):
    monkeypatch.setenv("CANOPY_SOURCE", "  Synthetic ")
    assert isinstance(build_reader(), SyntheticReader)


def test_build_reader_rejects_planned_sources_with_guidance(monkeypatch):
    monkeypatch.setenv("CANOPY_SOURCE", "can_log")
    with pytest.raises(ValueError, match="planned but not yet implemented"):
        build_reader()


def test_build_reader_rejects_unknown_sources(monkeypatch):
    monkeypatch.setenv("CANOPY_SOURCE", "carrier_pigeon")
    with pytest.raises(ValueError, match="Unknown"):
        build_reader()
