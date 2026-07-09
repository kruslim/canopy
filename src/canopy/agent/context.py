"""Context compaction — context management as an active discipline (docs/05).

Tool results re-enter the conversation as context, so uncapped history destroys the agent:
the window fills with sample arrays and the model loses the thread. Policy: when the
message log exceeds a budget, the *oldest* tool results are compacted into a one-line
summary ("EngineRPM: 200 samples, 812.4–3187.9 rpm") and the arrays dropped. The findings
survive in state; the bulk does not. The most recent tool results are always left intact —
they are what the model is currently reasoning about.

Budget is measured in characters (~4 chars/token) because a tokenizer here would add a
dependency for what is a coarse threshold, not an accounting system.
"""

from __future__ import annotations

import json

from langchain_core.messages import AnyMessage, ToolMessage

# ~6k tokens of history before old tool results start collapsing to one-liners.
DEFAULT_BUDGET_CHARS = 24_000

# The newest tool results are never compacted, whatever the budget says.
_KEEP_RECENT = 2

_COMPACTED_MARK = "[compacted] "


def _summarize_payload(payload: dict) -> str:
    """One line that preserves what the model may still need: shape, range, unit."""
    if "series" in payload:
        series = payload["series"]
        samples = series.get("samples", [])
        if not samples:
            return f"{series.get('name', '?')}: 0 samples"
        values = [s["value"] for s in samples]
        line = (
            f"{series.get('name', '?')}: {len(samples)} samples, "
            f"{min(values):g}–{max(values):g} {series.get('unit', '?')}"
        )
        if payload.get("truncated"):
            line += " (decimated)"
        return line
    if "findings" in payload:
        n = len(payload["findings"])
        skipped = len(payload.get("skipped", []))
        rules = ", ".join(payload.get("rules_run", [])) or "none"
        return f"{n} finding(s) from rules [{rules}], {skipped} rule(s) skipped"
    if "signals" in payload:
        names = [s.get("name", "?") for s in payload["signals"]]
        return f"{len(names)} signals available: {', '.join(names)}"
    text = json.dumps(payload)
    return text if len(text) <= 200 else text[:200] + "…"


def _summarize(message: ToolMessage) -> str:
    content = message.content if isinstance(message.content, str) else json.dumps(message.content)
    try:
        payload = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        payload = None
    if isinstance(payload, dict):
        summary = _summarize_payload(payload)
    else:
        summary = content[:200]
    tool = message.name or "tool"
    return f"{_COMPACTED_MARK}{tool} → {summary}"


def _size(message: AnyMessage) -> int:
    content = message.content
    return len(content) if isinstance(content, str) else len(json.dumps(content, default=str))


def compaction_updates(
    messages: list[AnyMessage], budget_chars: int = DEFAULT_BUDGET_CHARS
) -> list[ToolMessage]:
    """Return replacement ``ToolMessage``s (same ids) that bring history under budget.

    Returned messages carry the id of the original, so LangGraph's ``add_messages`` reducer
    swaps them in place rather than appending. Empty list means nothing to do.
    """
    total = sum(_size(m) for m in messages)
    if total <= budget_chars:
        return []

    candidates = [
        m
        for m in messages
        if isinstance(m, ToolMessage)
        and m.id
        and isinstance(m.content, str)
        and not m.content.startswith(_COMPACTED_MARK)
    ]
    # Oldest first, most recent _KEEP_RECENT untouchable.
    candidates = candidates[: -_KEEP_RECENT or None]

    updates: list[ToolMessage] = []
    for message in candidates:
        if total <= budget_chars:
            break
        summary = _summarize(message)
        total -= _size(message) - len(summary)
        updates.append(
            ToolMessage(
                content=summary,
                tool_call_id=message.tool_call_id,
                name=message.name,
                id=message.id,
            )
        )
    return updates
