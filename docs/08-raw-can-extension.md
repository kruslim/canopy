# 08 — Raw CAN Extension

**Phase:** 5
**Status when done:** the agent answers a question OBD literally cannot answer, with **zero changes to Layers 3–6.**

This phase is the proof. Everything before it was an assertion that the architecture would hold. This is where it either does or doesn't.

---

## What you are actually testing

Not "can I decode a CAN frame." You can — that's your day job.

You are testing whether **Doc 02's central bet was correct**: that the GenAI layers are independent of the data source, that the normalizer is a real seam and not a fiction you wrote in a design doc.

The success criterion is stated as a diff, not as a feature:

```
 src/canopy/readers/can_log.py     | +180
 src/canopy/readers/base.py        |   +2   (register the reader)
 data/dbc/README.md                |  +15   (provenance)
 tests/test_can_reader.py          | +120
 ─────────────────────────────────────────
 src/canopy/tools/                 |    0   ← must be zero
 src/canopy/mcp/                   |    0   ← must be zero
 src/canopy/agent/                 |    0   ← must be zero
 src/canopy/evals/                 |    0   ← must be zero
```

**If any file above the seam changes, the abstraction leaked.** Find out where, and say so honestly in the build log. A leaked abstraction that you diagnosed is a better interview story than a clean one you got by luck.

---

## The one thing that must be true first

Doc 02 said: *"Design the normalizer around the more general case: a time-ranged read. An OBD 'now' read is just a time range of one sample."*

If you did that, this phase is an afternoon.

If you modelled the OBD point read as primary — if `read()` returns a single `SignalSample` and you were planning to "add a list version later" — then this phase is a rewrite of every tool signature, every schema, and every eval fixture.

There is no clever recovery. The seam either holds or it doesn't. This is why Doc 02 spent so long on a data class.

---

## Implementing `CanLogReader`

```python
import cantools
import can
from canopy.readers.base import SignalReader, UnknownSignalError
from canopy.model.signals import SignalSample, SignalSeries, SignalSource


class CanLogReader(SignalReader):
    """Decodes a logged CAN capture using a DBC. Offline, deterministic, replayable."""

    def __init__(self, dbc_path: str, capture_path: str):
        self._db = cantools.database.load_file(dbc_path)
        self._capture_path = capture_path
        self._index: dict[str, list[SignalSample]] | None = None

    def available_signals(self) -> list[str]:
        return sorted(
            sig.name
            for msg in self._db.messages
            for sig in msg.signals
        )

    def read(self, name: str, start: datetime, end: datetime) -> SignalSeries:
        if name not in self.available_signals():
            raise UnknownSignalError(name, source=SignalSource.CAN)
        self._ensure_indexed()
        samples = [s for s in self._index[name] if start <= s.timestamp <= end]
        return SignalSeries(
            name=name,
            unit=self._unit_for(name),
            source=SignalSource.CAN,
            samples=samples,
        )
```

### Design notes that matter

**Index once, read many.** Decoding a capture per query is wasteful and makes the eval runner slow. Build `{signal_name: [samples]}` on first read. A capture is immutable; the index is a pure function of it.

**`available_signals()` comes from the DBC, not from the capture.** A DBC-defined signal whose message never appeared in this particular capture is *defined but absent*. Two options, and the choice is a real design decision:

- Report it as available; `read()` returns an empty series. Honest about capability, requires the agent to handle empty results.
- Report only signals actually present. Honest about this capture, but `available_signals()` now depends on capture contents.

Take the second. The tool's purpose (Doc 03) is to let the agent know **what it can actually get**, and an empty series is a worse experience than a clear absence. Note the trade-off in the build log; someone will ask.

**`unit` comes from the DBC.** Doc 02 insisted `unit` travels with every value because "when a tool result is serialized into the LLM's context, the unit must be right there in the payload, or the model will guess." The DBC has the unit. Use it. Never default to an empty string.

---

## Decode correctness: the failure that looks like success

Doc 01 warned: *"getting endianness wrong yields plausible-looking garbage."*

This is the single most dangerous bug in the project, because it produces numbers. Not exceptions — numbers. An agent handed a wrongly-decoded `EngineRPM` of 14,203 will reason about it earnestly, cite it, and pass Doc 06's validators, because the value *was* retrieved and the citation *is* real.

**Structured output cannot save you from bad data.** Nothing above the seam can. This is precisely why Doc 02 put a range check in the domain layer:

> **Range check.** Is any sample outside the DBC-declared min/max? Cheap, catches decode errors (wrong endianness produces plausible-looking garbage that violates range).

Implement it, and make it a hard gate on reader construction rather than a runtime finding. If more than a small fraction of samples for a signal fall outside its declared range, refuse to index and raise. The reader is broken; don't let it feed the agent.

```python
def _validate_decode(self, name: str, samples: list[SignalSample]) -> None:
    sig = self._signal_def(name)
    if sig.minimum is None or sig.maximum is None:
        return
    out = sum(1 for s in samples if not (sig.minimum <= s.value <= sig.maximum))
    if out / max(len(samples), 1) > 0.02:
        raise DecodeError(
            f"{name}: {out}/{len(samples)} samples outside DBC range "
            f"[{sig.minimum}, {sig.maximum}]. Check byte order."
        )
```

Fail loudly at the bottom of the stack. Everything above assumes the data is real.

---

## Provenance: the non-negotiable

Doc 00's boundary, restated because this is the phase where it becomes tempting to cross:

- **Never** commit real Ford CAN databases, capture files, internal signal definitions, or test data.
- Use **open DBC files** (the OpenDBC project publishes reverse-engineered DBCs for many vehicles) and **synthetic or self-captured logs** from your own vehicle.
- Domain *expertise* is yours and portable. Domain *artifacts* belong to your employer.

Write `data/dbc/README.md` and `data/captures/README.md` stating the origin of every file — the DBC's upstream repository and commit, the capture's vehicle and date and the fact that you recorded it yourself. When a reviewer asks *"is any of this proprietary?"*, you point at it.

The answer must be an immediate, confident no. A hesitation here costs you the interview regardless of how good the code is.

---

## What OBD could never do, and now works

This is the demo. Pick the question Doc 01 declared structurally unanswerable, and Doc 05 made the agent refuse:

> *"Did the rear camera activate within 2 seconds in run 47?"*

**Before (OBD source):** the agent calls `list_available_signals`, sees only emissions parameters, and returns a `Refusal` naming the missing signal and stating that a CAN log with an appropriate DBC would be needed.

**After (CAN log source):** the same agent, unchanged, calls the same tool, sees the body-control signals in the DBC, retrieves a true timeseries at a real sample rate, runs the timing rule, and answers with citations.

**Nothing above the seam knew the difference.**

Put both traces in the README, side by side. That comparison is the most persuasive artifact you will produce, because it demonstrates three things a reviewer cares about simultaneously: the agent refuses honestly when it can't answer; the architecture genuinely decouples; and you understand vehicle networks well enough to know which questions live on which bus.

---

## The refusal that must survive

A subtle regression risk: with a rich DBC loaded, the agent can now answer far more. Does the refusal path still fire when it should?

Add eval cases (Doc 07) with a CAN source and a signal that *isn't* in the DBC:

| Case | Source | Asserts |
|---|---|---|
| Camera timing, OBD | `obd` | refusal, `signal_unavailable` |
| Camera timing, CAN | `can_log` | answer, cites body-control signal |
| Signal absent from DBC, CAN | `can_log` | refusal, `signal_unavailable` |
| Signal in DBC, absent from capture | `can_log` | refusal, `time_range_not_covered` |
| Signal on a channel the DBC references but this capture never connected (e.g. `HS2` absent) | `can_log` | refusal, `channel_not_captured` |
| Name defined on two channels, request unqualified | `can_log` | refusal, `signal_unavailable`, names both channels |

That third row is why `available_signals()` reports capture contents rather than DBC contents. That fourth row is a new `refusal_reason` — Doc 05 defined `time_range_not_covered` and you finally have a reader that can produce it.

**Run the full Phase 4 regression suite against both sources.** A pass rate that holds across data sources is the strongest possible evidence that the seam is real.

---

## Sample rate reaches the agent

Doc 03's `get_signal` description said:

> *"Do not perform timing analysis on a point read — check `actual_sample_rate_hz` before reasoning about how a signal changed over time."*

Until now, `actual_sample_rate_hz` has always been `null` (OBD) or synthetic. Now it carries a real number, and it varies per signal — a body-control signal might broadcast at 10 Hz while a powertrain signal runs at 100 Hz.

Two consequences:

**The timing rule must check it.** A 2000 ms activation window measured against a 10 Hz signal has ±100 ms of quantization uncertainty. The rule should return `confidence: "medium"` and say so. Doc 02 required every `Finding` to carry `confidence`; this is where that field earns its existence.

**The agent must surface it.** If the answer asserts "activated at 1.84 s," and the signal sampled at 10 Hz, the honest claim is "activated between 1.8 and 1.9 s." Add an eval case asserting the agent doesn't over-report precision. This is the `OVERCONFIDENT` error type from Doc 07 in its most concrete form.

---

## Definition of done — Phase 5

- [ ] `CanLogReader` implements `SignalReader`; indexes once, reads many
- [ ] `available_signals()` reports **capture contents**, trade-off noted in build log
- [ ] `unit` sourced from the DBC, never defaulted
- [ ] Decode validation gate: >2% of samples outside DBC range raises `DecodeError`
- [ ] `data/dbc/README.md` and `data/captures/README.md` state provenance of every file
- [ ] Zero proprietary artifacts in the repo **or in git history**
- [ ] `actual_sample_rate_hz` carries real per-signal values
- [ ] Timing rule degrades `confidence` based on sample rate quantization
- [ ] Four refusal eval cases pass across both sources
- [ ] Full Phase 4 regression suite passes against `obd` **and** `can_log`
- [ ] Side-by-side before/after traces in the README
- [ ] **Diff shows zero lines changed in `tools/`, `mcp/`, `agent/`, `evals/`**
- [ ] Seam test still passes

---

## Questions to be ready for

> *"You started with OBD and added CAN. What did you have to change?"*

The reader, and nothing above it. That was the whole bet — I modelled the read operation as time-ranged from day one, because CAN is a broadcast stream and OBD is request-response, and if the tool layer knows which one it's talking to then adding CAN means rewriting every tool, schema, and eval. The OBD point read is just a series of length one. The diff touches `readers/` and the test suite; `tools/`, `mcp/`, `agent/`, and `evals/` are untouched, and there's a grep test in CI that fails if they ever import `cantools`.

> *"What's the most dangerous bug in CAN decoding?"*

Endianness. It doesn't throw — it produces plausible numbers. An agent handed a wrongly-decoded RPM of 14,000 will reason about it earnestly, cite it correctly, and pass every structured-output validator I have, because the value really was retrieved and the citation really is real. Nothing above the seam can catch bad data. So I gate at the reader: if more than 2% of a signal's samples fall outside its DBC-declared range, I refuse to index and raise. Fail loudly at the bottom.

> *"How do you know your refusal path didn't break once you had more data?"*

I added eval cases for signals absent from the DBC and for signals present in the DBC but absent from this capture — that second one exercises a distinct refusal reason, `time_range_not_covered`. Then I ran the entire Phase 4 regression suite against both sources. A pass rate that holds across data sources is the evidence that the abstraction is real rather than aspirational.

> *"Is any of this from your employer?"*

No. Open DBCs from the OpenDBC project, synthetic captures from a seeded generator, and logs I recorded from my own vehicle. Provenance for every file is documented in `data/`. My domain expertise is portable; my employer's artifacts are not, and I keep that line bright.
