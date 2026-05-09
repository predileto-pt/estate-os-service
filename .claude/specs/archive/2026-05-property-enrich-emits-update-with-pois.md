# `EnrichProperty` should publish `PROPERTY_UPDATED.v1` carrying POIs

**Status:** shipped
**Created:** 2026-05-09
**Shipped:** 2026-05-09

## Problem

ADR-013 §2a precondition: every `PROPERTY_*.v1` event carries POIs as structured data, and the POI auto-discovery workflow batches its writes into a single `PROPERTY_UPDATED.v1` at the end. The implementation spec `2026-05-listing-semantic-search` wired `PublishProperty` to fetch POIs and pass them to `emit_property_published`, so the *initial* listing seed includes whatever POIs exist at publish time.

But the auto-discovery workflow (`EnrichProperty` in `src/properties/application/use_cases/enrich_property.py`) **doesn't currently emit any event after writing POIs to the catalog.** That means once a property is published with no POIs (because auto-discovery hadn't completed), the post-discovery POI catalog never propagates to the listings projection or the search index. Every subsequent re-discovery (rare, but possible — e.g. via the `force=true` flag) is also invisible to downstream consumers.

Concrete user-visible effect: a listing that gets enriched after publish never gets a `NEARBY:` line in its embedding, so semantic search ranks it worse on POI-bearing queries (*"perto de boas escolas"*).

## Root cause

`EnrichProperty.execute()`:

1. Loads the property aggregate.
2. Calls `places_service.discover_pois(...)`.
3. Replaces the POI catalog via `property_poi_repo.replace_for_property(...)`.
4. Updates the job tracker.
5. **Returns** — no `bump_aggregate_version`, no `emit_property_updated`.

The aggregate version doesn't bump because POIs aren't part of the property aggregate's invariant set; they're a sibling table. But for downstream consumers that care about POIs (today: listings; future: notifications, analytics), the carried-state contract says they should see them via an event.

## Fix

After a successful POI replace in `EnrichProperty.execute`, fetch the just-persisted POIs and emit `PROPERTY_UPDATED.v1` with them in the snapshot. The aggregate version bumps because we're publishing a new state to the bus — keep idempotency tight on the projector side (already version-guarded).

```python
# After replace_for_property succeeds and before returning:
refreshed = await self.property_repo.bump_aggregate_version(prop.id)
pois = await self.property_poi_repo.list_by_property(prop.id)
await emit_property_updated(self.domain_event_publisher, refreshed, pois)
```

`EnrichProperty` already takes `property_poi_repo` and `property_repo`; only the publisher is missing from its constructor. Add `domain_event_publisher: EventPublisher | None = None` (matching the optional pattern other use cases use) and wire it from the container.

The container (`src/properties/container.py`) already constructs `EnrichProperty` when both `property_poi_repo` and `places_service` are present; thread the publisher through.

## Verification

- Unit test: `tests/unit/properties/test_enrich_property_use_case.py`
  - Run `EnrichProperty.execute` end-to-end → assert publisher captured a `PROPERTY_UPDATED.v1` event with the right `pois` field (lean shape).
  - Older event idempotency: re-running with `force=true` against the same property → assert version bumps and the new event reflects the new POI set.
- Integration test (LocalStack): submit `ENRICH_PROPERTY_REQUESTED.v1` via the enrichment endpoint → observe `PROPERTY_UPDATED.v1` on the SNS topic with `pois: [...]` → listings worker projects the row → embedding handler re-runs and `embedded_at` ticks.
- Manual smoke: publish a property with empty POIs (skip enrichment), enable `LISTINGS_EMBEDDING_ENABLED`, run discovery, observe `embedding_status='INDEXED'` with the new canonical hash.

## Out of scope

- POI batching guarantee enforcement — separate test asserting exactly one `PROPERTY_UPDATED.v1` fires per workflow run, not one per POI. (See follow-up "POI batching guarantee" in the parent spec.)
- Notifications context consumption of POI-changed events.

## Commit

`feat(properties): EnrichProperty emits PROPERTY_UPDATED.v1 with POI snapshot`
