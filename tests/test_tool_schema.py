"""Tests for ``inline_schema_defs`` — the $defs/$ref flattener for provider tool binding.

The bug this guards: ``AnswerPayload.model_json_schema()`` emits nested Claim/Citation
models under ``$defs`` referenced by ``$ref``. The Gemini adapter leaves ``$defs`` in place
and warns on every invocation. Inlining removes the indirection entirely.
"""

from __future__ import annotations

import json

from canopy.agent.contracts import AnswerPayload, RefusalPayload
from canopy.agent.tool_schema import inline_schema_defs


def _has_refs(schema: dict) -> bool:
    blob = json.dumps(schema)
    return "$defs" in blob or "$ref" in blob


def test_nested_model_schema_has_refs_before_inlining():
    # Guards the premise: if Pydantic stops emitting $defs, this test tells us the fix is moot.
    assert _has_refs(AnswerPayload.model_json_schema())


def test_inlining_removes_all_defs_and_refs():
    assert not _has_refs(inline_schema_defs(AnswerPayload.model_json_schema()))


def test_inlining_preserves_nested_structure():
    s = inline_schema_defs(AnswerPayload.model_json_schema())
    claim = s["properties"]["claims"]["items"]
    assert set(claim["properties"]) == {"statement", "citations", "confidence"}
    citation = claim["properties"]["citations"]["items"]
    assert set(citation["properties"]) == {"signal", "timestamp", "value", "unit"}


def test_flat_schema_is_unchanged_except_defs_key():
    # RefusalPayload has no nested models: inlining is a no-op on its content.
    raw = RefusalPayload.model_json_schema()
    inlined = inline_schema_defs(raw)
    assert not _has_refs(inlined)
    assert inlined["properties"] == {k: v for k, v in raw["properties"].items()}


def test_sibling_keys_win_over_referenced_definition():
    # A $ref carrying a sibling override should keep the sibling on top of the resolved def.
    schema = {
        "$defs": {"Foo": {"type": "object", "description": "from def"}},
        "properties": {"foo": {"$ref": "#/$defs/Foo", "description": "override"}},
    }
    out = inline_schema_defs(schema)
    assert out["properties"]["foo"]["type"] == "object"
    assert out["properties"]["foo"]["description"] == "override"


def test_cyclic_ref_terminates():
    # Self-referential def must not recurse forever; the guard drops the back-edge.
    schema = {
        "$defs": {"Node": {"type": "object", "properties": {"next": {"$ref": "#/$defs/Node"}}}},
        "properties": {"root": {"$ref": "#/$defs/Node"}},
    }
    out = inline_schema_defs(schema)
    assert not _has_refs(out)
    assert out["properties"]["root"]["type"] == "object"
