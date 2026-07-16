"""Generate the showcase site's data file from the *real* recorded artifacts.

The site never invents data: it replays `data/evals/traces/*.json` and reports
`data/evals/calibration_report.json` verbatim. This script compacts the traces
(the raw signal series run to hundreds of samples) into a viewer-friendly shape
while preserving every claim, citation, unit, and refusal exactly as recorded.

For answer traces it also emits a `plot_series` — the same recorded signal,
decimated to ~130 points so the viewer can draw a cited evidence chart — and
tags each citation that lands on that signal with a `t` offset (seconds from the
series start) so the chart can mark the exact samples the answer cited. Both are
derived straight from the recording; nothing is synthesised for display.

Run from the repo root:  .venv/bin/python site/build_data.py
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRACES_DIR = ROOT / "data" / "evals" / "traces"
CALIBRATION = ROOT / "data" / "evals" / "calibration_report.json"
OUT = Path(__file__).resolve().parent / "data.js"

# Curated order: lead with the two headline behaviours, then the rest.
FEATURED = ["cap_001", "cap_005", "cap_004", "cap_000", "cap_006", "cap_007"]

# Points to keep when decimating a series for the chart, and reference lines
# (a value the chart draws a dashed threshold at) keyed by unit.
PLOT_POINTS = 130
UNIT_REFERENCE = {"degC": 105.0}  # coolant overheat threshold


def truncate_arrays(obj, keep: int = 2):
    """Recursively shorten long lists so a 500-sample series doesn't bloat the page."""
    if isinstance(obj, dict):
        return {k: truncate_arrays(v, keep) for k, v in obj.items()}
    if isinstance(obj, list):
        if len(obj) > keep + 1:
            head = [truncate_arrays(x, keep) for x in obj[:keep]]
            head.append(f"… {len(obj) - keep} more of {len(obj)} (elided for display)")
            return head
        return [truncate_arrays(x, keep) for x in obj]
    return obj


def summarize(name: str, result) -> tuple[str, bool]:
    """A one-line human summary of a tool result, and whether it was an error."""
    if isinstance(result, dict) and result.get("error"):
        return f"structured error · {result['error']} — {result.get('hint', '')}", True
    if name == "list_available_signals":
        sigs = [s["name"] for s in result.get("signals", [])]
        return f"source={result.get('source')} · {len(sigs)} signals: {', '.join(sigs)}", False
    if name == "get_signal":
        series = result.get("series", {})
        n = len(series.get("samples", []))
        kind = "point read" if n == 1 else f"{n} samples"
        return f"{series.get('name')} · {kind} · unit={series.get('unit')}", False
    if name == "run_diagnostic_rules":
        return (
            f"{len(result.get('findings', []))} finding(s) · "
            f"ran {', '.join(result.get('rules_run', [])) or '—'} · "
            f"skipped {len(result.get('skipped', []))}",
            False,
        )
    if name == "summarize_session":
        return f"session summary · {len(result.get('signals', []))} signals", False
    return "ok", False


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def build_plot_series(raw: dict) -> dict | None:
    """Decimate the richest recorded series in a trace into a chart-ready shape."""
    best = None
    for inv in raw.get("tool_invocations", []):
        series = (inv.get("result") or {}).get("series")
        if series and isinstance(series.get("samples"), list):
            if best is None or len(series["samples"]) > len(best["samples"]):
                best = series
    if not best or not best.get("samples"):
        return None

    samples = best["samples"]
    t0 = _parse(samples[0]["timestamp"])
    step = max(1, -(-len(samples) // PLOT_POINTS))  # ceil division
    kept = []
    for i in range(0, len(samples), step):
        p = samples[i]
        kept.append(
            {
                "t": round((_parse(p["timestamp"]) - t0).total_seconds(), 1),
                "v": p["value"],
                "q": p.get("quality"),
            }
        )
    last = samples[-1]
    last_t = round((_parse(last["timestamp"]) - t0).total_seconds(), 1)
    if kept[-1]["t"] != last_t:
        kept.append({"t": last_t, "v": last["value"], "q": last.get("quality")})

    plot = {
        "name": best["name"],
        "unit": best["unit"],
        "t0iso": samples[0]["timestamp"],
        "samples": kept,
    }
    if best["unit"] in UNIT_REFERENCE:
        plot["ref"] = UNIT_REFERENCE[best["unit"]]
    return plot


def tag_citation_offsets(answer: dict, plot: dict) -> dict:
    """Add a `t` offset to each citation that lands on the plotted signal."""
    if not answer or not plot:
        return answer
    t0 = _parse(plot["t0iso"])
    answer = json.loads(json.dumps(answer))  # deep copy — don't mutate the source
    for claim in answer.get("claims", []):
        for cite in claim.get("citations", []):
            if cite.get("signal") == plot["name"] and cite.get("timestamp"):
                cite["t"] = round((_parse(cite["timestamp"]) - t0).total_seconds(), 1)
    return answer


def compact_trace(raw: dict) -> dict:
    invocations = []
    for inv in raw.get("tool_invocations", []):
        summary, is_err = summarize(inv["name"], inv.get("result", {}))
        invocations.append(
            {
                "name": inv["name"],
                "arguments": inv.get("arguments", {}),
                "summary": summary,
                "is_error": inv.get("is_error", False) or is_err,
                "result": truncate_arrays(inv.get("result", {})),
            }
        )
    plot = build_plot_series(raw) if raw.get("outcome") == "answer" else None
    answer = tag_citation_offsets(raw.get("answer"), plot) if plot else raw.get("answer")
    return {
        "trace_id": raw["trace_id"],
        "question": raw["question"],
        "outcome": raw["outcome"],
        "source": raw.get("source"),
        "iteration": raw.get("iteration"),
        "forced_final": raw.get("forced_final"),
        "validation_retries": raw.get("validation_retries"),
        "signals_touched": raw.get("signals_touched", []),
        "signals_available": raw.get("signals_available"),
        "tool_invocations": invocations,
        "answer": answer,
        "refusal": raw.get("refusal"),
        "plot_series": plot,
    }


def main() -> None:
    by_id = {}
    for f in sorted(TRACES_DIR.glob("cap_*.json")):
        raw = json.loads(f.read_text())
        by_id[raw["trace_id"]] = compact_trace(raw)

    ordered = [by_id[t] for t in FEATURED if t in by_id]
    ordered += [v for k, v in sorted(by_id.items()) if k not in FEATURED]

    payload = {
        "traces": ordered,
        "calibration": json.loads(CALIBRATION.read_text()),
    }
    banner = (
        "// AUTO-GENERATED by site/build_data.py from data/evals/*. Do not edit by hand.\n"
        "// Every trace below is a real recorded run against the synthetic source.\n"
    )
    OUT.write_text(banner + "window.CANOPY_DATA = " + json.dumps(payload, indent=2) + ";\n")
    print(f"wrote {OUT.relative_to(ROOT)} · {len(ordered)} traces")


if __name__ == "__main__":
    main()
