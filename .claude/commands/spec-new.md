---
description: Draft a new spec under .claude/specs/active/ from the feature template
argument-hint: <short-slug> [one-line summary]
---

You are starting a new spec-driven unit of work in this repo.

Arguments: `$ARGUMENTS` — the first token is the kebab-case slug; the rest (if any) is a one-line summary the user wants in the title.

Steps:

1. **Validate the slug.** Reject if it isn't kebab-case or is longer than ~5 words; ask for a better one. If the user passed no arguments, ask them for a slug + summary before doing anything else.
2. **Check for collisions.** If `.claude/specs/active/<slug>.md` already exists, stop and tell the user — don't overwrite. Suggest reading the existing one with `/spec-implement <slug>`.
3. **Create the file.** Copy `.claude/specs/_TEMPLATE.md` to `.claude/specs/active/<slug>.md`. Fill in:
   - Title from the user's one-liner (or a sensible derivation of the slug).
   - `Status: draft`, `Created: <today's date>`.
   - Leave the body sections present but empty/templated — the user fills them in interactively.
4. **Interview the user.** Ask focused questions to populate Problem, Goal, Non-goals, and Approach. Don't ask everything at once — one or two questions at a time, in conversation. Use what you already know about the repo (CLAUDE.md, existing code) to suggest concrete file paths and affected surfaces rather than asking the user to list them from memory.
5. **Don't implement yet.** This command produces a spec, not code. End by telling the user the file path and recommending `/spec-implement <slug>` once the spec is solid.

If the user wants a lightweight bug spec instead, use `.claude/specs/_TEMPLATE_BUG.md` and skip the long interview — just capture symptom, suspected cause, and fix.
