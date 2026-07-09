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
`CANOPY_SOURCE=synthetic`). The interactive exercise — and whatever the model does wrong
during it — still has to happen; restart Claude Desktop and ask it a diagnostics question.*

---

### [ ] Phase 3 — Iteration cap distribution
**Type:** number

Doc 05: *"Set `max_iterations = 8` as a starting point. Log the actual distribution. If real questions routinely need six, your tools are too granular."*

Record the histogram. If you retune the cap or merge tools, that's a decision entry too.

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

### [ ] Phase 4 — Rubric calibration
**Type:** decision

Doc 07: the calibration session *"is where you discover that 'overconfident' meant three different things to three people."*

Solo project, so you're the panel. Score 20 traces, wait a week, score them again blind. Where did you disagree with yourself? Those are the rubric's soft spots. **Record the self-agreement number** — Doc 09 requires you to state it as the ceiling for your judge.

---

### [ ] Phase 4 — Judge disagreement examples
**Type:** number

Doc 07 wants `disagreement_examples: list[str]` for the README. Pull two or three trace IDs where the judge and you diverged, and write *why*. Almost certainly `OVERCONFIDENT` — a judgment call a rubric only partially disciplines.

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
