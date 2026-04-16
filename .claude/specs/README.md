# Specs

Spec-driven workflow for this repo. One markdown file per unit of work (feature, bugfix, refactor). Specs are the source of truth for *what* and *why* before any code is written.

## Lifecycle

1. **Draft** — copy `_TEMPLATE.md` to `active/<short-slug>.md` and fill it in. Talk through gaps with Claude before implementing. Shortcut: `/spec-new <slug> "<one-line summary>"`.
2. **Review** (optional but recommended) — `/spec-review <slug>` asks Claude to critique clarity, scope, and completeness before any code is written.
3. **Implement** — `/spec-implement <slug>`. Work against the spec. Update the spec when reality diverges; the spec wins, the code follows.
4. **Ship** — once merged, move the file to `archive/YYYY-MM-<slug>.md`. Keep it brief — archived specs are reference, not living docs.

## Conventions

- **Slug**: kebab-case, ≤5 words (`add-llm-insight-generation`, `fix-kafka-consumer-lag`).
- **Granularity**: full spec for features/refactors; a one-paragraph intent note is fine for small bugs (use `_TEMPLATE_BUG.md`).
- **Scope discipline**: if a spec grows past ~1 page of acceptance criteria, split it.
- **Open questions**: resolve before implementing, or mark them as explicit assumptions.

## Layout

```
.claude/specs/
├── README.md              (this file)
├── _TEMPLATE.md           feature/refactor template
├── _TEMPLATE_BUG.md       lightweight bug template
├── active/                in-progress specs
└── archive/               shipped specs (YYYY-MM-<slug>.md)
```

## Two spec surfaces — don't confuse them

This repo has two places where you might find spec-shaped markdown. They serve different audiences:

| Location | Audience | Lifecycle |
|----------|----------|-----------|
| **`.claude/specs/`** (this folder) | The person (or Claude) doing the work right now. Working specs for active and archived work. | `active/` → `archive/YYYY-MM-<slug>.md` |
| **`docs/src/content/docs/specs/`** | Future contributors reading the published Starlight docs site. A curated subset of specs that document lasting patterns. | Permanent reference |

Rules of thumb:

- **Every non-trivial change starts here**, in `.claude/specs/active/`. That's where new work lives.
- **Most shipped specs stay here too**, in `archive/`. They're perfectly good reference material on their own.
- **Only a handful graduate to `docs/`** — the ones that introduce a repeating pattern worth teaching (e.g. `0001-event-batching-compression` in the Starlight site introduces the batching + compression pattern the whole pipeline follows). When you graduate a spec, write the docs version as a polished, audience-facing artefact — don't just copy the working spec verbatim.

For the conceptual overview of SDD itself, read the published [Spec-Driven Development overview](../../docs/src/content/docs/specs/overview.md).

## Slash commands

Three commands live in `.claude/commands/` and are auto-loaded by Claude Code:

- `/spec-new <slug> [summary]` — creates an empty spec in `active/` from the feature template and interviews you to fill it in.
- `/spec-review <slug>` — reads the spec + the affected files and returns a critique (ready / needs sharpening / split this spec).
- `/spec-implement <slug>` — works through the spec's acceptance criteria, updating the spec when reality diverges.
