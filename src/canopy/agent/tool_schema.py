"""Make a Pydantic JSON schema safe to hand to a provider's tool-binding layer.

Pydantic v2 factors nested models into a top-level ``$defs`` block and references them
with ``$ref``. Some function-calling adapters do not understand that indirection. The
Gemini adapter (``langchain_google_genai``) is the concrete case Canopy hits: it inlines
the ``$ref`` targets but leaves the now-orphaned ``$defs`` key in place, then warns
``Key '$defs' is not supported in schema, ignoring`` on *every* invocation because
``$defs`` is not in its allow-list. The call still works, but the log noise hides real
warnings and the flattened schema is one more thing that can drift.

``inline_schema_defs`` produces an equivalent, self-contained schema: every ``$ref`` is
replaced by the definition it points at, and ``$defs`` is dropped. No indirection remains
for an adapter to mishandle. This is a pure transform over the schema dict — it names no
data source and belongs to the tool-binding seam, not the domain.
"""

from __future__ import annotations

from typing import Any


def inline_schema_defs(schema: dict[str, Any]) -> dict[str, Any]:
    """Return ``schema`` with every ``$ref`` inlined and ``$defs`` removed.

    Sibling keys alongside a ``$ref`` (a ``description`` or ``default`` Pydantic sometimes
    emits next to one) are preserved and win over the referenced definition. Recursive
    definitions are guarded: a ref already being expanded resolves to an empty schema
    rather than recursing forever. Canopy's contracts are acyclic, so this guard only ever
    matters as a safety net.
    """
    defs: dict[str, Any] = schema.get("$defs", {})

    def resolve(node: Any, active: frozenset[str]) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                name = str(node["$ref"]).split("/")[-1]
                siblings = {k: resolve(v, active) for k, v in node.items() if k != "$ref"}
                target = defs.get(name)
                if target is None or name in active:
                    return siblings  # unknown or cyclic ref: keep what we can, drop the ref
                resolved = resolve(target, active | {name})
                return {**resolved, **siblings}
            return {k: resolve(v, active) for k, v in node.items() if k != "$defs"}
        if isinstance(node, list):
            return [resolve(item, active) for item in node]
        return node

    return resolve({k: v for k, v in schema.items() if k != "$defs"}, frozenset())
