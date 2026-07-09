"""Ask the Canopy agent one question against the configured data source.

The API key is read from a gitignored ``.env`` at the repo root (copy ``.env.example``).
Get a free Gemini key — no credit card — at https://aistudio.google.com/apikey.

Usage:
    .venv/bin/python scripts/ask.py "Is the engine overheating?"
    CANOPY_SOURCE=synthetic .venv/bin/python scripts/ask.py --model gemini-2.5-flash "..."
    .venv/bin/python scripts/ask.py --provider anthropic --model claude-sonnet-4-6 "..."

Prints the tool-call trace (the Phase 3 definition-of-done wants it *visible*) and then
the validated answer or the grounded refusal as JSON.
"""

from __future__ import annotations

import argparse
import os
import sys

from dotenv import load_dotenv

from canopy.agent import run_agent
from canopy.readers import build_reader

# Default free-tier Gemini model: 10 RPM / 250k TPM / 1,500 RPD, 1M-token context,
# no credit card. Flash (not Pro) — Pro moved behind billing in April 2026.
DEFAULT_MODELS = {"gemini": "gemini-2.5-flash", "anthropic": "claude-sonnet-4-6"}


def _build_model(provider: str, model_name: str | None):
    name = model_name or DEFAULT_MODELS[provider]
    if provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI

        if not os.environ.get("GOOGLE_API_KEY"):
            raise SystemExit(
                "GOOGLE_API_KEY is not set. Paste your key into the .env file at the repo "
                "root (get one free at https://aistudio.google.com/apikey)."
            )
        return ChatGoogleGenerativeAI(model=name, max_tokens=2048)
    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(model=name, max_tokens=2048)
    raise SystemExit(f"Unknown provider: {provider!r}")


def main() -> int:
    load_dotenv()  # pull GOOGLE_API_KEY (etc.) from the repo-root .env into the environment

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question", help="Natural-language diagnostics question.")
    parser.add_argument("--provider", choices=("gemini", "anthropic"), default="gemini")
    parser.add_argument("--model", default=None, help="Override the provider's default model.")
    parser.add_argument("--max-iterations", type=int, default=8)
    args = parser.parse_args()

    reader = build_reader()
    model = _build_model(args.provider, args.model)

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
