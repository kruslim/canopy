# 06 — Structured Outputs & Validation

**Phase:** 3 (concurrent with Doc 05)
**Status when done:** the agent's final answer is a validated Pydantic object, malformed output triggers a bounded retry, and unrecoverable failure degrades honestly rather than crashing.

---

## Why this layer exists

Everything up to now produced text. Text is unusable by anything downstream.

If the agent's answer is prose, then the review queue (Doc 07) cannot render it, the eval harness cannot score it field-by-field, and no other system can consume it. Structured output is what turns a chatbot into a **component**.

There is a second, less obvious reason. Constraining output to a schema constrains *reasoning*. A model asked to fill `confidence: Literal["high","medium","low"]` and `evidence: list[SignalSample]` must decide those things explicitly. A model asked to "explain what you found" will produce fluent hedging that hides whether it actually knows.

**The schema is a thinking harness, not just a serialization format.**

---

## The answer contract

```python
from typing import Literal
from pydantic import BaseModel, Field, model_validator


class Citation(BaseModel):
    """Every claim points at data. No exceptions."""
    signal: str
    timestamp: datetime
    value: float
    unit: str


class Claim(BaseModel):
    statement: str = Field(..., max_length=300)
    citations: list[Citation] = Field(..., min_length=1)
    confidence: Literal["high", "medium", "low"]

    @model_validator(mode="after")
    def low_confidence_needs_reason(self):
        if self.confidence == "low" and "because" not in self.statement.lower():
            raise ValueError(
                "A low-confidence claim must state why confidence is low."
            )
        return self


class DiagnosticAnswer(BaseModel):
    summary: str = Field(..., max_length=500)
    claims: list[Claim]
    findings_referenced: list[str]        # rule_ids
    signals_examined: list[str]
    could_not_determine: list[str] = Field(
        default_factory=list,
        description="Questions or sub-questions the available data could not answer.",
    )
    source: SignalSource

    @model_validator(mode="after")
    def signals_must_have_been_touched(self):
        cited = {c.signal for claim in self.claims for c in claim.citations}
        missing = cited - set(self.signals_examined)
        if missing:
            raise ValueError(f"Cited signals never retrieved: {sorted(missing)}")
        return self
```

### Read the validators again — they are the point

`min_length=1` on citations makes an uncited claim **structurally impossible.** The model cannot assert without pointing at data. This is grounding enforced by the type system rather than by hoping the system prompt worked.

`signals_must_have_been_touched` cross-references the answer against the trace from Doc 05. If the model cites `RearCameraActivation` but `signals_examined` never contained it, validation fails. **This catches confabulation mechanically.** It is the single highest-value validator in the project, and it is only possible because Doc 05 tracked `signals_touched`.

`low_confidence_needs_reason` is cruder — a heuristic, not a proof. Include it, but know its limit and say so when asked. Substring checks are brittle; it catches laziness, not adversarial output.

`could_not_determine` defaulting to empty is deliberate. An answer that determined everything has an empty list, which is normal. An answer that should have refused but didn't will have an empty list *and* a claim it couldn't support — caught by the cross-reference validator instead.

---

## Three ways to get structured output, ranked

**1. Tool-call / function-calling schema (preferred).** Bind `DiagnosticAnswer` as a "final answer tool." The model fills the schema through the same mechanism it already uses for tool calls. Best reliability, because the provider enforces the schema at decode time.

**2. Constrained decoding / JSON mode.** The provider guarantees syntactically valid JSON. Good, but *syntactically* valid is not *semantically* valid — you still validate with Pydantic. JSON mode gets you past `json.loads`, not past `min_length=1`.

**3. Prompt-and-parse.** "Respond only with JSON." Least reliable. The model will occasionally wrap it in prose or a markdown fence.

Use (1). Implement (3)'s defenses anyway, because you will hit them.

### The markdown-fence problem

Even with JSON mode, models sometimes emit:

````
```json
{"summary": "..."}
```
````

Strip fences before parsing. Do this once, in a utility, tested. Every practitioner has independently rediscovered this, and it is a small honest detail worth a line in your build log.

---

## The retry loop

Validation failure is not an error — it is a **turn**.

```
validate ──┬── ok ─────────────────► END
           │
           └── ValidationError ────► agent
                                     (with the error appended
                                      as a tool-result message)
```

The critical move: **feed the validation error back to the model as context.** Pydantic errors are unusually good for this — they name the field and the constraint.

```
Your response failed validation:

  claims.0.citations: List should have at least 1 item after validation, not 0
  signals_examined: Cited signals never retrieved: ['RearCameraActivation']

Correct these and respond again. If you cannot cite a signal because you never
retrieved it, remove the claim and add the question to could_not_determine.
```

That last sentence matters enormously. Without it, a model told "you cited a signal you never retrieved" will often respond by **calling the tool to retrieve it** — chasing a signal that doesn't exist, burning iterations, and eventually confabulating. With it, the model has a legal escape: withdraw the claim, declare it undeterminable.

**Bound the retries.** Two is right. `max_validation_retries = 2`, tracked in `CanopyState`.

---

## When retries are exhausted

Do not raise. Doc 05 established the principle for the iteration cap; the same applies here.

Construct a `DiagnosticAnswer` in code — not from the model — containing:

- `summary`: "The agent could not produce a valid structured answer."
- `claims`: `[]`
- `could_not_determine`: the original question
- `signals_examined`: whatever the trace actually holds

This is an honest, machine-readable failure. It flows into the review queue (Doc 07) like any other answer, gets reviewed, and becomes an eval case. A crash produces none of that.

**A system that fails into your eval loop is better than one that fails into your logs.**

---

## What must not be in the schema

Two temptations to resist.

**Do not put raw sample arrays in `DiagnosticAnswer`.** Citations carry individual samples — one point each, the specific evidence. A 200-element series in the answer bloats the review UI and the eval store, and it duplicates data already in the trace. Doc 05's context-compaction discipline applies here too.

**Do not let the model populate `source`.** Set it in code from the active reader. Any field the model *could* get wrong, and that you *already know*, should be filled by you. Reserve the schema for what only the model can produce: interpretation.

That is a generalizable rule worth stating in an interview: *the model fills the fields that require judgment; the code fills the fields that require facts it already has.*

---

## Testing validation without an LLM

All of this is testable with hand-written dicts. No model calls, no cost, fast.

- **Golden parse.** A well-formed answer validates.
- **Uncited claim.** `citations: []` → `ValidationError`.
- **Confabulation.** Cites `RearCameraActivation`, `signals_examined` lacks it → `ValidationError` naming the field.
- **Fence stripping.** Wrapped JSON parses.
- **Retry construction.** Given a `ValidationError`, the feedback message names the failing field and includes the escape instruction.
- **Exhaustion.** After `max_validation_retries`, a code-built degraded answer appears with the question in `could_not_determine`.
- **Refusal interaction.** A `Refusal` (Doc 05) does not go through `DiagnosticAnswer` validation — it is its own terminal type. Assert the graph routes it to `refuse`, not `validate`.

That last test guards a real design decision: refusal and failed-validation are **different outcomes** and must not be conflated. A refusal is a correct, grounded answer that the data doesn't support the question. A validation exhaustion is the agent failing to express itself. Your review queue needs to distinguish them, and so does your eval set.

---

## Definition of done — Phase 3 (output half)

- [ ] `DiagnosticAnswer`, `Claim`, `Citation` defined
- [ ] `min_length=1` on citations — uncited claims structurally impossible
- [ ] `signals_must_have_been_touched` cross-validator against the Doc 05 trace
- [ ] Structured output obtained via tool-call schema, not prompt-and-parse
- [ ] Markdown fence stripping, in a tested utility
- [ ] Validation errors fed back to the model with the field name **and the escape instruction**
- [ ] `max_validation_retries = 2`, tracked in state
- [ ] Exhaustion produces a code-built degraded answer, never an exception
- [ ] `source` filled by code, not by the model
- [ ] Refusal routed separately from validation failure
- [ ] Full validator test suite, all without LLM calls

---

## Questions to be ready for

> *"How do you guarantee valid JSON?"*

I don't rely on a guarantee. I use the provider's tool-call schema so the structure is enforced at decode time, strip markdown fences defensively, then validate with Pydantic — because syntactically valid JSON can still be semantically wrong. Validation failure isn't an error, it's another turn: I feed the Pydantic error back with the field name and a legal escape, capped at two retries, then degrade to a code-built honest failure.

> *"What stops the model from making things up?"*

Two structural constraints, not prompting. Citations have `min_length=1`, so an uncited claim can't serialize. And a cross-validator checks every cited signal against the trace of signals actually retrieved — if it cites something it never fetched, validation fails and it's told to withdraw the claim or mark it undeterminable. That catches confabulation mechanically rather than hoping the system prompt held.

> *"Why not just ask for a summary string?"*

Because prose can't be reviewed field-by-field, scored by an eval harness, or consumed by another system. And more subtly: forcing the model to fill `confidence` and `citations` makes it decide those things explicitly, where a free-text answer lets it hedge fluently. The schema is a thinking harness.

> *"Your `low_confidence_needs_reason` validator does a substring check for 'because'. Isn't that fragile?"*

Yes. It catches laziness, not adversarial output, and I'd say so in a code review. It's there because it's cheap and it caught real cases early. The load-bearing validators are the citation minimum and the trace cross-reference — those are structural. That one is a heuristic and I don't pretend otherwise.
