# 04 — MCP Server Spec

**Phase:** 2
**Status when done:** an MCP client can discover and invoke your tools. Still no agent, still no LangGraph.

---

## What MCP is, in one paragraph you must be able to deliver

The Model Context Protocol is a standard for connecting AI applications to tools and data sources. Before it, every agent framework invented its own tool-integration glue, so a tool built for one framework couldn't be used by another — an N×M problem between N agents and M tools. MCP defines a client-server protocol: a **server** exposes capabilities (tools, resources, prompts), a **client** discovers and invokes them, and any MCP-speaking agent can use any MCP server without custom code. It turns N×M into N+M.

That is the answer to *"what problem does MCP solve?"* Have it ready. It is the most likely opening question about this project, because MCP is the word on your resume.

### The follow-up you will get

> *"How is an MCP server different from just calling a function?"*

A function call is in-process, framework-specific, and known at compile time. An MCP server is a **separate process** exposing a **discoverable** interface over a transport. The differences that matter:

- **Discovery.** The client asks the server what tools exist at runtime. Your agent doesn't hardcode the tool list.
- **Decoupling.** The server can be written in any language, run anywhere, and be reused by Claude Desktop, an IDE, a custom LangGraph agent, or a coworker's script.
- **Uniform errors and schemas.** Every tool advertises a JSON Schema; every error follows the same shape.
- **Lifecycle.** Initialization, capability negotiation, and shutdown are specified rather than ad hoc.

For *this* project the concrete payoff is: the same Canopy server backs your LangGraph agent (Doc 05) *and* can be plugged into Claude Desktop for interactive exploration, with zero code changes. Demonstrate that in the README — it makes the decoupling argument viscerally rather than rhetorically.

---

## Architecture

```
┌──────────────────┐         ┌──────────────────┐
│  MCP Client      │         │  MCP Client      │
│  (LangGraph      │         │  (Claude Desktop)│
│   agent, Doc 05) │         │                  │
└────────┬─────────┘         └────────┬─────────┘
         │                            │
         │   JSON-RPC over transport  │
         └────────────┬───────────────┘
                      ▼
         ┌────────────────────────────┐
         │   Canopy MCP Server        │   ← L3, this document
         │   • capability negotiation │
         │   • tool discovery         │
         │   • tool invocation        │
         │   • structured errors      │
         └────────────┬───────────────┘
                      │
                      ▼
         ┌────────────────────────────┐
         │   Tool layer  (Doc 03)     │   ← L2
         └────────────┬───────────────┘
                      │
                 ═════╪═════  THE SEAM
                      ▼
         ┌────────────────────────────┐
         │   domain/ → readers/       │   ← L1
         └────────────────────────────┘
```

The MCP server is a **thin adapter.** It translates protocol messages into calls on your existing tool layer. If you find yourself writing domain logic in `mcp/`, stop — it belongs below the seam.

---

## Transport choice

MCP supports multiple transports. Pick deliberately and justify it.

| Transport | When | Trade-off |
|---|---|---|
| **stdio** | Local, single-client, launched as a subprocess | Simplest. What Claude Desktop uses. No network surface. |
| **HTTP + SSE** | Remote, multi-client, long-running | Needs auth, CORS, lifecycle management. |

**Recommendation for Canopy: start with stdio.** It is the path of least resistance, it is what Claude Desktop expects, and it removes an entire category of problems (ports, auth, TLS) that teach you nothing about GenAI.

Add HTTP later *only if* you want to demo the server backing a deployed web UI. If you do, that's a legitimate README bullet ("supports both stdio and HTTP transports") but it is not worth blocking Phase 3 on.

---

## What the server exposes

MCP servers can expose three kinds of capability. Know all three; use the ones that fit.

### Tools (you will use these)

Model-invoked, side-effect-capable operations. Your four tools from Doc 03 map directly:

- `list_available_signals`
- `get_signal`
- `run_diagnostic_rules`
- `summarize_session`

Each advertises a JSON Schema derived from its Pydantic input model, plus the description you crafted. **The description you wrote in Doc 03 is what travels over the wire.** This is the moment where description-writing stops being an abstraction and becomes literal protocol payload.

### Resources (consider these)

Application-controlled, read-only context the client can attach. Good candidates:

- `canopy://dbc/{name}` — the loaded DBC's signal definitions
- `canopy://session/{id}/metadata` — session structure

Resources differ from tools in that the *client* decides to include them, not the model. Using one correctly demonstrates you understand the distinction, which is a genuine depth signal.

### Prompts (optional, high-value for the README)

Reusable prompt templates the server offers. E.g. a `diagnose_session` prompt that pre-loads the right framing. Cheap to add, and shows you read past the tools section of the spec.

---

## Deriving JSON Schema from Pydantic

Do not hand-write JSON Schema. Your Pydantic models already are the schema.

```python
GetSignalInput.model_json_schema()
```

This is why Doc 03 insisted on `Field(..., description=...)` for every parameter — those descriptions land in the schema and reach the model. A parameter described only by its type name is a parameter the model will fill in wrong.

**Verify it.** Print the generated schema for each tool and read it as the model would. If `max_samples` shows up as `{"type": "integer"}` with no description, you have lost information between your intent and the model's context.

---

## Errors over the protocol

Doc 03 established: **errors are results, not exceptions.** MCP formalizes this.

A tool that fails must return a tool result with an error indication and a readable payload — not raise, not crash the server, not return an empty success.

```json
{
  "isError": true,
  "content": [{
    "type": "text",
    "text": "{\"error\": \"unknown_signal\", \"requested\": \"RearCameraActivation\", \"message\": \"Signal not available from source 'obd'.\", \"available_signals\": [\"EngineRPM\", \"VehicleSpeed\", \"CoolantTemp\"], \"hint\": \"This source cannot provide ADAS or camera signals.\"}"
  }]
}
```

The recovery information travels *with* the error. The model reads `available_signals` and `hint` and self-corrects inside the loop. This is the difference between an agent that recovers and one that spirals.

**Distinguish two error classes**, and handle them differently:

- **Tool errors** (unknown signal, bad time range) → return as tool result, model sees them, model adapts.
- **Protocol errors** (malformed request, server not initialized) → JSON-RPC error response, model never sees them, they are your bug.

Conflating these is a common mistake. A protocol error surfaced to the model produces confused reasoning about something the model cannot fix.

---

## Server lifecycle

Implement, in order:

1. **Initialize.** Client and server negotiate protocol version and capabilities. Declare that you offer tools (and resources, if you added them).
2. **List tools.** Return name, description, and input schema for each. This is discovery.
3. **Call tool.** Validate input against schema, dispatch to the handler, return content or `isError`.
4. **Shutdown.** Release the reader. If `ObdReader` holds a serial port, this matters.

State to hold: which `SignalReader` is active. Everything else is stateless per call — deliberately, because it keeps the server simple and makes each tool call independently testable and replayable (which Doc 07's eval harness depends on).

---

## Configuration: which reader is active

The server needs to know whether it is talking to synthetic data, a dongle, or a CAN log.

```python
# Environment-driven, not hardcoded.
CANOPY_SOURCE = "synthetic" | "obd" | "can_log"
CANOPY_DBC_PATH = "data/dbc/open_vehicle.dbc"     # can_log only
CANOPY_CAPTURE  = "data/captures/session_047.log" # can_log only
```

**The reader choice must be invisible above the seam.** The MCP server passes the configured `SignalReader` down; the tool layer never inspects its type. `list_available_signals` reports `source` so the *model* knows, but the *code* does not branch on it.

This is the payoff of Doc 02. Phase 5 is `CANOPY_SOURCE=can_log` and nothing else changes.

---

## Testing the server without an agent

You can fully validate Phase 2 with no LLM.

- **Discovery test.** Connect a bare MCP client, list tools, assert four tools with non-empty descriptions and valid schemas.
- **Schema round-trip test.** Every advertised schema validates the corresponding Pydantic model's example input.
- **Invocation test.** Call `get_signal` with valid input against `SyntheticReader`; assert the series comes back.
- **Error test.** Call `get_signal` with an unknown name; assert `isError: true` and that `available_signals` and `hint` are present in the payload.
- **Lifecycle test.** Initialize, call, shut down cleanly. No leaked file handles.
- **Claude Desktop smoke test.** Register the server, ask it something in natural language, watch the tool calls. This is not a unit test but it is the most informative five minutes of Phase 2.

That last one is also your first honest encounter with the model misusing a tool. Write down what it did wrong. That note becomes a description fix, and the before/after belongs in `10-build-log.md` — Doc 03 warned that *"the model kept doing X, so I added this sentence"* is worth more than any architecture diagram.

---

## Definition of done — Phase 2

- [ ] MCP server exposes four tools over stdio
- [ ] Tool schemas auto-derived from Pydantic, with parameter descriptions intact
- [ ] Tool errors return `isError` with structured, recovery-bearing payloads
- [ ] Protocol errors distinguished from tool errors
- [ ] Reader selection is environment-driven; no type-branching above the seam
- [ ] Clean initialize / list / call / shutdown lifecycle
- [ ] Server registered in Claude Desktop and exercised interactively at least once
- [ ] At least one observed model-misuse incident recorded in the build log
- [ ] Seam test still passes — nothing in `mcp/` imports `obd`, `dbc`, or `cantools`
- [ ] **Still no LangGraph, still no agent loop**

---

## Questions to be ready for

> *"What problem does MCP solve?"*

The N×M integration problem. Every agent framework used to invent its own tool glue, so tools weren't portable. MCP standardizes discovery and invocation so any client can use any server. N×M becomes N+M.

> *"How is your MCP server different from a REST API over your tools?"*

Discovery and schema advertisement. A REST client needs out-of-band documentation to know what endpoints exist and what they accept. An MCP client asks the server at runtime and gets machine-readable schemas plus natural-language descriptions written *for a model to read*. The description is a first-class protocol element, not a comment.

> *"Why stdio instead of HTTP?"*

Because the client is a local process, stdio removes auth, ports, and TLS from the problem, and it is what Claude Desktop expects. HTTP would add operational surface that teaches nothing about agent design. The transport is swappable if a deployed demo ever needs it.

> *"What happens if a tool throws?"*

It doesn't reach the model as an exception. It's caught and returned as a tool result with `isError: true`, carrying the available signals and a hint. The model reads that and self-corrects on the next turn. An uncaught exception would either crash the loop or, worse, surface as a protocol error the model can't act on.
