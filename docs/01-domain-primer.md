# 01 — Domain Primer: OBD, CAN, and DBC

**Audience:** you, in six months, having forgotten the details. Also any reviewer who is strong on GenAI and weak on vehicles.

**Purpose:** establish what the data actually *is*, so that every later design decision has a physical justification.

---

## The physical layer: CAN bus

CAN (Controller Area Network) is a **broadcast** bus. Electronic control units (ECUs) — engine, transmission, ABS, body control, camera modules — all sit on a shared twisted pair and shout messages onto it. Nobody addresses anybody. Everyone hears everything and ignores what they don't care about.

A CAN frame carries, in essence:

- an **arbitration ID** (11-bit standard, or 29-bit extended) — identifies *what kind of message this is*, not who sent it
- a **payload** of up to 8 bytes (classic CAN)
- framing/CRC that you almost never touch from Python

The arbitration ID also determines priority: lower ID wins the bus. This is why safety-critical messages get low IDs.

**Key consequence for tool design:** CAN is a *stream*. There is no "ask." Messages arrive continuously whether anyone listens or not. The natural read operation is "give me signal X over time range [t0, t1]," not "give me X now."

---

## The interpretation layer: DBC

A raw frame is meaningless bytes. `ID 0x1A0, payload 0x2F 0x64 0x00 0x00 ...` tells you nothing.

A **DBC file** is the decode dictionary. It maps, for each arbitration ID, the signals packed inside the payload:

- signal name (`EngineRPM`)
- bit start offset and bit length
- byte order (big/little endian — "Motorola" vs "Intel")
- scale factor and offset (`physical = raw * scale + offset`)
- unit (`rpm`)
- min/max

So decoding is: pull the bits at the right offset, apply scale and offset, attach the unit.

**Signals are packed.** One 8-byte payload might contain six different signals at odd bit boundaries. This is why you use a library (`cantools`) rather than doing it by hand.

**DBC files are usually proprietary.** The OEM's DBC is the crown jewels — it's the map to every signal on the vehicle. This is precisely why Phase 5 of this project uses **open DBC files** (the OpenDBC project publishes reverse-engineered DBCs for many vehicles) and never anything from your employer.

---

## The diagnostic layer: OBD-II

OBD-II is a **request-response protocol layered on top of CAN** (via ISO 15765 / UDS transport, on most vehicles since roughly 2008).

Instead of listening to broadcast traffic, you send a request: "Mode 01, PID 0x0C." The ECU replies with the bytes for engine RPM. You decode with a **publicly documented formula**.

```
PID 0x0C  Engine RPM        →  ((A * 256) + B) / 4        unit: rpm
PID 0x0D  Vehicle speed     →  A                           unit: km/h
PID 0x05  Coolant temp      →  A - 40                      unit: °C
PID 0x04  Engine load       →  (A * 100) / 255             unit: %
PID 0x11  Throttle position →  (A * 100) / 255             unit: %
```

(`A`, `B` are the returned data bytes. These formulas are standardized and identical across compliant vehicles.)

---

## The comparison table that drives every design decision

| | **OBD-II PIDs** | **Raw CAN + DBC** |
|---|---|---|
| **Access model** | Request → response | Broadcast stream |
| **Natural read op** | "Value now" | "Signal over [t0, t1]" |
| **Decode source** | Public standard formulas | Proprietary DBC (use open ones) |
| **Coverage** | ~dozens of emissions-related params | *Everything* on the bus |
| **ADAS / camera signals?** | **No. Never.** | Yes |
| **Sample rate** | Slow (~tens of Hz, degrades per added PID) | High (hundreds of Hz per signal) |
| **Python tooling** | `python-OBD` (turnkey) | `python-can` + `cantools` |
| **Hardware** | $20 ELM327 dongle | Proper CAN interface |
| **Portfolio signal** | "I plugged in a hobbyist dongle" | "I understand vehicle networks" |

---

## Why this table matters more than it looks

Three lines in it dictate the entire project architecture.

**1. "ADAS / camera signals? — No. Never."**

OBD will *never* expose rear-camera activation timing. The question "did the rear camera activate within 2 seconds?" is **structurally unanswerable** with OBD, no matter how good your agent is.

This is not a limitation to hide. It is the **most valuable teaching artifact in the project.** A well-built agent, asked that question with only OBD tools available, must say *"I don't have a tool that can answer this"* — not invent a plausible number.

Building that graceful refusal is a stronger portfolio detail than any successful query, because it demonstrates the trustworthiness and reliability thinking that separates production engineers from demo builders. Most portfolios only show the happy path.

**2. "Request → response" vs "Broadcast stream"**

These want different tool shapes. OBD says `get_current_value(pid)`. CAN says `get_signal(name, t0, t1)`.

The **normalizer's** entire job is to hide this difference. Both must produce the same shape, or Layers 3–6 will leak data-source knowledge and Phase 5 becomes a rewrite.

Design the normalizer around the *more general* case: a time-ranged read. An OBD "now" read is just a time range of one sample.

**3. "Sample rate: slow vs high"**

Timing-compliance logic (is activation within 2000 ms?) fundamentally needs the high-rate case. So the *rules* you write in the domain layer should assume a timeseries and degrade gracefully when handed a single sample. Don't write rules that assume one value.

---

## The strategic framing

Your competitive moat is that you are an automotive engineer who works with real vehicle networks. OBD-II is generic — anyone with a dongle and a Civic can pull RPM.

So use OBD for accessible data, but keep the **framing** and the **reasoning layer** in your professional domain:

- Frame the agent around **diagnostics and telemetry interpretation**, which is legitimately what OBD is for. "Coolant temp is climbing while load is only moderate — here's what that pattern suggests" is a real, defensible tool.
- Put your expertise in the **rules layer**, not the data layer. What the agent checks, how it interprets, what compliance logic it applies — that's where domain knowledge shows, and it does not require the data to be proprietary.
- Add raw-CAN decoding in Phase 5 with **open DBCs and synthetic logs**, to demonstrate you understand the real thing.

---

## Vocabulary you must be able to define cold

Interviewers will probe these. One sentence each, no hedging.

- **Arbitration ID** — identifies the message type and sets bus priority; lower wins.
- **PID** — Parameter ID; a standardized request code for one diagnostic value.
- **DBC** — the file that maps arbitration IDs and bit offsets to named, scaled signals.
- **Scale/offset** — `physical = raw * scale + offset`; how raw bits become engineering units.
- **Endianness (Motorola/Intel)** — the bit-packing order within the payload; getting it wrong yields plausible-looking garbage.
- **Broadcast vs request-response** — CAN shouts; OBD asks.
- **UDS / ISO 15765** — the transport that carries OBD requests over CAN.

---

## Reading list

- OBD-II PID tables — publicly documented, widely mirrored
- `python-OBD` documentation, including its simulation/async modes
- `cantools` documentation for DBC parsing
- The OpenDBC project, for open DBC files and sample captures

---

## What to build in Phase 0, having read this

A synthetic data source that emits a timeseries of normalized signals, with **no real vehicle attached.** You should be able to develop Layers 2–6 entirely against fake data. Hardware is a Phase 5 convenience, not a Phase 0 dependency.

If your architecture requires a dongle to test, the architecture is wrong.
