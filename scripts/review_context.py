"""Review helper — lay a captured trace's claims beside the ground-truth signal data.

The review step (``scripts/review.py``) asks you to judge whether an answer is sound. Tier-1
checks (does a claim match the samples it cites?) are answerable from the trace alone. Tier-2
checks (is the *whole session* what the claim implies?) want the underlying data. This script
re-reads the signals the trace touched — over the exact window the claims cite — straight from
the deterministic source, so ground truth sits next to the claim instead of in your memory.

Reads data only through ``build_reader()`` and the ``SignalReader`` protocol (seam-legal — it
never learns whether the numbers came from OBD or CAN). No API key: the source is replayed.

    .venv/bin/python scripts/review_context.py cap_001
    CANOPY_SOURCE=synthetic .venv/bin/python scripts/review_context.py cap_003
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime, timedelta
from pathlib import Path

from canopy.readers import build_reader
from canopy.readers.base import UnknownSignalError, WindowTooLargeError

_ROOT = Path(__file__).resolve().parent.parent
_TRACES = _ROOT / "data" / "evals" / "traces"


def _parse_ts(raw: str) -> datetime:
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


def _citations(trace: dict) -> list[dict]:
    ans = trace.get("answer") or {}
    cites: list[dict] = []
    for claim in ans.get("claims", []):
        cites.extend(claim.get("citations", []))
    return cites


def _window_for(signal: str, cites: list[dict]) -> tuple[datetime, datetime] | None:
    ts = [_parse_ts(c["timestamp"]) for c in cites if c.get("signal") == signal]
    if not ts:
        return None
    lo, hi = min(ts), max(ts)
    pad = timedelta(minutes=1)  # a little context on either side of what was cited
    return lo - pad, hi + pad


def render(trace: dict, reader) -> None:
    print(f"── {trace['trace_id']}  [{trace['outcome']}] ──────────────────────────")
    print(f"Q: {trace['question']}")
    print(f"source: {trace['source']}   tools: {', '.join(trace['tools_called']) or '(none)'}")

    # The absence-as-negation smell: tool errors and skipped rules the answer may have ignored.
    errs = [i for i in trace["tool_invocations"] if i["is_error"]]
    if errs:
        print(f"\n⚠ {len(errs)} tool error(s) in this trace — did the answer quietly absorb them?")
        for i in errs:
            print(f"    {i['name']}({i['arguments']}) -> {i['result'].get('message', i['result'])}")
    if trace.get("skipped"):
        print(f"⚠ skipped rules: {trace['skipped']}")

    if trace["outcome"] == "refusal":
        print("\n── refusal (verify the *reason*, not a number) ──")
        print(json.dumps(trace["refusal"], indent=2))
        print(f"\navailable here: {', '.join(reader.available_signals())}")
        return

    ans = trace["answer"] or {}
    cites = _citations(trace)
    print("\n── claims (Tier-1: does each match its citations?) ──")
    for c in ans.get("claims", []):
        print(f"  • {c['statement']}")
        for cite in c.get("citations", []):
            print(
                f"      cite: {cite['signal']} = {cite['value']} "
                f"{cite['unit']} @ {cite['timestamp']}"
            )

    signals = sorted({c["signal"] for c in cites} | set(trace.get("signals_touched", [])))
    print("\n── ground truth (Tier-2: is the whole window what the claim implies?) ──")
    for name in signals:
        window = _window_for(name, cites)
        try:
            desc = reader.describe(name)
        except UnknownSignalError:
            print(f"  {name}: not available from this source — a claim on it is unfounded")
            continue
        if window is None:
            print(f"  {name}: touched but not cited (typical {desc.typical_range} {desc.unit})")
            continue
        start, end = window
        try:
            series = reader.read(name, start, end)
        except WindowTooLargeError as e:
            print(f"  {name}: {e}")
            continue
        vals = [s.value for s in series.samples]
        if not vals:
            print(f"  {name}: no samples in cited window {start:%H:%M:%S}–{end:%H:%M:%S}")
            continue
        lo, hi = min(vals), max(vals)
        typ = desc.typical_range
        band = f" typical {typ}" if typ else ""
        flag = ""
        if typ and (lo < typ[0] or hi > typ[1]):
            flag = "  ← OUT OF TYPICAL BAND"
        print(
            f"  {name}: n={len(vals)}  min={lo:.3g}  max={hi:.3g}  "
            f"mean={statistics.fmean(vals):.3g} {series.unit}{band}{flag}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "trace_id", nargs="?", help="e.g. cap_001 (a file under data/evals/traces/)"
    )
    parser.add_argument(
        "--all", action="store_true", help="Render every trace under data/evals/traces/."
    )
    args = parser.parse_args()
    if bool(args.trace_id) == bool(args.all):
        parser.error("give exactly one of: a trace_id, or --all")

    if args.all:
        paths = sorted(_TRACES.glob("*.json"))
        if not paths:
            print(f"no traces under {_TRACES}", file=sys.stderr)
            return 1
    else:
        path = _TRACES / f"{args.trace_id}.json"
        if not path.exists():
            print(f"no such trace: {path}", file=sys.stderr)
            return 1
        paths = [path]

    reader = build_reader()
    for i, path in enumerate(paths):
        if i:
            print()  # blank line between traces in --all mode
        render(json.loads(path.read_text()), reader)
    return 0


if __name__ == "__main__":
    sys.exit(main())
