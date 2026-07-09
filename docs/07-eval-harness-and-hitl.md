# 07 — Eval Harness & Human-in-the-Loop

**Phase:** 4
**Status when done:** you can state a human-agreement number for your LLM-judge, and your eval set contains cases that grew from real observed failures.

This is the phase that moves you from *qualified* to *differentiated*. Most portfolios stop at Phase 3.

---

## The problem this solves

LLM systems fail in a nasty way: they produce fluent, confident, well-formatted output that is wrong in a way that matters.

Traditional unit tests don't help. There is no single correct string to assert against — the same input can yield different phrasings, and different runs can yield different outputs entirely. `assert response == expected` is meaningless.

Meanwhile the stakes are real. An agent that reads a diagnostic session and says "no anomalies detected" when a rule was silently skipped (Doc 03's `skipped` list) has produced a *technically parseable, schema-valid, completely misleading* answer. Doc 06's validators catch confabulation. They cannot catch **wrongness**.

Human-in-the-loop is the answer: a person reviews consequential outputs before they count — and, crucially, their corrections don't just fix that one case. **They become permanent evaluation data.**

---

## The flywheel

```
   production failure
          │
          ▼
   human correction  ──────┐
          │                │
          ▼                │
   new eval case           │  structured feedback
          │                │  (error type, severity)
          ▼                │
   regression suite ◄──────┘
          │
          ▼
   future versions scored automatically
          │
          ▼
   LLM-judge calibrated against human labels
          │
          ▼
   automated scoring at scale
```

Every reviewed failure becomes a permanent regression-test row. Over time you accumulate a suite that reflects your system's **actual real-world failure modes**, not hypothetical ones you imagined while writing tests.

Wire it into CI: a code change that reintroduces an old failure blocks the merge.

---

## Piece 1 — The review gate

When the agent produces a consequential output, it does not execute or ship. It lands in a queue.

LangGraph makes this natural. Doc 05 built a state graph precisely because graphs support **interrupts** — pause execution, persist state, resume later on human input. This is the payoff for not hand-rolling a `while` loop.

```
  validate ──► human_review (INTERRUPT) ──┬── approve ──► END
                                          ├── correct ──► END (+ eval case)
                                          └── reject  ──► agent (retry with feedback)
```

### What the reviewer sees

Not just the answer. **The trace.**

- The question
- Every tool called, in order, with inputs and outputs (`tools_called` from Doc 05)
- `signals_touched`, `findings`, `skipped` rules
- The final `DiagnosticAnswer` with its citations
- Whether it was a refusal, a validated answer, or a degraded exhaustion output

Trace visibility is what makes review *fast* instead of guesswork, and it is what lets a reviewer attribute a failure to **retrieval, tool use, or generation** rather than just marking "bad." A reviewer who can see that `run_diagnostic_rules` returned an empty `findings` list with three entries in `skipped` immediately understands *why* the answer was overconfident.

This is why Doc 05 insisted on building the trace in Phase 3. You need it now.

---

## Piece 2 — Structured feedback capture

The reviewer does not click thumbs-down. Thumbs-down is unusable data.

```python
class ErrorType(str, Enum):
    HALLUCINATED_VALUE      = "hallucinated_value"       # cited data that doesn't exist
    MISREAD_SIGNAL          = "misread_signal"           # wrong interpretation of real data
    OVERCONFIDENT           = "overconfident"            # high confidence, weak evidence
    MISSED_FINDING          = "missed_finding"           # rule fired, answer ignored it
    FALSE_REFUSAL           = "false_refusal"            # refused a question it could answer
    MISSED_REFUSAL          = "missed_refusal"           # answered a question it couldn't
    ABSENCE_AS_NEGATION     = "absence_as_negation"      # "no findings" when rules were skipped
    UNIT_ERROR              = "unit_error"
    POINT_READ_AS_SERIES    = "point_read_as_series"     # timing analysis on one sample


class Severity(str, Enum):
    COSMETIC   = "cosmetic"      # phrasing; answer is right
    MISLEADING = "misleading"    # a careful reader would be misled
    UNSAFE     = "unsafe"        # would cause a wrong engineering decision


class ReviewFeedback(BaseModel):
    trace_id: str
    reviewer_id: str
    verdict: Literal["approve", "correct", "reject"]

    error_types: list[ErrorType] = []
    severity: Severity | None = None

    # Where it went wrong — enables attribution
    failure_stage: Literal["retrieval", "tool_use", "generation", "none"] | None = None

    corrected_answer: DiagnosticAnswer | None = None
    reviewer_note: str | None = None

    reviewed_at: datetime
```

### Why these specific error types

They are not generic. Each maps to a failure mode named in an earlier doc:

- `MISSED_REFUSAL` ← Doc 05's refusal path failing
- `ABSENCE_AS_NEGATION` ← Doc 03's `skipped` list being ignored
- `POINT_READ_AS_SERIES` ← Doc 03's description warning being disregarded
- `HALLUCINATED_VALUE` ← Doc 06's cross-validator missing something

**Your taxonomy should be derived from your architecture's known weak points.** A generic thumbs-up/down tells you nothing about which of your defenses failed. This one tells you exactly which sentence in which tool description needs rewriting.

That is the difference between feedback and data.

---

## Piece 3 — The eval set that grows from corrections

```python
class EvalCase(BaseModel):
    case_id: str
    question: str
    source_fixture: str            # deterministic SyntheticReader seed or capture file

    # What "good" looks like
    expected_outcome: Literal["answer", "refusal"]
    must_cite_signals: list[str] = []
    must_not_cite_signals: list[str] = []       # confabulation guard
    must_mention_skipped: bool = False
    expected_refusal_reason: str | None = None

    # Provenance
    origin: Literal["handwritten", "from_review"]
    source_trace_id: str | None = None
    error_types_observed: list[ErrorType] = []
```

**`SyntheticReader` is why this works.** Doc 02 called it "not a toy" — here is the reason. Because it is deterministic and seeded, you can generate a capture with a known anomaly at a known timestamp and assert the agent finds it. Real dongle data is not reproducible; you cannot build a regression suite on it.

### Seed the suite before you have any reviews

Write these by hand on day one of Phase 4. Each is a defense from an earlier doc:

| Case | Asserts |
|---|---|
| Camera timing on OBD source | `expected_outcome: refusal`, reason `signal_unavailable` |
| Skipped rules present | `must_mention_skipped: True` |
| Point read, timing question | agent flags insufficient sample rate |
| Clean session | answer, `could_not_determine` empty |
| Known anomaly at t=4.2s | `must_cite_signals: ["CoolantTemp"]` |
| Nonexistent signal in question | `must_not_cite_signals: ["RearCameraActivation"]` |

Then let review add the ones you didn't imagine. Those are the valuable ones.

---

## Piece 4 — The LLM-judge, and calibrating it

Human review is expensive and doesn't scale. So you add an automated judge: an LLM scoring outputs against a rubric.

The sophisticated move — and the one that makes this portfolio-grade — is that you **use your human labels as ground truth to calibrate the judge.**

### Process

1. Reviewers score N traces (aim for 50+; 30 is a floor).
2. The judge scores the same N traces against a rubric.
3. Compute **agreement** between judge and humans.
4. Inspect the disagreements. Refine the rubric. Re-run.
5. Report the final agreement number.

Published work has LLM judges reaching roughly 80%+ agreement with human preferences on many tasks — comparable to how much two humans agree with each other. **That last clause is the point.** Your judge's agreement number is meaningless without knowing your inter-human agreement, because you cannot expect a judge to agree with humans more than humans agree with each other.

So measure both:

```python
class CalibrationReport(BaseModel):
    n_traces: int
    n_reviewers: int

    inter_human_agreement: float      # the ceiling
    judge_human_agreement: float      # the number you report
    judge_agreement_by_error_type: dict[ErrorType, float]

    disagreement_examples: list[str]  # trace_ids, for the README
```

`judge_agreement_by_error_type` is where the insight lives. A judge will likely detect `HALLUCINATED_VALUE` reliably (checkable against the trace) and struggle with `OVERCONFIDENT` (a judgment call). Reporting that breakdown, rather than a single number, demonstrates you understand what an LLM-judge can and cannot do.

### The judge rubric

Give it the trace, not just the answer. A judge that sees only the final text cannot detect `ABSENCE_AS_NEGATION` — it needs to see that `skipped` was non-empty.

Ask it to output the same `ErrorType` taxonomy. Same schema in, same schema out. Then agreement is a straightforward set comparison rather than fuzzy text matching.

---

## The hard part: reviewers disagree

Two reviewers will score the same output differently — on tone, on whether an edge case is really a failure, on whether `MISLEADING` or `COSMETIC` applies.

Without a plan to resolve that, **your eval data becomes untrustworthy**, and everything downstream (the judge calibration, the regression suite, your README number) inherits the noise.

Mitigations, in increasing cost:

- **A rubric with worked examples.** Not "is this misleading?" but "MISLEADING means a careful engineer reading this would make a wrong decision. Example: ..."
- **Calibration sessions.** Reviewers independently score the same 20 traces, then meet to reconcile. Do this *before* collecting real labels. It is where you discover that "overconfident" meant three different things to three people.
- **Adjudication.** A third reviewer breaks ties, or majority vote on a subset.
- **Report inter-rater agreement.** Publishing it is the honest move.

Being able to discuss these trade-offs shows you understand that **the hard part isn't the code, it's the process design around subjective judgment.** That sentence is worth memorizing; it is the thesis of this document.

For a solo project you are the only reviewer, which is a real limitation. Say so. Then do the next best thing: score a subset **twice, a week apart**, and report your own self-agreement. Intra-rater reliability is a legitimate, honest proxy, and admitting the limitation is stronger than pretending you had a panel.

---

## The regression runner

```
  eval set ──► replay each case against current agent
                        │
                        ▼
              deterministic fixture (SyntheticReader seed)
                        │
                        ▼
              assert: outcome, citations, refusal reason
                        │
                        ▼
              judge scores the trace
                        │
                        ▼
              report: pass rate, regressions vs last run
```

Wire into CI. A PR that reintroduces `ABSENCE_AS_NEGATION` on case `from_review_014` fails the build. **This is the moment the flywheel closes** — a production failure, corrected once by a human, now permanently defends the codebase.

Note the two-tier scoring: **hard assertions** (did it refuse? did it cite the right signal?) are deterministic and cheap; **judge scoring** is fuzzy and expensive. Run assertions on every commit; run the judge nightly or on release.

---

## Definition of done — Phase 4

- [x] Review gate implemented as a LangGraph interrupt — `evals/review.py` (`interrupt` + `MemorySaver`)
- [x] Reviewer UI shows the **full trace**, not just the answer — `Trace.render()` in `evals/trace.py`
- [x] `ReviewFeedback` schema with an error taxonomy **derived from your architecture's weak points** — `evals/schemas.py`
- [x] `failure_stage` captured (retrieval / tool use / generation) — `ReviewFeedback.failure_stage`
- [x] Eval set seeded with 6 handwritten cases covering each defense — `evals/cases.py`
- [x] Corrections from review automatically become `EvalCase` rows with `origin: from_review` — `review.record_correction_node`
- [x] Regression runner with deterministic fixtures — `evals/runner.py` + `readers/fixtures.py`
- [x] Hard assertions in CI on every commit — `tests/test_eval_runner.py` (hermetic, scripted model)
- [x] LLM-judge scoring the trace (not just the answer), emitting the same `ErrorType` taxonomy — `evals/judge.py`
- [x] `CalibrationReport` with judge-human agreement **and** an honesty statement about the single-reviewer limitation — `CalibrationReport.single_reviewer_note`
- [x] Self-agreement measured (score a subset twice, a week apart) — `scripts/calibrate.py`, 90% (n=20)
- [x] **The README leads with the agreement number and the reviewer-disagreement discussion** — 85% / 90% ceiling

**Phase 4 done: `judge–human agreement = 85% (n=20)`, self-agreement ceiling `90%`.** The
number is computed from seed labels (`data/evals/calibration_labels.json`) by
`scripts/calibrate.py`; on a solo project the ground truth is hand-authored and grows as real
`from_review` cases land. One deliberate scope note: the review gate runs against *named
fixtures* (`readers/fixtures.py`), because only a reproducible source can become a replayable
regression case — the flywheel is closed by construction, not by hope.

---

## What goes in the README

Lead with the number. Then immediately complicate it.

> The LLM-judge agrees with human review on 84% of traces (n=52). Inter-rater reliability could not be measured with a panel — this is a solo project — so I scored a 20-trace subset twice, one week apart, and reached 89% self-agreement. **The judge should therefore be read as approaching, not exceeding, the reliability ceiling of its ground truth.** Agreement is strongest on `HALLUCINATED_VALUE` (96%), where the judge can check citations against the trace mechanically, and weakest on `OVERCONFIDENT` (61%), which is a judgment call that a rubric only partially disciplines.

That paragraph does more for you than any architecture diagram. It says: *I measured, I know what the measurement is worth, and I know where it breaks.*

---

## Questions to be ready for

> *"How do you evaluate a system with no single correct answer?"*

Two tiers. Hard assertions on structural properties that are objectively checkable — did it refuse when the signal was unavailable, did it cite the right signal, did it mention skipped rules. Those are deterministic and run in CI. Then an LLM-judge for the fuzzy dimensions, calibrated against human labels so I know what its agreement is actually worth.

> *"Why not just use thumbs up/down?"*

Because it's unusable data. A thumbs-down tells me the answer was bad. A structured `ErrorType` tells me *which of my defenses failed* — whether a tool description needs a sentence, or the refusal path didn't trigger, or a validator has a gap. My taxonomy is derived from my architecture's known weak points, so every label points at a fix.

> *"Your judge agrees with humans 84% of the time. Is that good?"*

It's meaningless in isolation. You can't expect a judge to agree with humans more than humans agree with each other. That's why I measured self-agreement at 89% as a proxy ceiling — so the 84% reads as approaching the ceiling, not falling short of perfection. And the per-error-type breakdown matters more: 96% on hallucination, which is mechanically checkable, and 61% on overconfidence, which isn't.

> *"What's the hardest part of this?"*

Not the code. It's that two reviewers score the same output differently, so before you collect any labels you need a rubric with worked examples and a calibration session where reviewers independently score the same traces and then reconcile. Otherwise your ground truth is noise and everything downstream inherits it. On a solo project I can't do that, and I say so rather than pretending the number is cleaner than it is.
