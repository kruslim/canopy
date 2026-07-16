"""Serve the Canopy web UI and run the diagnostic agent live behind ``POST /api/ask``.

This is the host that turns the static showcase into an interactive one: it serves the
``site/`` front end and, for each question the chat panel submits, runs the *real* agent
(``run_agent``) against the configured source, then returns the same compacted trace shape
the front end already renders — tool-call record, cited answer or grounded refusal, and the
``plot_series`` the evidence chart annotates.

Nothing here duplicates display logic. It reuses:

* ``canopy.evals.trace.Trace.from_state`` — terminal ``CanopyState`` → serializable trace;
* ``site/build_data.py`` (``compact_trace`` → ``build_plot_series`` + ``tag_citation_offsets``)
  — trace → the front-end shape, including the decimated chart series and citation offsets;
* ``scripts/ask.py`` (``_build_model``) — provider/model construction.

The host stays *above the seam*: it only calls ``run_agent`` and ``build_reader`` and never
names a concrete reader. A ``scenario`` string ("normal" / "overheat") is passed straight
through ``build_reader`` — the mapping to a ground-truth condition lives below the seam.

Errors are results, not crashes (Constraint 3): a missing API key or a failed run returns a
structured JSON payload the chat can render, never an uncaught exception.

Usage:
    .venv/bin/python scripts/serve.py                 # http://127.0.0.1:8000
    .venv/bin/python scripts/serve.py --port 9000 --provider anthropic

Without an API key in ``.env`` the server still runs: ``/api/ask`` replays the closest
recorded trace so the demo works fully offline.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
SITE_DIR = ROOT / "site"
SCRIPTS_DIR = ROOT / "scripts"

# Reuse the site's compaction pipeline and ask.py's model builder without duplicating them.
# Both modules are side-effect-free at import (their entry points are ``__main__``-guarded).
sys.path.insert(0, str(SITE_DIR))
sys.path.insert(0, str(SCRIPTS_DIR))
import build_data as bd  # noqa: E402  (path-dependent import, intentional)
from ask import DEFAULT_MODELS, _build_model  # noqa: E402

from canopy.agent import run_agent  # noqa: E402
from canopy.evals.trace import Trace  # noqa: E402
from canopy.readers import build_reader  # noqa: E402

# Which env var carries each provider's key — used to decide live-vs-replay before we ever
# try to build a model (building one with no key raises).
_PROVIDER_KEYS = {"gemini": "GOOGLE_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}

# Serialize agent runs: the model is shared across requests and the free Gemini tier is
# 10 RPM, so one live run at a time is both correct and quota-friendly. Static GETs and the
# no-key replay path never take this lock.
_AGENT_LOCK = threading.Lock()

_MAX_BODY_BYTES = 64 * 1024
_VALID_SCENARIOS = ("normal", "overheat")


class CanopyServer(ThreadingHTTPServer):
    """A threading HTTP server that carries the shared agent config and replay corpus."""

    daemon_threads = True

    def __init__(self, address, handler, *, provider: str, model_name: str | None) -> None:
        super().__init__(address, handler)
        self.provider = provider
        self.model_name = model_name
        self._model = None
        self._model_lock = threading.Lock()
        # Compact every recorded trace once so the no-key path can replay them instantly.
        self.replay: list[dict] = [
            bd.compact_trace(json.loads(f.read_text()))
            for f in sorted(bd.TRACES_DIR.glob("cap_*.json"))
        ]

    def api_key_present(self) -> bool:
        return bool(os.environ.get(_PROVIDER_KEYS.get(self.provider, "")))

    def model(self):
        """Build the chat model once, lazily, and reuse it across requests."""
        with self._model_lock:
            if self._model is None:
                self._model = _build_model(self.provider, self.model_name)
            return self._model


def _match_replay(server: CanopyServer, question: str, scenario: str) -> dict | None:
    """Find the recorded trace that best answers ``question`` (offline fallback)."""
    q = question.strip().lower()
    traces = server.replay
    if not traces:
        return None
    for t in traces:  # exact question match first
        if t["question"].strip().lower() == q:
            return t
    for t in traces:  # then a substring either way
        tq = t["question"].strip().lower()
        if q and (q in tq or tq in q):
            return t
    if scenario == "overheat":  # scenario hint: the headline overheat trace
        for t in traces:
            if "overheat" in t["question"].lower():
                return t
    return traces[0]  # last resort: something renderable rather than nothing


class CanopyRequestHandler(SimpleHTTPRequestHandler):
    """Serves ``site/`` for GET; runs the agent (or replays a trace) for POST /api/ask."""

    server: CanopyServer  # type: ignore[assignment]

    def log_message(self, fmt: str, *args) -> None:  # noqa: A002 - stdlib signature
        line = fmt % args
        sys.stderr.write(f"  {self.address_string()} - {line}\n")

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802 - stdlib name
        if self.path.split("?", 1)[0] != "/api/ask":
            self._send_json({"ok": False, "error": "not_found"}, status=404)
            return

        def bad(hint: str) -> None:
            self._send_json({"ok": False, "error": "bad_request", "hint": hint}, 400)

        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > _MAX_BODY_BYTES:
            bad("empty or oversized body")
            return
        try:
            data = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, ValueError):
            bad("invalid JSON")
            return

        question = (data.get("question") or "").strip()
        if not question:
            bad("question is required")
            return
        scenario = (data.get("scenario") or "normal").strip().lower()
        if scenario not in _VALID_SCENARIOS:
            bad(f"scenario must be one of {_VALID_SCENARIOS}")
            return

        # No key → replay the closest recorded trace so the demo still works (by design).
        if not self.server.api_key_present():
            match = _match_replay(self.server, question, scenario)
            if match is not None:
                self._send_json(
                    {
                        "ok": True,
                        "live": False,
                        "note": "offline replay — no API key configured, showing a recorded trace",
                        "trace": match,
                    }
                )
            else:
                key = _PROVIDER_KEYS.get(self.server.provider, "the provider API key")
                self._send_json(
                    {
                        "ok": False,
                        "live": False,
                        "error": "no_api_key",
                        "hint": f"Set {key} in .env to run the agent live.",
                    }
                )
            return

        # Live run. One at a time (shared model + rate limits). Any failure becomes a
        # structured result, never a crashed handler thread (Constraint 3).
        try:
            with _AGENT_LOCK:
                model = self.server.model()
                reader = build_reader(scenario=scenario)
                state = run_agent(question, reader, model)
            raw = Trace.from_state(state, trace_id="live").model_dump(mode="json")
            trace = bd.compact_trace(raw)
            self._send_json({"ok": True, "live": True, "scenario": scenario, "trace": trace})
        except Exception as exc:  # noqa: BLE001 - surface any agent/model failure as a result
            self._send_json(
                {"ok": False, "live": True, "error": "agent_failed", "hint": str(exc)}
            )


def main() -> int:
    load_dotenv()  # pull provider keys from the repo-root .env before we check for them

    parser = argparse.ArgumentParser(description="Serve the Canopy web UI + live agent.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--provider",
        choices=tuple(DEFAULT_MODELS),
        default=os.environ.get("CANOPY_PROVIDER", "gemini"),
    )
    parser.add_argument("--model", default=os.environ.get("CANOPY_MODEL") or None)
    args = parser.parse_args()

    handler = partial(CanopyRequestHandler, directory=str(SITE_DIR))
    server = CanopyServer(
        (args.host, args.port), handler, provider=args.provider, model_name=args.model
    )

    live = server.api_key_present()
    mode = f"LIVE ({args.provider})" if live else "OFFLINE replay (no API key)"
    print(f"Canopy web UI → http://{args.host}:{args.port}   [{mode}]")
    if not live:
        key = _PROVIDER_KEYS.get(args.provider, "the provider API key")
        print(f"  (set {key} in .env to enable live agent runs)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down")
        server.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
