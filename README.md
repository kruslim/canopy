# Canopy

> An MCP server that exposes vehicle-diagnostic and CAN-bus domain logic as agent tools,
> with a LangGraph orchestration layer and a human-in-the-loop eval harness.

**Status: Phase 0 (Foundation) complete — normalizer contract + synthetic reader + first
diagnostic rule. No LLM code in the repo yet.** The design lives in [`docs/`](docs/); the
build ships one phase at a time.

## Architecture

The central bet: **the GenAI layers are independent of the data source.** A normalizer sits
between the data and the intelligence, so swapping OBD for raw CAN later does not require
rewriting the tools, the agent, or the evals.

```
┌──────────────────────────────────────────────────┐
│ L6  Evals & human-in-the-loop                    │  GenAI      (Phase 4)
│ L5  Structured outputs & validation              │  GenAI      (Phase 3)
│ L4  Agent orchestration  (LangGraph)             │  GenAI  ←core(Phase 3)
│ L3  MCP server                                   │  GenAI      (Phase 2)
│ L2  Tool design & schemas                        │  GenAI      (Phase 1)
╞══════════════════════════════════════════════════╡  ← THE SEAM
│ L1b Domain logic (diagnostic rules)              │  expertise  ✅ Phase 0
│ L1a Normalizer  (SignalSample / SignalSeries)    │  contract   ✅ Phase 0
│ L0  Data access:  synthetic | OBD | CAN+DBC      │  plumbing   ✅ synthetic
└──────────────────────────────────────────────────┘
```

Everything **above the seam** must be ignorant of whether a number came from an OBD PID or a
decoded CAN frame. A [seam-enforcement test](tests/test_seam.py) fails CI if that leaks.

## What's built (Phase 0)

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
