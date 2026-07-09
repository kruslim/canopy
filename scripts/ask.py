"""Ask the Canopy agent one question against the configured data source.

Usage:
    ANTHROPIC_API_KEY=... .venv/bin/python scripts/ask.py "Is the engine overheating?"
    CANOPY_SOURCE=synthetic .venv/bin/python scripts/ask.py --model claude-sonnet-4-6 "..."

Prints the tool-call trace (the Phase 3 definition-of-done wants it *visible*) and then
the validated answer or the grounded refusal as JSON.
"""

from __future__ import annotations

import argparse
import sys

from langchain_anthropic import ChatAnthropic

from canopy.agent import run_agent
from canopy.readers import build_reader


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question", help="Natural-language diagnostics question.")
    parser.add_argument("--model", default="claude-sonnet-4-6")
    parser.add_argument("--max-iterations", type=int, default=8)
    args = parser.parse_args()

    reader = build_reader()
    model = ChatAnthropic(model=args.model, max_tokens=2048)

    state = run_agent(args.question, reader, model, max_iterations=args.max_iterations)

    print("── trace ──────────────────────────────────────")
    print(f"iterations:       {state.iteration}")
    print(f"tools called:     {', '.join(state.tools_called) or '(none)'}")
    print(f"signals touched:  {', '.join(state.signals_touched) or '(none)'}")
    print(f"findings:         {len(state.findings)}")
    print(f"validation retries: {state.validation_retries}")

    if state.refusal is not None:
        print("── refusal ────────────────────────────────────")
        print(state.refusal.model_dump_json(indent=2))
    elif state.answer is not None:
        print("── answer ─────────────────────────────────────")
        print(state.answer.model_dump_json(indent=2))
    else:
        print("neither answer nor refusal was produced — this is a bug", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
