"""Defensive parsing utilities (docs/06).

Structured output arrives through the tool-call channel, where the provider enforces the
schema at decode time — but the prompt-and-parse failure modes are implemented anyway,
because every practitioner hits them eventually. The classic: a model asked for JSON wraps
it in a markdown fence.
"""

from __future__ import annotations

import re

# ``` or ```json (any language tag) at the very start, closing fence at the very end.
_FENCE = re.compile(r"^\s*```[\w-]*\s*\n?(.*?)\n?\s*```\s*$", re.DOTALL)


def strip_markdown_fences(text: str) -> str:
    """Return ``text`` with a single wrapping markdown code fence removed, if present.

    Non-fenced text passes through untouched. Only a fence that wraps the *entire* payload
    is stripped — a fence in the middle of prose is content, not wrapping.
    """
    match = _FENCE.match(text)
    return match.group(1) if match else text
