# 00 — Project Charter & Document Index

**Project codename:** Canopy
**One-line:** An MCP server that exposes vehicle diagnostic and CAN-bus domain logic as agent tools, with a LangGraph orchestration layer and a human-in-the-loop eval harness.

---

## Why this project exists

Two audiences, one artifact.

**For a GenAI hiring manager:** this demonstrates agent orchestration, tool/function calling, MCP server design, structured outputs, context management, human-in-the-loop review, and evaluation — the recurring stack in nearly every GenAI job posting in 2026.

**For a motorsport / automotive hiring manager:** this demonstrates that you can build production tooling over vehicle networks, which is what internal tools teams actually do.

The domain (vehicle diagnostics) is the moat. Thousands of people have built a RAG chatbot over PDFs. Almost nobody has built an agent that decodes a CAN frame and reasons about signal timing, because that requires domain knowledge most applicants don't have.

---

## The central architectural bet

The GenAI layers are **independent of the data source.**

```
Layer 6  Evals & human-in-the-loop     ← GenAI
Layer 5  Structured outputs            ← GenAI
Layer 4  Agent orchestration           ← GenAI  (the core skill)
Layer 3  MCP server                    ← GenAI
Layer 2  Tool design & schemas         ← GenAI  (where learning starts)
─────────────────────────────────────────────────
Layer 1  Data access (OBD | CAN+DBC)   ← plumbing, interchangeable
```

We start with OBD because it is publicly documented, needs no proprietary DBC, and has turnkey Python tooling. We add raw CAN later. **Because a normalizer sits between Layer 1 and Layer 2, swapping the data source does not require rewriting the intelligence.**

Get the normalizer right on day one and Phase 5 becomes an afternoon instead of a rewrite.

---

## Hard boundary: IP hygiene

Non-negotiable, stated up front because it constrains every later decision.

- **Never** commit real Ford CAN databases, capture files, internal signal definitions, or test data.
- Use **standard OBD-II PIDs** (publicly documented), **open DBC files** (e.g. the OpenDBC project), and **synthetic or self-captured logs** from your own vehicle.
- Domain *expertise* is yours and portable. Domain *artifacts* belong to your employer.
- If a reviewer asks "is any of this proprietary?" the answer must be an immediate, confident no.

This is not just legal caution. It is what makes the project something you can actually show people.

---

## Document index

| Doc | Title | Purpose | Build phase |
|-----|-------|---------|-------------|
| 00 | Charter & Index | This file. Scope, bet, boundaries. | — |
| 01 | Domain Primer | OBD vs CAN vs DBC. What the data *is*. | Pre-work |
| 02 | Architecture & Data Model | The normalizer contract. Layer boundaries. | Phase 0 |
| 03 | Tool Design Spec | The four tools, schemas, descriptions. | Phase 1 |
| 04 | MCP Server Spec | Protocol, discovery, transport, errors. | Phase 2 |
| 05 | Agent Orchestration Spec | The LangGraph loop. State. Termination. | Phase 3 |
| 06 | Structured Outputs & Validation | Pydantic contracts, retry, failure modes. | Phase 3 |
| 07 | Eval Harness & HITL | Review gate, feedback schema, LLM-judge. | Phase 4 |
| 08 | Raw CAN Extension | Adding DBC decoding behind the normalizer. | Phase 5 |
| 09 | Interview Defense Guide | What you must be able to explain, and how. | Continuous |
| 10 | Build Log Template | Decisions, trade-offs, things that broke. | Continuous |

---

## Phase plan

Ship each phase **completely** before starting the next. A finished single repo beats two half-built ones, because the market rewards people who ship.

**Phase 0 — Foundation.** Repo, normalizer, synthetic data source. No LLM yet.
*Done when:* you can call `get_signal("EngineRPM", t0, t1)` in Python and get back a normalized result from fake data.

**Phase 1 — Tools.** Wrap domain logic in Pydantic-schema'd tools. Still no LLM.
*Done when:* four tools exist, each with a schema and a deliberately-written description, each unit-tested.

**Phase 2 — MCP server.** Expose the tools over MCP.
*Done when:* an MCP client can discover and invoke your tools.

**Phase 3 — Agent.** LangGraph loop + structured output.
*Done when:* a natural-language question produces a validated answer with a visible tool-call trace, *and* an out-of-scope question produces a graceful refusal rather than a hallucination.

**Phase 4 — Evals & HITL.** Review queue, structured feedback, regression set, calibrated judge.
*Done when:* you can state a human-agreement number for your LLM-judge.

**Phase 5 — Raw CAN.** DBC decoding behind the same normalizer.
*Done when:* the agent answers a question OBD literally cannot answer, with zero changes to Layers 3–6.

---

## The self-test that decides whether this worked

After Phase 3: close the repo, open a blank file, and rebuild the agent loop from scratch without looking.

If you can, you understand it. If you can't, you have found exactly what to study — and you should not put it on your resume yet.

Claude Code compresses the typing, not the understanding. Building fast with it is expected and correct. Shipping a repo you cannot defend gets you into interview rooms you will then lose.

---

## Definition of done for the whole project

- [ ] README leads with an architecture diagram and an honest trade-offs section
- [ ] `SKILL.md` exists (some postings ask for exactly this artifact)
- [ ] The agent gracefully refuses questions its tools cannot answer
- [ ] An eval set exists that grew from real observed failures
- [ ] A human-agreement figure for the LLM-judge is stated in the README
- [ ] Zero proprietary artifacts anywhere in git history
- [ ] You can whiteboard the agent loop from memory
