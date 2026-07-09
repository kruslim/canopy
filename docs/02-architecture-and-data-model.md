# 02 — Architecture & Data Model

**Phase:** 0
**Status when done:** you can call `get_signal("EngineRPM", t0, t1)` in plain Python and receive a normalized result from synthetic data. No LLM involved yet.

---

## The layer stack, and why the boundaries sit where they do

```
┌──────────────────────────────────────────────────┐
│ L6  Evals & human-in-the-loop                    │  GenAI
├──────────────────────────────────────────────────┤
│ L5  Structured outputs & validation              │  GenAI
├──────────────────────────────────────────────────┤
│ L4  Agent orchestration  (LangGraph)             │  GenAI ← core skill
├──────────────────────────────────────────────────┤
│ L3  MCP server                                   │  GenAI
├──────────────────────────────────────────────────┤
│ L2  Tool design & schemas                        │  GenAI ← learning starts
╞══════════════════════════════════════════════════╡  ← THE SEAM
│ L1b Domain logic (rules, compliance checks)      │  your expertise
├──────────────────────────────────────────────────┤
│ L1a Normalizer                                   │  the contract
├──────────────────────────────────────────────────┤
│ L0  Data access:  OBD  |  CAN+DBC                │  interchangeable plumbing
└──────────────────────────────────────────────────┘
```

**The seam is between L1b and L2.** Everything above the seam must be ignorant of whether a number came from an OBD PID or a decoded CAN frame. Everything below the seam is automotive engineering you already know.

If any code above the seam contains the string `"obd"` or `"dbc"`, the abstraction has leaked and Phase 5 will be a rewrite.

---

## The normalizer contract

This is the single most important artifact in the project. Get it right on day one.

### Core type: `SignalSample`

```python
from datetime import datetime
from enum import Enum
from typing import Literal
from pydantic import BaseModel, Field


class SignalSource(str, Enum):
    OBD = "obd"
    CAN = "can"
    SYNTHETIC = "synthetic"


class SignalSample(BaseModel):
    """One observation of one signal at one instant."""

    name: str = Field(..., description="Canonical signal name, e.g. 'EngineRPM'")
    value: float
    unit: str = Field(..., description="Engineering unit, e.g. 'rpm', 'km/h', 'degC'")
    timestamp: datetime
    source: SignalSource
    quality: Literal["good", "estimated", "stale"] = "good"
```

### Core type: `SignalSeries`

```python
class SignalSeries(BaseModel):
    """A time-ranged read of one signal. The universal return shape."""

    name: str
    unit: str
    source: SignalSource
    samples: list[SignalSample]

    @property
    def sample_rate_hz(self) -> float | None:
        """None when fewer than two samples — an OBD point read."""
        ...

    @property
    def is_point_read(self) -> bool:
        return len(self.samples) <= 1
```

### The three design decisions embedded here, and their justifications

**1. Time-ranged is the general case; "now" is a special case.**

CAN is a broadcast stream — the natural read is a range. OBD is request-response — the natural read is a point. If you model the point as primary, adding CAN later breaks every signature.

So: **`SignalSeries` is always the return type.** An OBD read returns a series of length one. `is_point_read` tells the domain layer to degrade gracefully.

This is the single decision that makes Phase 5 an afternoon rather than a rewrite.

**2. `unit` travels with the value, always.**

Vehicle data is a minefield of km/h vs mph, °C vs °F, rpm vs rad/s. A bare float is an outage waiting to happen. More importantly for this project: when a tool result is serialized into the LLM's context, the unit must be *right there in the payload*, or the model will guess. Models guess confidently.

**3. `quality` exists because reality is messy.**

OBD polling degrades as you add PIDs — values go stale. CAN captures have dropouts. A `stale` marker lets the domain layer and, ultimately, the agent reason about confidence rather than treating every number as gospel.

---

## The data-access interface

Everything below the seam implements one protocol:

```python
from typing import Protocol
from datetime import datetime


class SignalReader(Protocol):
    """Implemented by ObdReader, CanLogReader, SyntheticReader."""

    def available_signals(self) -> list[str]:
        """Canonical names this reader can produce. The agent needs this
        to know what it cannot answer."""
        ...

    def read(
        self,
        name: str,
        start: datetime,
        end: datetime,
    ) -> SignalSeries:
        """Raises UnknownSignalError if name not in available_signals()."""
        ...
```

Three implementations, built in this order:

| Reader | Phase | Backing |
|---|---|---|
| `SyntheticReader` | 0 | Generated waveforms. No hardware. |
| `ObdReader` | 1 | `python-OBD`, dongle *or* its simulation mode |
| `CanLogReader` | 5 | `cantools` + open DBC + logged capture |

**`SyntheticReader` is not a toy.** It is the reader you develop Layers 2–6 against. If your architecture requires a dongle to test, the architecture is wrong. It also becomes your eval fixture in Phase 4, because it is deterministic — you can generate a capture with a known anomaly at a known timestamp and assert the agent finds it.

---

## `available_signals()` is a first-class citizen, not an afterthought

This method exists for one reason: **the agent must be able to know what it cannot answer.**

OBD will never expose rear-camera activation timing. When a user asks that question and the only reader is `ObdReader`, the correct behavior is a graceful refusal — not a hallucinated number.

The mechanism is: expose signal availability *through the tool layer*, so the model can check before it commits. Doc 03 covers how the tool description enforces this. Doc 05 covers the agent's refusal path.

Most portfolios only demonstrate the happy path. This is the detail that reads as production thinking.

---

## The domain-logic layer (L1b)

This is where your expertise lives and where the project stops being generic.

Rules consume `SignalSeries` and emit structured findings. They must **assume a timeseries and degrade when handed a point read.**

```python
class Finding(BaseModel):
    rule_id: str
    severity: Literal["info", "warning", "violation"]
    message: str
    evidence: list[SignalSample]          # always cite the data
    confidence: Literal["high", "medium", "low"]
```

Example rule shapes (not exhaustive — this is where you add value):

- **Timing check.** Did signal X transition within N ms of trigger Y? *Requires* a series. Returns `confidence: "low"` + a warning if handed a point read, rather than silently passing.
- **Correlation check.** Is coolant temp rising while engine load is only moderate? A genuine diagnostic pattern, answerable with OBD.
- **Range check.** Is any sample outside the DBC-declared min/max? Cheap, catches decode errors (wrong endianness produces plausible-looking garbage that violates range).
- **Dropout check.** Are there gaps in the timeseries exceeding the expected sample interval?

`evidence` is mandatory on every finding. A rule that asserts without citing samples is a rule the agent will happily launder into a hallucination.

---

## Repository layout

```
canopy/
├── README.md                    # architecture diagram + trade-offs, first
├── SKILL.md                     # some postings ask for this artifact by name
├── pyproject.toml
├── src/canopy/
│   ├── model/
│   │   ├── signals.py           # SignalSample, SignalSeries, SignalSource
│   │   └── findings.py          # Finding
│   ├── readers/                 # ── below the seam ──
│   │   ├── base.py              # SignalReader protocol, UnknownSignalError
│   │   ├── synthetic.py         # Phase 0
│   │   ├── obd.py               # Phase 1
│   │   └── can_log.py           # Phase 5
│   ├── domain/                  # ── below the seam ──
│   │   └── rules/
│   │       ├── timing.py
│   │       ├── correlation.py
│   │       └── ranges.py
│   ├── tools/                   # ── above the seam: L2 ──
│   ├── mcp/                     # L3
│   ├── agent/                   # L4, L5
│   └── evals/                   # L6
├── tests/
└── data/
    ├── dbc/                     # OPEN DBCs ONLY
    └── captures/                # synthetic or self-captured ONLY
```

Note the seam is visible in the directory structure. `tools/`, `mcp/`, `agent/`, `evals/` must never import from `readers/` directly — only through `domain/` and the `SignalReader` protocol.

**Enforce it with a test.** A grep-based test asserting that nothing under `tools/`, `mcp/`, `agent/`, or `evals/` contains `obd`, `dbc`, or `cantools` is worth ten paragraphs of README prose. It converts an architectural intention into a thing that fails CI when violated.

---

## IP hygiene, restated as a code constraint

`data/dbc/` and `data/captures/` contain **only** open DBCs and synthetic or self-captured logs.

Add to `.gitignore` before the first commit, not after:

```gitignore
data/captures/proprietary/
*.private.dbc
```

Better: put a `data/README.md` in the repo stating the provenance of every file. When a reviewer asks "is any of this proprietary?", you point at it. The answer must be an immediate, confident no.

Domain *expertise* is yours and portable. Domain *artifacts* belong to your employer. This distinction is what makes the project showable.

---

## Definition of done — Phase 0

- [ ] `SignalSample`, `SignalSeries`, `Finding` defined with Pydantic
- [ ] `SignalReader` protocol defined
- [ ] `SyntheticReader` emits a deterministic, seeded timeseries
- [ ] At least one rule implemented, consuming `SignalSeries`, emitting `Finding` with `evidence`
- [ ] `available_signals()` works and `UnknownSignalError` raises correctly
- [ ] Unit tests pass; the seam-enforcement grep test passes
- [ ] **No LLM code exists in the repo yet**

That last checkbox is deliberate. The temptation is to skip to the agent because that's the interesting part. Resist it. Every hour spent on the normalizer contract is repaid tenfold in Phase 5, and a reviewer who sees clean layer boundaries will trust everything above them.

---

## The question to be ready for

> *"Why did you build a normalizer instead of just calling python-OBD from your tools?"*

The answer, in one breath: because OBD is request-response and CAN is broadcast, they want different tool shapes, and if the tool layer knows which one it's talking to, then adding CAN later means rewriting every tool, every schema, and every eval. The normalizer costs an afternoon and buys the ability to change the data source without touching the intelligence.

If you can say that without notes, Phase 0 succeeded.
