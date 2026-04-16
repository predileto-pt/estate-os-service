---
description: Critique an active spec before implementation
argument-hint: <slug>
---

You are reviewing a spec for clarity, completeness, and scope before any code is written.

Arguments: `$ARGUMENTS` — the slug of the spec to review (matches a file at `.claude/specs/active/<slug>.md`).

Steps:

1. **Read the spec** at `.claude/specs/active/<slug>.md`. Also read CLAUDE.md and any files the spec names under "Affected files" so your review is grounded in the actual code, not generalities.
2. **Critique on these axes** (be specific, cite line numbers / file paths):
   - **Problem clarity** — is the motivation concrete? Could a stranger understand why this matters?
   - **Goal vs. non-goals** — is the line sharp? Is the goal observable / testable?
   - **Approach soundness** — does it fit the existing architecture? Are alternatives considered? Any obvious failure modes?
   - **Affected surfaces** — are the listed files actually the ones that change? Anything missing (tests, migrations, UI, docs)?
   - **Acceptance criteria** — is each item testable? Would passing them all actually mean the goal is met?
   - **Scope** — is this one spec, or three pretending to be one?
   - **Open questions** — are the important unknowns surfaced, or hiding as assumptions?
3. **Write a verdict.** End with one of: *ready to implement*, *needs sharpening* (list what), or *split this spec* (suggest the split).
4. **Do not edit the spec yourself.** This command is a critique — the owner decides what to change. Do not implement code either.
