# 03 — Tool Design Spec

**Phase:** 1
**Status when done:** four tools exist, each with a Pydantic schema and a deliberately-written description, each unit-tested. Still **no LLM in the repo.**

---

## The central insight of this document

> **The model chooses tools by reading their descriptions.**

That sentence is the entire discipline. A tool description is not documentation for humans. It is a *prompt fragment* that the model reads at decision time, under uncertainty, with no ability to ask you a follow-up question.

Most engineers write tool descriptions the way they write docstrings — describing what the function does. That is necessary and insufficient. A good tool description also tells the model:

- what the tool **cannot** do
- **when not to call it**
- what the parameters **mean semantically**, not just their types
- what the result will and won't contain

The failure mode is specific and worth naming: **a vague tool description makes the model misuse the tool.** It will call `get_signal` for a camera-timing question, get an `UnknownSignalError`, and — depending on how you handle errors — either loop forever or invent an answer. Both are your fault, not the model's.

---

## Anatomy of a tool

Each tool is three things:

1. **An input schema** (Pydantic) — the model fills this in
2. **A description** (prose) — the model reads this to decide
3. **A handler** (Python) — calls down through the seam into `domain/` and `readers/`

The handler is trivial. The schema is mechanical. **The description is the craft.**

---

## The four tools

### Tool 1 — `list_available_signals`

The most important tool, and the one most people forget to build.

```python
class ListAvailableSignalsInput(BaseModel):
    """No parameters. Returns everything the current data source exposes."""
    pass


class SignalDescriptor(BaseModel):
    name: str
    unit: str
    typical_range: tuple[float, float] | None
    description: str          # human-meaningful, e.g. "crankshaft rotational speed"


class ListAvailableSignalsOutput(BaseModel):
    source: SignalSource
    signals: list[SignalDescriptor]
```

**Description (what the model reads):**

> Returns the complete list of signals available from the currently connected data source, with units and typical ranges.
>
> **Call this first** whenever you are unsure whether a signal exists. Signal availability depends entirely on the data source: an OBD-II connection exposes only standardized emissions-related parameters, while a CAN log exposes whatever signals its DBC defines.
>
> If the signal a user asks about does not appear in this list, it is **not available** — do not attempt to retrieve it, do not estimate it, and do not substitute a related signal. Tell the user the signal is unavailable and say which source is connected.

**Why this tool exists:** it is the mechanism by which the agent can *know what it cannot answer.* Without it, a model asked about rear-camera timing over an OBD connection has no way to discover its own ignorance, and will confabulate. With it, the refusal path is grounded in a tool result rather than in the model's self-knowledge — which is far more reliable.

This is the tool that turns "the agent hallucinated" into "the agent checked, found nothing, and said so."

---

### Tool 2 — `get_signal`

```python
class GetSignalInput(BaseModel):
    name: str = Field(
        ...,
        description=(
            "Canonical signal name, exactly as returned by list_available_signals. "
            "Case-sensitive. Do not guess or abbreviate."
        ),
    )
    start: datetime = Field(
        ...,
        description="Start of the time range, inclusive, ISO 8601.",
    )
    end: datetime = Field(
        ...,
        description="End of the time range, inclusive, ISO 8601.",
    )
    max_samples: int = Field(
        default=200,
        le=1000,
        description=(
            "Downsampling cap. The full series is decimated to at most this many "
            "evenly-spaced samples. Raise it only when fine timing detail matters; "
            "large values consume context without adding insight."
        ),
    )


class GetSignalOutput(BaseModel):
    series: SignalSeries
    truncated: bool
    actual_sample_rate_hz: float | None
    note: str | None   # e.g. "Point read: OBD returns a single sample."
```

**Description:**

> Retrieves one signal over a time range, returned as a timeseries with explicit units and timestamps.
>
> The signal `name` must exactly match a name from `list_available_signals`. Calling this with an unknown name returns an error — it does not return an estimate.
>
> Note that different data sources have very different sample rates. An OBD-II source is request-response and typically returns a **single sample** (a "point read"), with `actual_sample_rate_hz` set to null. A CAN log returns a true timeseries, often at hundreds of hertz. **Do not perform timing analysis on a point read** — check `actual_sample_rate_hz` before reasoning about how a signal changed over time.
>
> Results are downsampled to `max_samples`. If `truncated` is true, the returned series is a decimation of the full data, and fine timing detail may be lost.
>
> **Some sources expose more than one bus channel** (e.g. `HS1`, `HS2`). `list_available_signals` pairs each name with its channel. If the same `name` appears on more than one channel, it is **ambiguous** — the reader cannot know which bus you mean, and reading it may return the wrong signal or an error. Confirm the name resolves to a single channel before relying on the result, and say which channel your answer rests on. A `null` channel means a single-channel source, where no ambiguity exists.

**The two paragraphs after the first are doing the real work.** They pre-empt the single most likely reasoning error: treating a one-sample OBD read as though it were a timeseries and confidently announcing that a signal "remained stable."

---

### Tool 3 — `run_diagnostic_rules`

```python
class RunDiagnosticRulesInput(BaseModel):
    start: datetime
    end: datetime
    rule_ids: list[str] | None = Field(
        default=None,
        description=(
            "Specific rules to run. Omit to run all rules applicable to the "
            "available signals. Rules whose required signals are unavailable "
            "are skipped and reported in `skipped`."
        ),
    )


class RunDiagnosticRulesOutput(BaseModel):
    findings: list[Finding]
    rules_run: list[str]
    skipped: list[dict]        # {rule_id, reason: "requires signal X, unavailable"}
```

**Description:**

> Runs the domain diagnostic rule set over a time range and returns structured findings, each citing the specific data samples that support it.
>
> Every finding includes `evidence` — the actual samples the rule examined — and a `confidence` level. A finding with `confidence: "low"` usually means the rule ran against insufficient data (for example, a timing rule given a single-sample point read). **Report low-confidence findings as tentative; never present them as established fact.**
>
> Rules requiring signals the current source cannot provide are skipped, not failed. Check `skipped` before concluding that no problems exist — an empty `findings` list with a non-empty `skipped` list means "we didn't look," not "nothing is wrong."

**The last sentence is the most valuable sentence in this document.** It encodes the difference between absence of evidence and evidence of absence, which is exactly the reasoning error that makes AI systems dangerous in a compliance context. Writing it into the tool description is more reliable than hoping the model infers it.

---

### Tool 4 — `summarize_session`

```python
class SummarizeSessionInput(BaseModel):
    start: datetime
    end: datetime


class SummarizeSessionOutput(BaseModel):
    source: SignalSource
    duration_s: float
    signals_present: list[str]
    sample_counts: dict[str, int]
    coverage_gaps: list[dict]      # {signal, gap_start, gap_end, duration_s}
    finding_counts: dict[str, int] # {"violation": 0, "warning": 2, "info": 5}
```

**Description:**

> Returns a structural overview of a data session: which signals are present, how many samples each has, where there are gaps in coverage, and a count of findings by severity.
>
> Use this **before** detailed analysis to understand what data actually exists. This tool returns no interpretation — only structure. It will not tell you what a finding means; call `run_diagnostic_rules` for that.
>
> `coverage_gaps` matters: a signal can be "present" while missing the exact interval a user is asking about.

**Why a purely structural tool:** it gives the agent a cheap first move that constrains all subsequent reasoning, and it costs few tokens. Good agent design front-loads cheap orienting calls before expensive ones.

---

## Description-writing rules, extracted

These generalize beyond this project and are worth internalizing, because they are the substance of the "tool/function calling" bullet on every job posting.

1. **State the negative space.** What the tool cannot do, explicitly. `"Cannot access ADAS, camera, or body-control signals."`
2. **Say when not to call it.** `"Do not attempt to retrieve it, do not estimate it, do not substitute a related signal."`
3. **Name the likely reasoning error and forbid it.** `"Do not perform timing analysis on a point read."`
4. **Distinguish absence from negation.** `"An empty findings list with a non-empty skipped list means 'we didn't look,' not 'nothing is wrong.'"`
5. **Describe parameters semantically.** `max_samples` isn't "an integer" — it's "a downsampling cap; large values consume context without adding insight."
6. **Put the unit in the payload.** Never return a bare float. The model will guess the unit, confidently.
7. **Order tools by cost.** Cheap orienting tools (`list_available_signals`, `summarize_session`) should read as things to call first.

---

## Return-shape discipline

Tool results are serialized into the model's context. Two consequences.

**Token economy.** A 10,000-sample series is both useless to the model and expensive. Hence `max_samples` with a hard cap. Hence a `truncated` flag so the model knows it's looking at a decimation.

**Errors are results, not exceptions.** An `UnknownSignalError` must reach the model as a structured, readable tool result:

```json
{
  "error": "unknown_signal",
  "requested": "RearCameraActivation",
  "message": "Signal not available from source 'obd'.",
  "available_signals": ["EngineRPM", "VehicleSpeed", "CoolantTemp", "..."],
  "hint": "This source cannot provide ADAS or camera signals."
}
```

If you let the exception propagate and crash the loop, you learn nothing. If you return this, the model recovers gracefully — and you have demonstrated error handling in an agentic system, which is a real interview topic.

Note that the error payload **includes the recovery information.** Don't just say no; say no and hand the model what it needs to do better. This is a general principle of agent tool design.

---

## Testing tools without an LLM

You can and should fully test Layer 2 before any model exists.

- **Schema tests.** Invalid input rejected; valid input parsed. `max_samples > 1000` fails.
- **Handler tests.** Against `SyntheticReader` with a fixed seed, `get_signal` returns the expected series.
- **Error-path tests.** `get_signal("Nonexistent")` returns the structured error dict, not an exception.
- **The point-read test.** `ObdReader` (or a stub) returns `is_point_read == True` and `actual_sample_rate_hz is None`.
- **The skip test.** `run_diagnostic_rules` with a timing rule and an OBD source returns empty `findings` and non-empty `skipped`.
- **The seam test.** Grep asserts nothing in `tools/` imports `obd`, `dbc`, or `cantools`.

That last one keeps you honest. The tool layer speaks `SignalReader` and `SignalSeries` only.

---

## Definition of done — Phase 1

- [ ] Four tools with Pydantic input and output schemas
- [ ] Each description states negative space, when-not-to-call, and the likely reasoning error
- [ ] `list_available_signals` exists and is described as "call this first"
- [ ] Errors return structured payloads with recovery hints, never raw exceptions
- [ ] `max_samples` enforced with a hard cap and a `truncated` flag
- [ ] Full unit-test coverage, all against `SyntheticReader`
- [ ] Seam test passes
- [ ] **Still no LLM code in the repo**

---

## Questions to be ready for

> *"How do you stop the model from calling the wrong tool?"*

You don't stop it — you make the right choice obvious and the wrong choice self-correcting. The description states negative space explicitly, a cheap `list_available_signals` tool lets it check before committing, and every error result carries recovery hints so a wrong call becomes a learning step inside the loop rather than a crash.

> *"What happens when a tool returns 10,000 samples?"*

It doesn't, because `max_samples` caps at 1000 and defaults to 200, and the result carries a `truncated` flag so the model knows it's reasoning over a decimation. Uncapped tool output is the most common way agentic systems blow their context window.

> *"Show me a tool description you rewrote."*

Have a real answer. Keep the first draft of one description in `10-build-log.md` alongside the version that fixed an observed failure. Being able to say *"the model kept doing X, so I added this sentence, and it stopped"* is worth more than any architecture diagram.
