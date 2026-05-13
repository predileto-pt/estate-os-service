# Re-embed listings after address enrichment lands

**Status:** shipped
**Created:** 2026-05-09

## Symptom

When a property is published, the listings worker fans out two events from the projector:

- `PROPERTY_LISTING_NEEDS_ADDRESS_ENRICHMENT.v1` → `handle_address_enrichment` (LLM address parser)
- `PROPERTY_LISTING_UPDATED.v1` → `handle_listing_embedding` (canonical text + Pinecone)

Both run in parallel via SNS. The embedding handler typically wins the race because its work is faster (one OpenAI embed call) than the address parser (LLM call + reasoning). Result: the **first embedding has `parish/municipality/district = NULL`**, so the canonical text's `LOCATION:` line is absent and the embedding ranks worse for location-bound queries like *"apartamento em Lisboa"*.

When the address handler finishes, it patches `parish/municipality/district` via `PropertyListingRepository.update_location()` — but no event fires, so the embedding handler never re-runs. The vector stays stale until the next `PROPERTY_UPDATED.v1` from properties (which may take days for a steady-state listing).

## Root cause

`handle_address_enrichment` in `src/listings/adapters/workers/address_enrichment_handler.py` writes to the row but doesn't notify the embedding pipeline. The current flow:

```python
row = await listings.property_listing_repo.update_location(
    property_id=property_id,
    parish=parsed.parish,
    municipality=parsed.municipality,
    district=parsed.district,
)
# ... logs success and returns. No fan-out event published.
```

ADR-013 §2c says the embedding handler is driven by `PROPERTY_LISTING_UPDATED.v1`. Address enrichment is a state change worth re-embedding (canonical text gains the LOCATION line) but doesn't currently emit that event.

## Fix

In `handle_address_enrichment`, after a successful `update_location`, publish `PROPERTY_LISTING_UPDATED.v1` so the embedding handler re-runs with location populated. Mirror the projector's existing `_publish_listing_event` log-and-swallow pattern.

```python
# At end of handle_address_enrichment, after `row` is non-None:
publisher = context.get("publisher")
if publisher is None:
    return
try:
    await publisher.publish(
        DomainEvent(
            event_type=PROPERTY_LISTING_UPDATED_V1,
            data={"property_id": str(property_id)},
        )
    )
except Exception:
    log.exception(
        "property_listings.address_enrichment_fanout_failed",
        property_id=str(property_id),
    )
```

Idempotency safety: the embedding handler's hash check skips if the canonical text is unchanged. So if location was already set (re-running address enrichment on an already-enriched row), the second `PROPERTY_LISTING_UPDATED.v1` is a no-op embed call — only metadata refreshes.

## Verification

- Unit test in `tests/unit/listings/test_address_enrichment_handler.py`:
  - Seed a row, run `handle_address_enrichment` → assert publisher captured a `PROPERTY_LISTING_UPDATED.v1` event with the right `property_id`.
  - Run with no publisher in context → no raise.
  - Run with `update_location` returning None (row deleted) → no event published.
- Existing tests for the address-enrichment failure path (LLM raises) must still pass — the new fan-out only fires after a successful `update_location`.
- Manual end-to-end (LocalStack): publish a `PROPERTY_PUBLISHED.v1`, observe two embedding handler runs in the logs (first without LOCATION, second with), and confirm `embedded_at` ticks twice on the row.

## Commit

`fix(listings): re-fire PROPERTY_LISTING_UPDATED after address enrichment`
