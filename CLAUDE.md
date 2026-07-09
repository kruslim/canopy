# CLAUDE.md — Canopy

An MCP server exposing vehicle-diagnostic / CAN-bus domain logic as agent tools,
with a LangGraph orchestration layer and a human-in-the-loop eval harness.

Authoritative design lives in `docs/`. Read `docs/00`, `docs/02` before touching
architecture. This file states the **hard constraints** — violating one is a bug,
not a style choice.

## Phase discipline
Ship each phase completely before the next (docs/00). We are at **Phase 3**
(agent: LangGraph loop + structured outputs — `langgraph`/`langchain`/`anthropic`
are now legitimately in the tree). Phase 4 (evals & HITL) has not started: no
review-queue, judge, or eval-harness code until then.

## Data sources & rig
The real-world inputs the readers ultimately model (below the seam — this context
never leaks above it):

- **Simulated OBD** — a software OBD-II source, not a live vehicle. Standard public
  PIDs only (see Constraint 2).
- **Vector CANalyzer** for RAW CAN data. The bus has **4 channels**, but the port I
  connect to may only expose a subset (e.g. **HS1 / HS2** only) — code and readers
  MUST NOT assume all 4 channels are present. Treat available channels as discovered,
  not fixed.
- **DBCs to come** — I'll provide DBC files later. Until then, decoding paths work
  against synthetic/open definitions. When DBCs land they go in `data/dbc/` and are
  subject to Constraint 2 (open/synthetic only; nothing proprietary in the tree).

## Constraint 1 — The seam (docs/02)
The seam sits between L1b (domain logic) and L2 (tools). Everything above the seam
— `tools/`, `mcp/`, `agent/`, `evals/` — MUST be ignorant of whether a number came
from an OBD PID or a decoded CAN frame.

- Above-seam code MUST NOT contain the strings `obd`, `dbc`, or `cantools`.
- Above-seam code reaches data ONLY through the `SignalReader` protocol and the
  `domain/` layer — never by importing `readers/` concretions directly.
- `SignalSeries` is the universal return shape. A "value now" read is just a series
  of length one (`is_point_read`). Never add a point-only signature.
- Enforced by `tests/test_seam.py`. If it fails, the abstraction leaked and Phase 5
  becomes a rewrite. Fix the leak, don't weaken the test.

## Constraint 2 — IP hygiene (docs/00, docs/02)
Domain *expertise* is portable and yours. Domain *artifacts* belong to the employer.

- NEVER commit real Ford CAN databases, capture files, internal signal definitions,
  or proprietary test data — not in the tree, not in git history.
- Use only: standard OBD-II PIDs (public), open DBCs (e.g. OpenDBC), and synthetic
  or self-captured logs.
- `data/dbc/` and `data/captures/` hold open/synthetic files ONLY. Record provenance
  in `data/README.md`. `.gitignore` excludes `data/captures/proprietary/` and
  `*.private.dbc` — keep those rules.
- The answer to "is any of this proprietary?" must be an immediate, confident **no**.

## Constraint 3 — Errors as results (docs/02, docs/03)
Below the seam, readers *raise* (`UnknownSignalError` carries the requested name and
what IS available). At the tool layer and above, errors become **structured result
payloads**, never uncaught exceptions that crash the agent loop.

- A tool asked for an unavailable signal returns a structured error with a hint, so
  the agent can refuse gracefully.
- The agent MUST refuse questions its tools cannot answer ("I don't have a tool for
  that") rather than inventing a plausible number. Graceful refusal is a feature, not
  a failure — it is the project's headline teaching artifact.

## Constraint 4 — The citation validator (docs/02, docs/06)
Every `Finding` MUST carry non-empty `evidence: list[SignalSample]`. A claim without
cited samples is a hallucination waiting to launder itself through the agent.

- Rules assert nothing they cannot point at with actual samples.
- `unit` travels with every value, always — a bare float is an outage waiting to
  happen and the model will guess the unit if it isn't in the payload.
- Validation rejects any finding/answer that asserts without citing its evidence.

## Working here
- **Always use the project's Python 3.12 venv at `.venv/`** — there is no `python` on
  PATH and the system `python3` is 3.9, which violates `requires-python >=3.11`. Run
  everything through it: `.venv/bin/python`, `.venv/bin/pytest`, `.venv/bin/ruff`
  (or activate with `source .venv/bin/activate`).
- `pytest` runs the suite (config in `pyproject.toml`). `ruff check` / `ruff format`
  for lint/format.
- Rules consume a timeseries and MUST degrade gracefully on a point read (return low
  confidence + a warning), never assume a single value.
