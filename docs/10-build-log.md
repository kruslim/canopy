# 10 — Build Log

**Phase:** continuous. Write entries *as they happen*, not reconstructed afterward.

---

## Why this file exists

Doc 03 said it plainly:

> Being able to say *"the model kept doing X, so I added this sentence, and it stopped"* is worth more than any architecture diagram.

That story only exists if you wrote it down when it happened. A week later you'll remember that the agent misbehaved; you won't remember the exact description that fixed it, or what it did before, or why your first fix didn't work.

This log is the raw material for the Tier 3 interview answers in Doc 09 — the ones where you separate from the field. It is also the honest record of where the architecture leaked, which is a better story than pretending it never did.

**Rule:** if a debugging session took more than twenty minutes, it earns an entry.

---

## Entry types

Use whichever fits. Don't force a format.

| Type | When | Why it matters later |
|---|---|---|
| **Model misuse** | The agent did something wrong you had to fix in a description or prompt | Tier 3, "show me a description you rewrote" |
| **Decision** | You chose between two defensible options | "Why did you...?" questions |
| **Leak** | Something above the seam had to change | Honest architecture story |
| **Surprise** | Reality contradicted the design doc | Proves you observed rather than assumed |
| **Number** | You measured something | README material |

---

## Template

```markdown
### [YYYY-MM-DD] Phase N — <short title>
**Type:** model misuse | decision | leak | surprise | number

**What happened**
<Concrete. What did you observe? Paste the actual bad output.>

**Why**
<Your diagnosis. If you were wrong at first, say so and say what changed your mind.>

**Fix**
<Before/after. For descriptions, paste both versions verbatim.>

**Did it work**
<How you verified. Which test, which eval case.>

**Open question**
<Optional. What you still don't understand.>
```

---

## Seed entries — the things you will almost certainly hit

Pre-written prompts. Fill in the real details when they occur. Delete any that don't.

---

### [ ] Phase 1 — First tool description rewrite
**Type:** model misuse

The most valuable entry in this file. Doc 09 lists it as a Tier 3 question you must have a real answer to.

Watch for: the model calling `get_signal` for a signal that doesn't exist, rather than calling `list_available_signals` first. Or performing timing analysis on a point read despite the warning.

**Capture the before-description verbatim.** Not a paraphrase. The exact text that failed.

---

### [ ] Phase 2 — Claude Desktop smoke test
**Type:** model misuse

Doc 04 called this *"the most informative five minutes of Phase 2"* and predicted it would be your *"first honest encounter with the model misusing a tool."*

Register the MCP server, ask something in natural language, watch the tool calls. Write down exactly what it did wrong before you fix anything.

---

### [ ] Phase 3 — Iteration cap distribution
**Type:** number

Doc 05: *"Set `max_iterations = 8` as a starting point. Log the actual distribution. If real questions routinely need six, your tools are too granular."*

Record the histogram. If you retune the cap or merge tools, that's a decision entry too.

---

### [ ] Phase 3 — The validation-retry escape clause
**Type:** surprise

Doc 06 predicted this precisely: told that it cited a signal it never retrieved, a model will often respond by **calling the tool to retrieve it** — chasing a signal that doesn't exist, burning iterations, eventually confabulating.

Did it happen? Did adding the explicit escape instruction stop it? This is a clean before/after and makes an excellent interview anecdote.

---

### [ ] Phase 3 — Markdown fences
**Type:** surprise

Doc 06: *"Every practitioner has independently rediscovered this, and it is a small honest detail worth a line in your build log."*

One line. But it's a real line.

---

### [ ] Phase 4 — Rubric calibration
**Type:** decision

Doc 07: the calibration session *"is where you discover that 'overconfident' meant three different things to three people."*

Solo project, so you're the panel. Score 20 traces, wait a week, score them again blind. Where did you disagree with yourself? Those are the rubric's soft spots. **Record the self-agreement number** — Doc 09 requires you to state it as the ceiling for your judge.

---

### [ ] Phase 4 — Judge disagreement examples
**Type:** number

Doc 07 wants `disagreement_examples: list[str]` for the README. Pull two or three trace IDs where the judge and you diverged, and write *why*. Almost certainly `OVERCONFIDENT` — a judgment call a rubric only partially disciplines.

---

### [ ] Phase 5 — Did the seam hold?
**Type:** leak *(hopefully not)*

Doc 08 is unambiguous:

> If any file above the seam changes, the abstraction leaked. Find out where, and say so honestly in the build log. **A leaked abstraction that you diagnosed is a better interview story than a clean one you got by luck.**

Paste the actual `git diff --stat`. If `tools/` or `agent/` shows a nonzero line count, that entry is *more* valuable than a clean diff, not less — provided you explain what assumption in Doc 02 turned out to be wrong.

---

### [ ] Phase 5 — `available_signals()`: DBC contents or capture contents?
**Type:** decision

Doc 08 flagged this as a real design decision with a noted trade-off, and predicted *"someone will ask."* Record which you chose and why.

---

### [ ] Phase 5 — Endianness
**Type:** surprise

Doc 01 warned; Doc 08 called it *"the single most dangerous bug in the project, because it produces numbers. Not exceptions — numbers."*

If the range-check gate caught it, that's a triumphant entry: the defense you built at the bottom of the stack caught the failure that nothing above the seam could have. If it *didn't* catch it and you found it by eye, that's an even better entry — say what you'd change.

---

## Anti-patterns for this file

**Don't reconstruct.** An entry written a month later is a design doc, not a log. It will read as such.

**Don't sanitize.** "I initially thought X, which was wrong, because Y" is the sentence that proves you understand the system. Deleting the wrong turn deletes the evidence of understanding.

**Don't omit the leaks.** Doc 08 again: a diagnosed leak beats a lucky clean run. The interviewer is trying to find out whether you observed a real system or assembled one from a tutorial. Leaks are proof of observation.

**Don't paraphrase model output.** Paste it. The exact confabulated sentence is the artifact.

---

## Harvesting this file

Before applying, mine it for the Doc 09 rehearsal checklist:

- [ ] One **"the model kept doing X, so I added this sentence"** story, with both versions verbatim
- [ ] Your **judge-agreement number** and your **self-agreement ceiling**
- [ ] One **decision** you can defend from either side
- [ ] One **surprise** where reality contradicted your design doc
- [ ] Whether the **seam held**, and if not, precisely where it leaked

Five entries. That's the difference between a repo and a portfolio.
