---
description: Implement an active spec from .claude/specs/active/
argument-hint: <slug>
---

You are implementing a spec-driven unit of work.

Arguments: `$ARGUMENTS` — the slug of the spec to implement (matches a file at `.claude/specs/active/<slug>.md`).

Steps:

1. **Locate the spec.** Read `.claude/specs/active/<slug>.md`. If it doesn't exist, list what's in `active/` and ask the user which one they meant. Don't guess.
2. **Sanity-check before coding.** If Problem, Goal, Acceptance criteria, or Approach are blank or hand-wavy, stop and tell the user the spec needs sharpening first. Don't implement against a vague spec.
3. **Resolve open questions.** If `Open questions` has unresolved items, raise them with the user before writing code. Convert resolved answers into the spec body (update the file) so the spec stays the source of truth.
4. **Plan, then implement.** Use the acceptance criteria as your task list. Work through them in order. When reality forces a deviation from the Approach, **update the spec first**, then code.
5. **Update the status.** Flip `Status:` to `in-progress` when you start. When acceptance criteria all pass, ask the user if they want to ship — if yes, flip to `shipped` and move the file to `.claude/specs/archive/<YYYY-MM>-<slug>.md`.
6. **Don't expand scope.** If you discover something tangential, capture it under `Out of scope follow-ups` in the spec, don't silently fix it.

The spec wins. The code follows.
