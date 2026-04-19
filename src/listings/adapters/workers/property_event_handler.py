"""Projector: maintains `property_listings` from carried-state property events.

Registered on the listings context worker for three event types:
- `PROPERTY_CREATED.v1` — upsert (insert on first event)
- `PROPERTY_UPDATED.v1` — upsert (update columns from snapshot)
- `PROPERTY_DELETED.v1` — delete (guarded by aggregate_version)

After every non-DELETED event the projector emits a
`PROPERTY_LISTING_NEEDS_ADDRESS_ENRICHMENT.v1` event so the LLM call
happens out-of-band on its own SNS topic. If the parser fails, the
enrichment message DLQs but the original listing row is already present
with NULL location — handler isolation per ADR-008 §6.

Handler signature (per ADR-008): `(event: DomainEvent, context: dict) -> None`.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

import structlog

from shared.events.base import DomainEvent
from shared.events.types import (
    PROPERTY_DELETED_V1,
    PROPERTY_LISTING_NEEDS_ADDRESS_ENRICHMENT_V1,
)

log = structlog.get_logger()


def _parse_occurred_at(value: str) -> datetime:
    """`DomainEvent.occurred_at` is an ISO string; the repo needs a datetime."""
    return datetime.fromisoformat(value)


async def handle_property_event(event: DomainEvent, context: dict) -> None:
    listings = context["listings"]
    data = event.data
    occurred_at = _parse_occurred_at(event.occurred_at)

    if event.event_type == PROPERTY_DELETED_V1:
        deleted = await listings.property_listing_repo.delete_if_newer(
            property_id=UUID(data["id"]),
            source_aggregate_version=data["aggregate_version"],
            source_occurred_at=occurred_at,
        )
        log.info(
            "property_listings.delete",
            property_id=data["id"],
            source_aggregate_version=data["aggregate_version"],
            applied=deleted,
        )
        return

    row = await listings.property_listing_repo.upsert_from_event(
        event_data=data,
        source_occurred_at=occurred_at,
    )
    applied = row is not None
    log.info(
        "property_listings.upsert",
        property_id=data["id"],
        source_aggregate_version=data["aggregate_version"],
        applied=applied,
    )

    # Skip enrichment fan-out when the upsert was idempotency-dropped — the
    # currently-stored row is already as fresh or fresher, and its
    # enrichment state is preserved.
    if not applied:
        return

    publisher = context.get("publisher")
    if publisher is None:
        return
    try:
        await publisher.publish(
            DomainEvent(
                event_type=PROPERTY_LISTING_NEEDS_ADDRESS_ENRICHMENT_V1,
                data={"property_id": data["id"], "address": data["address"]},
            )
        )
    except Exception:
        # Same log-and-swallow as write-side emissions. A missed
        # enrichment leaves parish/municipality/district NULL; the next
        # PROPERTY_UPDATED event will re-queue enrichment anyway.
        log.exception(
            "property_listings.enrichment_publish_failed", property_id=data["id"]
        )
