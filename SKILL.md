# Canopy — Skill

> Stub. This artifact is declared in Phase 0 and filled in as the agent layers land
> (Phases 2–4). Some job postings ask for a `SKILL.md` by name; this is that file.

## What this skill will do (target)

Given a natural-language question about a vehicle data session, Canopy:

1. Discovers what signals the connected data source exposes (`list_available_signals`).
2. Retrieves the relevant signals over a time range (`get_signal`), respecting point-read
   vs. timeseries semantics.
3. Runs domain diagnostic rules (`run_diagnostic_rules`) that cite evidence.
4. Summarizes session structure and coverage gaps (`summarize_session`).
5. Returns a **validated, structured answer with a visible tool-call trace** — and
   **gracefully refuses** questions its tools cannot answer, rather than hallucinating.

## Current capability (Phase 0)

Below the seam only: a normalizer contract, a deterministic synthetic data source, and one
diagnostic rule. No tools, MCP server, or agent exist yet. See [README](README.md) for the
phase map and [`docs/`](docs/) for the full design.
