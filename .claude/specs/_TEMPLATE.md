# <Title>

**Status:** draft | in-progress | shipped
**Owner:** <name>
**Created:** YYYY-MM-DD

## Problem

What's broken or missing today, and why it matters. Concrete, not abstract — link to a bug, a user complaint, a metric, or a constraint that motivated this work.

## Goal

One sentence. The outcome that lets us mark this spec shipped.

## Non-goals

What this spec deliberately does **not** cover. Use this to prevent scope creep before it starts.

## Approach

How we'll solve it. Architecture, data flow, key choices, and the alternatives considered. Reference existing modules by path (`services/events-ingestion/internal/...`, `pkg/kafkautil/...`). If a diagram helps, drop it in.

## Affected files / surfaces

- `services/events-ingestion/internal/adapters/http/handler.go` — what changes
- `pkg/kafkautil/confluent_producer.go` — what changes
- New: `pkg/<new-package>/...`
- Tests: `services/<service>/...`
- Docs: update `docs/src/content/docs/<section>/<page>.md` if architecture changed

## Acceptance criteria

Checklist of observable outcomes. Each item should be testable.

- [ ] …
- [ ] …
- [ ] Tests cover <specific behavior>
- [ ] Docs / CLAUDE.md updated if architecture changed

## Open questions

Things that need a decision before (or during) implementation. Resolve or convert to explicit assumptions before merging the spec.

- ?

## Out of scope follow-ups

Ideas surfaced during spec review that belong in their own future spec. Capture them here so they're not lost.
