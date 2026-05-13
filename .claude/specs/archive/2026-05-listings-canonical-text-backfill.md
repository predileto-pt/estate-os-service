# Listings canonical-text backfill CLI

**Status:** shipped
**Created:** 2026-05-09

## Problem

Two situations produce listings whose embeddings are out of sync with the current `LISTING_CANONICAL_TEXT_VN` schema:

1. **Schema version bump** (e.g., v1 → v2 just shipped: PT POI categories + new `FEATURES:` line). Every existing listing's persisted `embedding_text_hash` is invalidated. Listings naturally re-embed when their next `PROPERTY_LISTING_UPDATED.v1` event fires — but listings that don't get any events sit at the old hash + old canonical text version. Search results mix old-and-new representations in the same Pinecone namespace, dragging quality.
2. **Pre-existing rows from before the embedding pipeline launched.** Same problem: `embedding_status='PENDING'` forever unless something re-fires `PROPERTY_LISTING_UPDATED.v1` for them.

## Goal

A one-shot CLI that re-fires `PROPERTY_LISTING_UPDATED.v1` for every row in `property_listings`, letting the existing embedding handler do the work (hash check makes already-current rows a no-op, so it's safe to re-run).

## Approach

```bash
uv run python -m listings.entrypoints.backfill_embeddings \
  [--filter-status <PENDING|FAILED|...>] \
  [--filter-version <v1|null>] \
  [--batch-size 100] \
  [--dry-run]
```

Implementation under `src/listings/entrypoints/backfill_embeddings.py`:

1. Open a SQLAlchemy session.
2. Stream rows from `property_listings` matching the filter (default: all rows).
3. For each row, publish `PROPERTY_LISTING_UPDATED.v1` to SNS via the standard `SNSEventPublisher`.
4. Sleep `LISTINGS_BACKFILL_RATE_LIMIT_MS` between batches to avoid OpenAI rate limits (default 1000ms per 100-batch).
5. Log progress every batch.

The embedding handler picks up each event off SQS, runs the standard hash-check + embed + upsert flow. No special backfill code path on the consumer side.

Filter flags let ops run targeted backfills:
- `--filter-version v1` → only re-fire rows whose `canonical_text_version='v1'` (after a schema bump).
- `--filter-status FAILED` → retry the FAILED rows ops never investigated.
- `--filter-status PENDING` → catch listings that exist but were never indexed.

## Affected files / surfaces

- New: `src/listings/entrypoints/backfill_embeddings.py` — CLI entrypoint.
- Reuses: `SNSEventPublisher`, `SqlAlchemyPropertyListingRepository`, the existing embedding handler.
- New env var: `LISTINGS_BACKFILL_RATE_LIMIT_MS` (default 1000).

## Acceptance criteria

- [ ] CLI runs end-to-end against a populated DB; every row produces one `PROPERTY_LISTING_UPDATED.v1` event.
- [ ] `--dry-run` lists row IDs without publishing.
- [ ] `--filter-version v1` only emits for rows whose `canonical_text_version` matches.
- [ ] Rate-limit sleep is respected between batches.
- [ ] Idempotency: re-running the backfill is safe (handler hash-check skips no-ops).
- [ ] Smoke test: after a v1→v2 bump, run the backfill, verify all rows reach `canonical_text_version='v2'`.

## Out of scope

- Full namespace flip (model bump). That's a separate procedure — provision new namespace, run backfill into it, atomically swap `VECTOR_INDEX_NAMESPACE`, drop old namespace. The CLI here can be reused but the orchestration is operator-driven.

## Commit

`feat(listings): backfill CLI for property_listings embeddings`
