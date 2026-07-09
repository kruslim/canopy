"""In-process tool execution for the agent's ``tools`` node.

Executes the same registry the MCP server advertises (``tools/registry.py`` — one authority
for name/description/schema/handler), against a ``SignalReader`` held by closure. The
dispatch semantics deliberately mirror the server's: argument-validation failures and
below-seam raises both come back as structured error *payloads* the model can read and
recover from, never as exceptions that crash the loop (Constraint 3).

Nothing here names a data source; the reader arrives as the protocol (Constraint 1).
"""

from __future__ import annotations

from pydantic import ValidationError

from canopy.agent.tool_schema import inline_schema_defs
from canopy.model.signals import SignalSource
from canopy.readers.base import SignalReader
from canopy.tools.registry import TOOLS, TOOLS_BY_NAME


def _invalid_arguments_payload(name: str, exc: ValidationError) -> dict:
    return {
        "error": "invalid_arguments",
        "tool": name,
        "message": f"Arguments did not validate against the schema for {name!r}.",
        "details": [
            {"field": ".".join(str(p) for p in err["loc"]), "problem": err["msg"]}
            for err in exc.errors()
        ],
        "hint": "Re-read the tool's input schema and supply arguments matching it exactly.",
    }


class ToolExecutor:
    """Bind the tool registry to one reader for the life of an agent run."""

    def __init__(self, reader: SignalReader) -> None:
        self._reader = reader

    @property
    def source(self) -> SignalSource:
        return self._reader.source

    def available_signals(self) -> list[str]:
        """Ground truth for the refusal path, straight from the source."""
        return self._reader.available_signals()

    def definitions(self) -> list[dict]:
        """Tool definitions in provider format, schemas verbatim from the Pydantic models
        so the ``Field(description=...)`` text authored in the tool layer reaches the model
        unchanged — the same guarantee the MCP server makes (docs/04)."""
        return [
            {
                "name": spec.name,
                "description": spec.description,
                # Inlined ($defs/$ref removed) so provider tool-binding adapters that don't
                # follow references get a self-contained schema (canopy.agent.tool_schema).
                "input_schema": inline_schema_defs(spec.input_model.model_json_schema()),
            }
            for spec in TOOLS
        ]

    def execute(self, name: str, arguments: dict) -> dict:
        """Run one tool call and return a JSON-serializable payload.

        Success payloads are the tool's output model dumped to JSON mode; error payloads
        carry ``error`` plus recovery information. Both are dicts, because both go back to
        the model as tool results — the model recovers from errors by reading them.
        """
        spec = TOOLS_BY_NAME.get(name)
        if spec is None:
            return {
                "error": "unknown_tool",
                "requested": name,
                "message": f"Unknown tool: {name!r}.",
                "hint": f"Valid tools: {', '.join(s.name for s in TOOLS)}.",
            }

        try:
            inp = spec.input_model.model_validate(arguments or {})
        except ValidationError as exc:
            return _invalid_arguments_payload(name, exc)

        result = spec.invoke(self._reader, inp)
        if isinstance(result, dict):
            return result
        return result.model_dump(mode="json")
