# 10 — Build Log

**Phase:** continuous. Write entries *as they happen*, not reconstructed afterward.

---

## Why this file exists

Doc 03 said it plainly:

> Being able to say *"the model kept doing X, so I added this sentence, and it stopped"* is worth more than any architecture diagram.

That story only exists if you wrote it down when it happened. A week later you'll remember that the agent misbehaved; you won't remember the exact description that fixed it, or what it did before, or why your first fix didn't work.

This log is the raw material for the Tier 3 interview answers in Doc 09 — the ones where you separate from the field. It is also the honest record of where the architecture leaked, which is a better story than pretending it never did.

**Rule:** if a debugging session took more than twenty minutes, it earns an entry.

---

## Entry types

Use whichever fits. Don't force a format.

| Type | When | Why it matters later |
|---|---|---|
| **Model misuse** | The agent did something wrong you had to fix in a description or prompt | Tier 3, "show me a description you rewrote" |
| **Decision** | You chose between two defensible options | "Why did you...?" questions |
| **Leak** | Something above the seam had to change | Honest architecture story |
| **Surprise** | Reality contradicted the design doc | Proves you observed rather than assumed |
| **Number** | You measured something | README material |

---

## Template

```markdown
### [YYYY-MM-DD] Phase N — <short title>
**Type:** model misuse | decision | leak | surprise | number

**What happened**
<Concrete. What did you observe? Paste the actual bad output.>

**Why**
<Your diagnosis. If you were wrong at first, say so and say what changed your mind.>

**Fix**
<Before/after. For descriptions, paste both versions verbatim.>

**Did it work**
<How you verified. Which test, which eval case.>

**Open question**
<Optional. What you still don't understand.>
```

---

## Entries

### [2026-07-08] Phase 1 — Signal metadata lives on the reader, not a shared registry
**Type:** decision

**What happened**
`list_available_signals` (and `summarize_session`) need each signal's unit, typical range,
and human gloss — metadata that in Phase 0 lived in a private `SyntheticReader.signal_descriptor()`
returning the internal `_SignalSpec`. The tool layer may only reach data through the
`SignalReader` protocol (Constraint 1), so it could not call that private method.

**Why**
Two options: (a) add `describe(name) -> SignalDescriptor` to the protocol so each reader owns
its own metadata; (b) put a canonical metadata registry in `domain/` keyed by name. Chose (a).
A shared registry can silently drift from what a reader actually produces — the OBD reader and
the CAN reader will legitimately expose different units and ranges for overlapping concepts,
and a central table would have to special-case per source, which is exactly the source-branching
the seam forbids. Metadata is a property of the source, so it belongs on the reader.

**Fix**
Added a public `SignalDescriptor` model to `model/signals.py`, `describe()` to the
`SignalReader` protocol, and a `source` property alongside it (the tools need to report
provenance without reading a sample). Replaced `signal_descriptor()`/`_SignalSpec` leakage
with `describe()` returning the public model.

**Did it work**
`test_list_available_signals_returns_all_descriptors` and the seam test both pass; nothing
above the seam names a data source.

**Open question**
When two readers disagree on a signal's unit, is the canonical name still the right join key,
or does the agent need to see the source-qualified descriptor? Revisit in Phase 5.

---

### [2026-07-08] Phase 1 — Deferred the real ObdReader; simulate point reads with synthetic
**Type:** decision

**What happened**
docs/03's point-read and skip tests reference "ObdReader (or a stub)." Building a real OBD
reader now would make the point-read story concrete.

**Why**
The Phase 1 definition-of-done says all tests run against `SyntheticReader`, and a zero-span
read (`start == end`) already degrades to a single-sample point read — the exact OBD behaviour.
Building ObdReader now expands Phase 1 beyond its DoD for no test coverage that synthetic can't
already provide. The rule-skip path (a source lacking a required signal) is exercised with a
small in-test `_LimitedReader` stub rather than a whole new concretion.

**Fix**
Point-read test uses `get_signal(..., start=T0, end=T0)`. Skip test uses `_LimitedReader`
withholding `EngineLoad`. No `readers/obd.py` yet.

**Did it work**
`test_get_signal_point_read_sets_null_rate_and_note` and
`test_run_diagnostic_rules_skips_when_signal_unavailable` pass. ObdReader is a Phase 1.5 /
Phase 5 concern.

---

### [2026-07-08] Phase 1 — Tool-description "before" baseline (rewrite pending a model)
**Type:** model misuse *(pre-observation)*

**What happened**
Doc 03's DoD and the seed entry below both want the first tool-description rewrite — the
"the model kept doing X, so I added this sentence, and it stopped" story. At the end of
Phase 1 that story **does not exist, and cannot yet**: there is no model in the repo until
Phase 3, so nothing has misused a tool. Writing a before/after now would be reconstruction —
the exact anti-pattern this file warns against ("Don't reconstruct. Don't sanitize.").

**What I did instead**
Froze the two descriptions most likely to generate the story as the *before* baseline, so
the first real misuse in the Phase 2 Claude Desktop smoke test (or the Phase 3 loop) has an
exact prior version to diff against. Verbatim, as committed in Phase 1:

`get_signal` — guards against timing analysis on a point read, and unknown-name calls:
```
Retrieves one signal over a time range, returned as a timeseries with explicit units and
timestamps.

The `name` must exactly match a name from list_available_signals. Calling this with an
unknown name returns a structured error, not an estimate.

Different data sources have very different sample rates. A request-response source may
return a SINGLE sample (a 'point read'), with actual_sample_rate_hz set to null. Do NOT
perform timing analysis on a point read — check actual_sample_rate_hz before reasoning about
how a signal changed over time.

Results are downsampled to max_samples. If `truncated` is true, the series is a decimation
of the full data and fine timing detail may be lost.
```

`list_available_signals` — the "call first" / know-what-you-can't-answer tool:
```
Returns the complete list of signals available from the currently connected data source,
with units and typical ranges.

Call this FIRST whenever you are unsure whether a signal exists. Signal availability depends
entirely on the data source, so the only reliable way to know what you can answer is to ask.

If the signal a user asks about does not appear in this list, it is NOT available: do not
attempt to retrieve it, do not estimate it, and do not substitute a related signal. Tell the
user the signal is unavailable and say which source is connected.
```

**Prediction to test (fill the "after" in Phase 2/3)**
Per the seed entry: the model will likely either (a) call `get_signal` for a signal that
doesn't exist instead of `list_available_signals` first, or (b) do timing analysis on a
point read despite the note. Whichever sentence I add to stop it, diffed against the text
above, becomes the Tier 3 answer.

**Status of the Doc 03 checkbox**
Honestly *not done* — deferred to first observation, not skipped. Baseline is captured so it
becomes a one-line before/after the moment a model misbehaves.

---

### [2026-07-08] Phase 2 — Low-level `Server` with a directly-registered call handler, not FastMCP
**Type:** decision

**What happened**
The MCP Python SDK offers two server APIs: `FastMCP` (decorate a plain function, schema
inferred from its signature) and the low-level `Server` (register handlers, hand it
`types.Tool` objects yourself). Chose the low-level API, and registered the call-tool
handler directly into `server.request_handlers[types.CallToolRequest]` rather than via the
`@server.call_tool()` decorator.

**Why**
Two docs/04 requirements decided it. First, the tool schemas must be the Doc-03 Pydantic
models' `model_json_schema()` verbatim — FastMCP re-derives schemas from function
signatures, which would put a second schema authority next to the one Phase 1 deliberately
built. Second, tool errors and protocol errors must stay distinct: the `@server.call_tool()`
decorator catches *all* handler exceptions and converts them into `isError` tool results,
which would launder a protocol error (unknown tool name — the client's bug) into a payload
the model is asked to reason about. Registering the handler directly lets a raised
`McpError` propagate to the framework and come back as a JSON-RPC error the model never
sees, while genuine tool errors return as `isError` payloads.

**Did it work**
`test_unknown_tool_is_a_protocol_error_not_a_tool_result` asserts `McpError` with
`METHOD_NOT_FOUND` on the client side; `test_unknown_signal_is_a_tool_error_with_recovery_payload`
asserts the same server returns `isError: true` with `available_signals` + `hint` for the
model-recoverable case. Both pass over the SDK's in-memory transport, and
`scripts/smoke_mcp.py` confirms the stdio path end-to-end (10/10).

**Open question**
The direct `request_handlers` registration reaches past the decorator API into SDK
internals. If a future SDK version changes how handlers are wired, this is the seam-adjacent
spot that breaks. Revisit if/when the SDK grows a public way to opt out of exception
conversion.

---

### [2026-07-08] Phase 2 — Invalid arguments are a tool error, not a protocol error
**Type:** decision

**What happened**
docs/04 lists "malformed request" under protocol errors. Arguments that fail Pydantic
validation (e.g. `max_samples: 5000` against a `le=1000` field) are literally a malformed
request — but the server returns them as an `isError` tool result with field-level details,
not as a JSON-RPC error.

**Why**
The classification test isn't "who violated the schema" but "who can fix it." A malformed
JSON-RPC envelope or an unadvertised tool name is the *client's* bug — the model can't act
on it, so surfacing it as a tool result produces confused reasoning about something outside
the model's control. But schema-violating *arguments* are text the model itself emitted, and
the model can fix them on the next turn — exactly the recovery loop tool errors exist for.
So: envelope/dispatch failures → JSON-RPC error; argument validation failures → `isError`
with `{field, problem}` pairs and a hint to re-read the schema.

**Did it work**
`test_invalid_arguments_is_a_tool_error_with_field_details` passes: `max_samples: 5000`
comes back `isError: true`, `error: "invalid_arguments"`, with `max_samples` named in
`details`. Whether the model actually self-corrects from it is a Phase 3 observation — if it
doesn't, the `hint` text is the first thing to rewrite, and that becomes a model-misuse
entry.

---

### [2026-07-08] Phase 3 — Agent executes tools in-process, not over an MCP stdio client
**Type:** decision

**What happened**
Doc 05's node listing says the `tools` node "executes requested tools via the MCP client."
The implemented node calls the tool layer directly instead: `_ToolSpec`/`_TOOLS` were
extracted out of `mcp/server.py` into `tools/registry.py` (one authority for
name/description/schema/handler), and both the MCP server and the agent's `ToolExecutor`
consume that registry.

**Why**
Spawning a stdio subprocess and running an async MCP session inside a LangGraph node buys
protocol fidelity the loop doesn't need and costs test hermeticity — every loop test would
drag in a subprocess and an event loop. What actually matters is that the agent and the
server can never drift: same names, same descriptions, same schemas, same dispatch
semantics (invalid arguments and unknown signals come back as structured error payloads in
both). The shared registry guarantees that structurally. The MCP transport itself is
already exercised end-to-end by the Phase 2 tests and `scripts/smoke_mcp.py`. If a real
remote-tool deployment arrives later, `ToolExecutor` is the single seam to swap.

**Did it work**
The whole Phase 3 loop suite runs in-process with a scripted model — no network, no key,
sub-second. `test_mcp_server.py` still passes against the registry-backed server.

**Open question**
An MCP-client-backed `ToolExecutor` would make the "agent ↔ server over the wire" demo
more literal. Worth doing as a follow-up if an interviewer is likely to probe it.

---

### [2026-07-08] Phase 3 — The forced final turn keeps `submit_answer`/`refuse` bound
**Type:** decision

**What happened**
Doc 05 says the iteration cap triggers "one final turn with the tools *unbound*." Implemented
as: the four *data* tools unbind, but the two virtual channels (`submit_answer`, `refuse`)
stay bound.

**Why**
Structured output arrives through the tool-call channel (Doc 06's preferred mechanism). If
*every* tool unbinds, the forced turn can only produce prose — which then fails validation
and burns the retry budget on a turn we ourselves forced. Keeping the answer channels bound
preserves both properties at once: the model can retrieve nothing further, and the degraded
honest answer still lands as a validated `DiagnosticAnswer` with `could_not_determine`
filled. "Tools unbound" is read as "data acquisition unbound."

**Did it work**
`test_iteration_cap_forces_a_final_turn_with_data_tools_unbound` asserts the final
invocation carried exactly `[submit_answer, refuse]` and that the answer validated.

---

### [2026-07-08] Phase 3 — Prose-where-an-answer-belongs consumes the validation-retry budget
**Type:** decision

**What happened**
Doc 05's graph has exactly four nodes, and its routing assumes the model either calls tools,
answers, or refuses. A real model has a fourth move: reply in plain prose. That case is
routed to the `validate` node, which treats "no structured answer" as a validation failure —
feedback message, bounded retry, degrade on exhaustion.

**Why**
The alternative was a fifth "nudge" node or an unbounded re-prompt loop. Folding it into
validation keeps the graph at the four specced nodes and — more importantly — keeps *every*
malformed-final-output path behind one bounded counter. There is now no shape of model
misbehavior at answer time that can loop forever or crash: tool-call answers validate,
prose gets two chances to become structured, then the code-built degraded answer ships.

**Did it work**
`test_prose_final_reply_is_nudged_into_the_structured_channel` (recovers on retry) and
`test_retry_exhaustion_degrades_to_a_code_built_answer_not_an_exception` (never recovers,
degrades honestly) both pass.

---

### [2026-07-08] Phase 2 — Smoke-tested the live server against a real model; baseline, not a before/after
**Type:** surprise *(doubles as the Phase 2 interactive-exercise record)*

**What happened**
Drove the registered `canopy` stdio server with a real Opus model — the same server Claude
Desktop launches (`python -m canopy.mcp`, `CANOPY_SOURCE=synthetic`), same crafted descriptions
travelling over the wire, a live model on the other end. Ran all four tools against a natural
diagnostics session. Three observations:

1. **The refusal path survives the protocol.** `get_signal("BrakePedalPressure")` came back as a
   structured tool error, not an exception, carrying the recovery payload verbatim:
   ```json
   {"error": "unknown_signal", "requested": "BrakePedalPressure",
    "message": "Signal 'BrakePedalPressure' is not available from the connected source.",
    "available_signals": ["EngineRPM","VehicleSpeed","CoolantTemp","EngineLoad","ThrottlePosition"],
    "hint": "The connected source does not expose this signal. Call list_available_signals to see
             what it does expose. Do not estimate a value or substitute a related signal — tell the
             user it is unavailable."}
   ```
   Constraint 3 holds end-to-end, not just in the unit tests: the `hint` that forbids substitution
   reaches the model as data it can act on.

2. **A real gap: no time-range discovery.** Every time-scoped tool demands ISO `start`/`end`, but
   nothing tells the model what window the data covers — I had to guess timestamps. Worse,
   `summarize_session` accepts *any* window and reports it fully present. Asked for a whole day it
   synthesised `863991` samples per signal, `coverage_gaps: []`. So a natural question — "was coolant
   OK on my last drive?" — is unanswerable: there is no affordance to scope "the drive." The
   synthetic reader has no notion of a bounded session; it generates on demand.

3. **The point-read trap is currently unreachable.** `get_signal`'s most heavily-defended paragraph
   ("do NOT perform timing analysis on a point read") guards a failure mode that cannot occur yet:
   synthetic always returns a full timeseries, and there is no `ObdReader` (deferred — see the
   2026-07-08 Phase 1 entry). The description defends against a source that does not exist yet.

**Why**
The interesting one is (2). Doc 03 designed the tools around a signal-name axis (what exists) and got
that right — `list_available_signals` plus the structured error make "what can't I answer" reliable.
But there is a second axis, *when does the data exist*, with no discovery tool. On synthetic that
axis is invisible because data is infinite; on a real capture (Phase 5) it becomes load-bearing, and
`summarize_session` reporting a fabricated window as gap-free is actively misleading rather than
merely unhelpful.

**Fix**
None yet — this run is the **baseline**, deliberately. Honest caveat, stated for the interview: the
model driving the tools had already read the descriptions and the constraints, so it made the right
tool choices for the right reasons. That is *not* a clean observation of a naive model, so there is
**no legitimate "the model kept doing X, so I added this sentence" before/after here** — writing one
would be the reconstruction this file forbids. What this run *is*: (a) the Phase 2 DoD
"exercised interactively at least once," done for real; (b) confirmation the refusal mechanism
survives the wire; (c) the first fixed point to diff a naive or weaker model against.

**Did it work**
As a smoke test, yes — four tools discovered and invoked over stdio, refusal payload intact,
`run_diagnostic_rules` returned `rules_run: ["correlation.coolant_rising_under_moderate_load"]`,
`skipped: []`. As a source of the headline description-rewrite story, no — see caveat. The next
move is a naive question against a weaker model (Claude Desktop on Haiku): ask "what was my oil
temperature this afternoon?" — oil temp is unavailable but `CoolantTemp` is one substitution away —
and see whether it refuses or substitutes. Whatever sentence stops the substitution, diffed against
today's `get_signal`/`list_available_signals` text, becomes the real Tier-3 answer.

**Open question**
Does the time-range gap warrant a fifth tool (session bounds / available intervals), a field on
`summarize_session` distinguishing "data present" from "window you asked for," or is it purely a
Phase 5 concern once captures are finite? Leaning toward: `summarize_session` should not claim
coverage for a window that exceeds the source's real extent. Revisit when the first capture lands.

---

### [2026-07-08] Phase 3 — Gemini (free tier) is the default provider; Anthropic stays optional
**Type:** decision

**What happened**
Phase 3's loop needs a real model behind it. Wired `scripts/ask.py` to two providers through
LangChain's chat interface — `--provider gemini` (default, `gemini-2.5-flash`) and
`--provider anthropic` (`claude-sonnet-4-6`) — with the key read from a gitignored `.env`
(`.env.example` committed, the key never enters the tree — Constraint 2 applies to secrets too).

**Why**
The whole point of the `langchain-core` seam is that the loop doesn't care who answers; the
provider is a one-line swap at the edge (`_build_model`), never inside the graph. Defaulted to
Gemini because its free tier needs no credit card (10 RPM / 250k TPM / 1.5k RPD, 1M context) —
anyone cloning the repo can run the agent for zero dollars, which matters for a portfolio piece.
Anthropic stays a flag away for when a stronger model is worth the key. Graph, tools, and
contracts are identical across both.

**Did it work**
End-to-end runs below (the "number" entry). Constraint 1 still holds: nothing above the seam
names a provider any more than it names a data source — `agent/` binds an abstract chat model,
`ask.py` picks the concretion.

---

### [2026-07-08] Phase 3 — Gemini's tool adapter warns on Pydantic `$defs`; inline them at the seam
**Type:** surprise

**What happened**
First live Gemini run printed, once per bound tool per turn:
```
Key '$defs' is not supported in schema, ignoring
```
The run *worked* — the answer validated — but the noise appeared on every invocation.

**Why**
Pydantic v2 factors nested models (`submit_answer` carries `claims → citations`) into a
top-level `$defs` block referenced by `$ref`. `langchain_google_genai` inlines the `$ref`
targets but leaves the orphaned `$defs` key behind, then rejects it against its allow-list. The
assumption that a Doc-03 `model_json_schema()` travels cleanly to *any* provider was false: it
travels cleanly to Anthropic, not to Gemini. Left alone, the noise would bury a real warning some
day, and a half-flattened schema is one more thing that can drift.

**Fix**
Added `agent/tool_schema.py::inline_schema_defs` — a pure transform that replaces every `$ref`
with its definition and drops `$defs`, so no indirection reaches the adapter. Names no data
source; lives at the tool-binding seam, not the domain. Before: warning on every turn. After:
silent, same validated answer.

**Did it work**
`test_tool_schema.py` covers the transform (inlining, sibling-key precedence, the acyclic
guard). Live: the coolant-analysis run printed zero schema warnings and produced a validated
`DiagnosticAnswer` with cited claims.

---

### [2026-07-08] Phase 3 — An unbounded window is a structured tool error, not a spun CPU
**Type:** decision *(bears on the open question in the Phase 2 smoke entry)*

**What happened**
While smoke-testing the tool layer, a `get_signal` with a decade-wide window pinned a core for
~90 seconds before it was killed: `n = span_seconds × sample_rate + 1` had the synthetic reader
trying to materialize ~3 billion `SignalSample`s in a Python loop *before* the tool ever
decimated to `max_samples`.

**Why**
Same axis the Phase 2 smoke entry flagged (#2, "no time-range discovery"): the tools are designed
around *what* exists, and the *when* axis had no guard. On synthetic, data is infinite, so an
absurd span is silently expensive rather than impossible. The reader owns the guard because only
it knows its own sample rate, and it must raise *before* materializing — after is too late.
Consistent with Constraint 3: readers raise, the tool layer turns it into a structured payload
the model can act on.

**Fix**
Added `WindowTooLargeError` to `readers/base.py` (carries estimate, cap, and span for recovery),
an `_MAX_MATERIALIZED_SAMPLES = 1_000_000` guard in `SyntheticReader.read` that raises O(1)
before the loop, a `window_too_large_payload` in `tools/errors.py`, and a `try` around
`read`/`run_rules` in all three time-scoped tools (`get_signal`, `run_diagnostic_rules`,
`summarize_session`). Also added a sentence to `get_signal`'s description: a wide window returns
an error, not data, and buys no resolution (results decimate anyway).

**Did it work**
`test_synthetic_reader.py` / `test_tools.py` cover the raise-and-payload path; full suite 76/76.
Doesn't fully close the Phase 2 open question — `summarize_session` still reports a fabricated
window as gap-free *within* the cap — but it removes the pathological case. "Does the window
exceed the source's real extent" stays a Phase 5 concern once captures are finite.

---

### [2026-07-08] Phase 3 — End-to-end verification: 4 tools, 2 terminal states, both live
**Type:** number

**What happened**
Full Phase 3 pass with Gemini driving the real graph. Offline: `pytest` **76/76** (~1s),
`ruff check` clean. Live `gemini-2.5-flash` scenarios — all four tools invoked by the model,
both terminal contracts produced:

| Question | Tools fired | Terminal | iters | val-retries |
|---|---|---|---|---|
| what signals can you read | `list` | answer | 3 | 1 |
| coolant avg + stability | `list → get_signal → submit_answer` | answer w/ cited claims | 6 | 2 |
| diagnostic check | `list → run_diagnostic_rules` | answer | 3 | 0 |
| tire pressure | `list` | refusal (`signal_unavailable`) | 2 | 0 |
| battery + fuel | `list` | refusal (`signal_unavailable`) | 2 | 0 |
| summarize (no window) | `list` | refusal (`time_range_not_covered`) | 3 | 1 |
| summarize (explicit window) | `summarize_session` | answer | 2 | 0 |

**Why it matters**
Constraint 3 holds through the live loop, not just the wire: every out-of-scope question refused
with a structured `Refusal` naming required-vs-available signals — no invented number, once even
refusing rather than inventing a *time range*. Constraint 4 holds too: the coolant answer's claims
each carried real `SignalSample` citations with units, validated by the citation gate (2 retries,
then passed).

**Iteration distribution (see the seed box below)**
Observed iterations across the 7 runs: 2,2,2,3,3,3,6 — max 6 (the claim+citation path), none near
the `max_iterations = 8` cap. Small sample, but no sign the tools are too granular (Doc 05's "if
real questions routinely need six" trigger unmet — the single 6 was the only retrieve-then-cite-
then-submit run). Revisit with a larger sample in Phase 4.

---

### [2026-07-08] Phase 4 — The trace was missing `skipped`; the reviewer would have been blind to it
**Type:** surprise

**What happened**
Doc 05's state tracked `tools_called`, `signals_touched`, and `findings` — but not the
`skipped` list from `run_diagnostic_rules`. Phase 4's whole `ABSENCE_AS_NEGATION` defense
depends on the reviewer (and the judge) seeing that a rule was *skipped*, not that it found
nothing. Building `Trace` surfaced the gap immediately: `to_judge_payload()` had nothing to put
in `skipped`.

**Why**
"Build the trace in Phase 3, you'll need it in Phase 4" (Doc 05) was right in spirit but
incomplete in inventory. `skipped` is the single most important field for distinguishing "we
looked and it's clean" from "we didn't look," and it wasn't being carried out of the tools node.

**Fix**
Added `skipped: list[dict]` to `CanopyState`, harvested it in `tools_node` (dedup on the way
in), and threaded it into `Trace`. No above-seam data-source leak — `skipped` entries are rule
ids and reasons, source-agnostic.

**Did it work**
`test_eval_trace.py::test_skipped_rules_surface_in_the_trace_and_render` and the `hs1_only`
fixture (a channel subset that makes the cooling rule skip) both assert it. `Trace.render()`
prints a `⚠ SKIPPED rules` line with the "we did not look, not healthy" gloss.

---

### [2026-07-08] Phase 4 — The seam test caught a data-source word in an eval comment
**Type:** leak *(caught, not shipped)*

**What happened**
`tests/test_seam.py` failed the moment `evals/cases.py` landed:

```
evals/cases.py:20: # Defense: the refusal path (docs/05). OBD-shaped sources never expose body-control
```

The word `OBD` — in a *comment* — tripped the word-boundary scan for `obd|dbc|cantools` above
the seam.

**Why**
This is the seam doing exactly its job. Above-seam code must be ignorant of whether a number
came from an OBD PID or a decoded CAN frame; naming OBD, even to explain a refusal case, is the
leak. The eval layer describes *what signal is missing*, never *which bus dialect* would carry
it.

**Fix**
Reworded to "This source never exposes body-control signals." The refusal case is unchanged;
only the justification stopped naming the source. Kept as a live entry because a diagnosed leak
(even a comment-level one) is a better artifact than a clean run I got by luck.

**Did it work**
`pytest tests/test_seam.py` green; the eval package carries zero `obd/dbc/cantools` tokens.

---

### [2026-07-08] Phase 4 — Review gate: fixtures by name, so a correction is replayable
**Type:** decision

**What happened**
The review gate's `correct` verdict mints a `from_review` `EvalCase`. That case needs a
`source_fixture` the regression runner can rebuild — but the gate had been handed an arbitrary
`SignalReader`. A reader isn't reconstructible from a serialized eval row; a *fixture name* is.

**Why**
Two options: (a) let the gate accept any reader and store nothing replayable, or (b) require the
gate to run against a *named* fixture resolved below the seam (`readers/fixtures.py`). Chose (b).
The flywheel's premise is that a one-time human correction becomes a *standing regression
defense*, which is only true if the case can be replayed deterministically. Tying the gate to
named fixtures closes the loop by construction instead of hoping the source is reproducible. It
also kept the eval layer seam-clean: it selects a fixture by string and gets back a bare
`SignalReader`, never learning the concretion (exactly like `factory.build_reader`).

**Did it work**
`test_review_gate.py::test_correct_mints_a_from_review_eval_case_with_ground_truth` asserts the
minted case has `source_fixture="clean_full"`, `origin="from_review"`, `source_trace_id` set,
and `must_cite_signals` derived from the reviewer's corrected answer.

---

### [2026-07-08] Phase 4 — Calibration: 85% judge–human, 90% self-agreement ceiling
**Type:** number

**What happened**
`scripts/calibrate.py` over 20 seeded, labelled traces: judge–human agreement **85%**,
self-agreement (same subset, scored twice) **90%**. Per-error-type: `hallucinated_value` and
`absence_as_negation` **100%** (mechanically checkable against the trace), `overconfident`
**85%** — and *every* disagreement (`cal_overconf_02/03/04`) was an overconfidence call.

**Why it matters**
The story is the doc's thesis made concrete: the judge is perfect where a rule can check the
trace and shakiest where a human is exercising judgment. The 85% reads as *approaching* a 90%
ceiling, not falling short of 100% — which is only legible because the ceiling was measured.

**Honesty caveat (stated, not hidden)**
Solo project: no panel, so the ground-truth labels are hand-seeded and the "ceiling" is
self-agreement, not inter-rater. The calibration *machinery* is real and reproducible with no
API key; the *number* firms up as real `from_review` cases replace the seeds. This caveat lives
in `CalibrationReport.single_reviewer_note` and in the README's headline paragraph, because
admitting the limitation is stronger than pretending the number is cleaner than it is.

**Open question**
`per_type_agreement` is presence-based over all traces, which inflates rare types via
true-negatives. A conditional metric (agreement only over traces where *either* side flagged the
type) would make `overconfident` look dramatically weaker (~25%). I kept the presence-based
metric as the honest default but flagged the alternative — worth revisiting with a larger,
real-labelled set.

---

## Seed entries — the things you will almost certainly hit

Pre-written prompts. Fill in the real details when they occur. Delete any that don't.

---

### [ ] Phase 1 — First tool description rewrite
**Type:** model misuse

The most valuable entry in this file. Doc 09 lists it as a Tier 3 question you must have a real answer to.

Watch for: the model calling `get_signal` for a signal that doesn't exist, rather than calling `list_available_signals` first. Or performing timing analysis on a point read despite the warning.

**Capture the before-description verbatim.** Not a paraphrase. The exact text that failed.

---

### [ ] Phase 2 — Claude Desktop smoke test
**Type:** model misuse

Doc 04 called this *"the most informative five minutes of Phase 2"* and predicted it would be your *"first honest encounter with the model misusing a tool."*

Register the MCP server, ask something in natural language, watch the tool calls. Write down exactly what it did wrong before you fix anything.

*Status [2026-07-08]: server registered in `claude_desktop_config.json` (`canopy`, stdio,
`CANOPY_SOURCE=synthetic`) AND exercised interactively once — see the Phase 2 smoke-test entry
above. That run was against a strong model that had read the descriptions, so it produced a
baseline, not a misuse. What still has to happen: the same server against a **naive prompt on a
weaker model** (Claude Desktop on Haiku) to catch a real substitution/refusal failure. Suggested
bait: "what was my oil temperature this afternoon?" (oil temp unavailable, `CoolantTemp` one
substitution away). Keep this box unchecked until a genuine misuse is observed and captured.*

---

### [ ] Phase 3 — Iteration cap distribution
**Type:** number

Doc 05: *"Set `max_iterations = 8` as a starting point. Log the actual distribution. If real questions routinely need six, your tools are too granular."*

Record the histogram. If you retune the cap or merge tools, that's a decision entry too.

*Status [2026-07-08]: first data point captured in the Phase 3 end-to-end entry above — 7 live
Gemini runs, iterations 2,2,2,3,3,3,6, none near the cap. Left unchecked because 7 runs is not a
histogram; needs a proper Phase 4 eval-set sample before the cap decision is defensible.*

---

### [ ] Phase 3 — The validation-retry escape clause
**Type:** surprise

Doc 06 predicted this precisely: told that it cited a signal it never retrieved, a model will often respond by **calling the tool to retrieve it** — chasing a signal that doesn't exist, burning iterations, eventually confabulating.

Did it happen? Did adding the explicit escape instruction stop it? This is a clean before/after and makes an excellent interview anecdote.

---

### [ ] Phase 3 — Markdown fences
**Type:** surprise

Doc 06: *"Every practitioner has independently rediscovered this, and it is a small honest detail worth a line in your build log."*

One line. But it's a real line.

---

### [x] Phase 4 — Rubric calibration
**Type:** decision

Doc 07: the calibration session *"is where you discover that 'overconfident' meant three different things to three people."*

*Resolved [2026-07-08] — see the "Calibration: 85% / 90%" entry above.* Solo panel: scored the
seed set twice (self-agreement **90%**, n=20). Both self-disagreements were `overconfident`
(`cal_overconf_04`, `cal_overconf_05`) — the rubric's soft spot is exactly the judgment-call
type, as predicted. Recorded as the ceiling in `CalibrationReport.self_agreement`.

---

### [x] Phase 4 — Judge disagreement examples
**Type:** number

Doc 07 wants `disagreement_examples: list[str]` for the README.

*Resolved [2026-07-08].* `disagreement_examples = [cal_overconf_02, cal_overconf_03,
cal_overconf_04]` — all three `OVERCONFIDENT`, exactly as Doc 07 predicted: the judge declined
to call thin-but-plausible evidence overconfident where the human did. Surfaced automatically by
`build_calibration_report` and written to `data/evals/calibration_report.json`.

---

### [ ] Phase 5 — Did the seam hold?
**Type:** leak *(hopefully not)*

Doc 08 is unambiguous:

> If any file above the seam changes, the abstraction leaked. Find out where, and say so honestly in the build log. **A leaked abstraction that you diagnosed is a better interview story than a clean one you got by luck.**

Paste the actual `git diff --stat`. If `tools/` or `agent/` shows a nonzero line count, that entry is *more* valuable than a clean diff, not less — provided you explain what assumption in Doc 02 turned out to be wrong.

---

### [ ] Phase 5 — `available_signals()`: DBC contents or capture contents?
**Type:** decision

Doc 08 flagged this as a real design decision with a noted trade-off, and predicted *"someone will ask."* Record which you chose and why.

---

### [ ] Phase 5 — Endianness
**Type:** surprise

Doc 01 warned; Doc 08 called it *"the single most dangerous bug in the project, because it produces numbers. Not exceptions — numbers."*

If the range-check gate caught it, that's a triumphant entry: the defense you built at the bottom of the stack caught the failure that nothing above the seam could have. If it *didn't* catch it and you found it by eye, that's an even better entry — say what you'd change.

---

## Anti-patterns for this file

**Don't reconstruct.** An entry written a month later is a design doc, not a log. It will read as such.

**Don't sanitize.** "I initially thought X, which was wrong, because Y" is the sentence that proves you understand the system. Deleting the wrong turn deletes the evidence of understanding.

**Don't omit the leaks.** Doc 08 again: a diagnosed leak beats a lucky clean run. The interviewer is trying to find out whether you observed a real system or assembled one from a tutorial. Leaks are proof of observation.

**Don't paraphrase model output.** Paste it. The exact confabulated sentence is the artifact.

---

## Harvesting this file

Before applying, mine it for the Doc 09 rehearsal checklist:

- [ ] One **"the model kept doing X, so I added this sentence"** story, with both versions verbatim
- [ ] Your **judge-agreement number** and your **self-agreement ceiling**
- [ ] One **decision** you can defend from either side
- [ ] One **surprise** where reality contradicted your design doc
- [ ] Whether the **seam held**, and if not, precisely where it leaked

Five entries. That's the difference between a repo and a portfolio.
