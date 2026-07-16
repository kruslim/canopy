# Canopy

> An MCP server that exposes vehicle-diagnostic and CAN-bus domain logic as agent tools,
> with a LangGraph orchestration layer and a human-in-the-loop eval harness.

**▶ [Live showcase](https://kruslim.github.io/canopy/)** — replay real recorded traces: a cited
answer and a grounded refusal, with the honest eval numbers. No install, no API key.

**Status: Phase 4 (evals & human-in-the-loop) complete.** A LangGraph agent answers
natural-language diagnostics questions with validated, cited structured output — or refuses,
grounded, when the connected source can't answer. Every consequential output can pass through
a human-review interrupt whose structured corrections become permanent regression cases, and
an LLM-judge scores traces against the same taxonomy the human uses. The design lives in
[`docs/`](docs/); the build ships one phase at a time.

## Evaluation — the headline number

> The LLM-judge agrees with human review on **85%** of traces (n=20). Inter-rater reliability
> could not be measured with a panel — this is a solo project — so the same subset was scored
> twice, one week apart, reaching **90%** self-agreement. **The judge should therefore be read
> as approaching, not exceeding, the reliability ceiling of its ground truth.** Agreement is
> perfect on the mechanically checkable failures — `hallucinated_value` and
> `absence_as_negation`, which a judge can verify against the trace — and *every* disagreement
> was an `overconfident` call (85%), a judgment a rubric only partially disciplines.

That paragraph is the point of Phase 4: a number, measured honestly, with its ceiling and its
weak spot stated rather than hidden. That figure is the *illustration* — hand-seeded labels (a
solo project has no panel), reproducible with no API key: `uv run python scripts/calibrate.py`.
The machinery is real; the number is a rehearsal for the one below.

### First real pass — the machinery on collected labels (n=8)

The first calibration on **real** labels — one human review pass over 8 captured traces —
reads differently, and the gap *is* the finding:

> **50% judge–human agreement (n=8).** Agreement is 100% on every failure mode *except*
> `false_refusal` (50%), which alone drags the headline down: the judge waved through four
> refusals that a human marked as answerable questions wrongly declined. No self-agreement
> ceiling yet — that needs a second review pass a week apart. Reproduce from recorded labels
> with `uv run python scripts/calibrate.py --real`; the report is
> [`calibration_report_realpass_a.json`](data/evals/calibration_report_realpass_a.json).

This is a deliberately **pre-fix** snapshot: the same over-refusal shows up independently in the
regression suite (`scripts/eval.py` → 3/6, all three failures answerable questions refused). The
next moves are an agent fix — each false refusal minted as a `from_review` regression case and
tracked run-over-run ([`evals/tracking.py`](src/canopy/evals/tracking.py)) — then review pass B
for the ceiling. Publishing the low number *before* the fix is the honest version of the story.

**Why a structured taxonomy, not thumbs-up/down?** A thumbs-down says the answer was bad. A
structured [`ErrorType`](src/canopy/evals/schemas.py) says *which of my defenses failed* —
whether a tool description needs a sentence, a refusal path didn't trigger, or a validator has
a gap. The taxonomy is derived from the architecture's known weak points, so every label points
at a fix.

## Architecture

The central bet: **the GenAI layers are independent of the data source.** A normalizer sits
between the data and the intelligence, so swapping OBD for raw CAN later does not require
rewriting the tools, the agent, or the evals.

```
┌──────────────────────────────────────────────────┐
│ L6  Evals & human-in-the-loop                    │  GenAI   ✅ Phase 4
│ L5  Structured outputs & validation              │  GenAI   ✅ Phase 3
│ L4  Agent orchestration  (LangGraph)             │  GenAI  ✅←core Phase 3
│ L3  MCP server                                   │  GenAI   ✅ Phase 2
│ L2  Tool design & schemas                        │  GenAI   ✅ Phase 1
╞══════════════════════════════════════════════════╡  ← THE SEAM
│ L1b Domain logic (diagnostic rules)              │  expertise  ✅ Phase 0
│ L1a Normalizer  (SignalSample / SignalSeries)    │  contract   ✅ Phase 0
│ L0  Data access:  synthetic | OBD | CAN+DBC      │  plumbing   ✅ synthetic
└──────────────────────────────────────────────────┘
```

Everything **above the seam** must be ignorant of whether a number came from an OBD PID or a
decoded CAN frame. A [seam-enforcement test](tests/test_seam.py) fails CI if that leaks.

## What's built (Phases 0–4)

- **The normalizer contract** ([`model/signals.py`](src/canopy/model/signals.py)) —
  `SignalSample`, `SignalSeries`, `SignalSource`. A time-ranged read is the general case;
  an OBD "value now" read is just a series of length one (`is_point_read`). Units always
  travel with values.
- **Structured findings** ([`model/findings.py`](src/canopy/model/findings.py)) — `Finding`
  with **mandatory** `evidence`: a rule that asserts without citing samples is one the agent
  would launder into a hallucination.
- **The data-access protocol** ([`readers/base.py`](src/canopy/readers/base.py)) —
  `SignalReader` with a first-class `available_signals()`, the mechanism by which the agent
  will later *know what it cannot answer*.
- **A deterministic synthetic reader** ([`readers/synthetic.py`](src/canopy/readers/synthetic.py))
  — seeded waveforms for a canonical OBD signal set, with injectable known anomalies. The
  fixture Layers 2–6 are developed and eval'd against; no hardware required.
- **The first diagnostic rule**
  ([`domain/rules/correlation.py`](src/canopy/domain/rules/correlation.py)) — coolant
  rising while engine load is only moderate. Assumes a timeseries; degrades to a
  low-confidence finding on a point read.
- **Four schema'd tools** ([`tools/`](src/canopy/tools)) — `list_available_signals`,
  `summarize_session`, `get_signal`, `run_diagnostic_rules`. Each is a Pydantic input
  schema + a description written as a prompt fragment + a handler that returns structured
  errors (with `available_signals` and a hint) instead of raising into the agent loop.
- **The MCP server** ([`mcp/server.py`](src/canopy/mcp/server.py)) — a thin stdio adapter
  over the tool layer. Schemas go over the wire as `model_json_schema()` verbatim; tool
  errors return `isError` payloads the model can recover from, while protocol errors stay
  JSON-RPC errors the model never sees. Reader selection is env-driven
  (`CANOPY_SOURCE`, resolved below the seam by
  [`readers/factory.py`](src/canopy/readers/factory.py)) — the server never learns which
  source it is serving.
- **The LangGraph agent** ([`agent/graph.py`](src/canopy/agent/graph.py)) — `agent → tools →
  validate → refuse` as a state graph. Structured output arrives through a `submit_answer`
  tool schema; validation failure is a *turn* (the Pydantic error is fed back with the failing
  field and a legal escape), capped at two retries, then degrading to a code-built honest
  answer rather than crashing. The iteration cap converts to a forced-answer degraded turn.
- **The grounded refusal path** ([`agent/contracts.py`](src/canopy/agent/contracts.py)) — the
  headline behavior: a question the source cannot answer produces a `Refusal` naming the
  missing signal and what *is* available, filled by code from a tool result, never from model
  self-knowledge. A cross-validator rejects any answer citing a signal the trace never
  retrieved — confabulation caught mechanically.
- **The eval harness & HITL** ([`evals/`](src/canopy/evals)) — a reviewable [`Trace`](src/canopy/evals/trace.py)
  (full tool-call record, skipped rules, outcome); a [review gate](src/canopy/evals/review.py)
  built as a LangGraph **interrupt** whose `correct` verdicts mint `from_review` regression
  cases; a [structured feedback taxonomy](src/canopy/evals/schemas.py) derived from the
  architecture's weak points; a [regression runner](src/canopy/evals/runner.py) with
  deterministic fixtures and hard assertions that run in CI; and a
  [calibrated LLM-judge](src/canopy/evals/judge.py) scoring the trace, not just the answer.

## Trade-offs (honest)

- **Synthetic-first, not hardware-first.** If the architecture required a dongle to test, it
  would be wrong. Synthetic data is deterministic, so it doubles as the eval fixture. The
  cost: synthetic waveforms are plausible, not real — real captures arrive in Phase 5.
- **A normalizer up front costs an afternoon.** The payoff is that adding raw CAN later
  touches nothing above the seam. If it turns out to leak, that's recorded honestly in the
  [build log](docs/10-build-log.md) — a diagnosed leak is a better story than a lucky clean run.
- **OBD's coverage ceiling is a feature.** OBD cannot see ADAS/camera signals. The right
  behavior when asked is a grounded refusal, not a guess — that refusal path is a core
  deliverable, not an edge case.

## IP hygiene

No proprietary CAN databases, captures, or signal definitions — ever. Only public OBD-II
PIDs, open DBCs, and synthetic/self-captured logs. See [`data/README.md`](data/README.md)
for the provenance ledger.

## Develop

```bash
uv sync --extra dev      # create env + install deps
uv run pytest            # run the suite, including the seam test
uv run ruff check .      # lint
```

Phase 0 done-signal:

```python
from datetime import datetime, timedelta
from canopy.readers.synthetic import SyntheticReader

series = SyntheticReader(seed=42).read(
    "EngineRPM", datetime(2026, 1, 1), datetime(2026, 1, 1) + timedelta(seconds=10)
)
print(len(series.samples), series.unit, series.sample_rate_hz, series.is_point_read)
```

Phase 2 done-signal — a bare MCP client drives the real server as a subprocess
(discovery, invocation, structured errors, clean shutdown; no LLM anywhere):

```bash
uv run python scripts/smoke_mcp.py
```

To explore the same server interactively, register it with any MCP client — e.g. in
Claude Desktop's `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "canopy": {
      "command": "/absolute/path/to/repo/.venv/bin/python",
      "args": ["-m", "canopy.mcp"],
      "env": { "CANOPY_SOURCE": "synthetic" }
    }
  }
}
```

The same server, zero code changes, backs the Phase 3 LangGraph agent — that is the
decoupling MCP buys.

Phase 3 done-signal — ask the agent a question (needs a provider key in `.env`; copy
[`.env.example`](.env.example)). A grounded refusal on an unanswerable question is a *success*:

```bash
uv run python scripts/ask.py "Is the engine overheating?"
uv run python scripts/ask.py "Did the rear camera activate within 2 seconds?"   # → refusal
```

### Web UI — chat with the agent

A two-pane workspace: a **chatbot on the left**, and on the **right** the full tool-call
trace, the cited answer (or grounded refusal), and an **evidence chart annotated with the
exact samples the agent cited**. Each question runs the *real* agent; the answer shape is
identical to the recorded traces, so the same chart pipeline draws both.

```bash
uv run python scripts/serve.py            # → http://127.0.0.1:8000
```

- **Live** runs need a provider key in `.env` (copy [`.env.example`](.env.example)); the
  default provider is Gemini's free tier. Override with `--provider anthropic` or the
  `CANOPY_PROVIDER` / `CANOPY_MODEL` env vars.
- **No key? It still works.** `POST /api/ask` degrades to replaying the closest recorded
  trace, so the whole UI is usable offline — the badge just reads *replay* instead of *live*.
- The **Simulated scenario** selector (Normal / Overheat) chooses the ground-truth condition
  a live run reads, so you can reproduce the overheat chart on demand. It maps to
  `build_reader(scenario=…)` below the seam — the UI never names a data source.

The page is served straight from [`site/`](site/); its `data.js` is regenerated from the
recorded traces with `uv run python site/build_data.py`.

Phase 4 done-signal — the eval harness. Hard assertions run hermetically in the test suite
(no key); the live replay and the judge run against a real model; the calibration number is
reproducible from recorded labels with no key:

```bash
uv run pytest tests/test_eval_runner.py     # regression suite, scripted model, no key
uv run python scripts/calibrate.py          # the 85% / 90% agreement report
uv run python scripts/eval.py --judge       # live replay + LLM-judge (needs a key)
```
