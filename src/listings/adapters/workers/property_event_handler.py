"""Projector: maintains `property_listings` from carried-state property events.

Registered on the listings context worker for four event types:
- `PROPERTY_CREATED.v1` — upsert (insert on first event)
- `PROPERTY_UPDATED.v1` — upsert (update columns from snapshot)
- `PROPERTY_DELETED.v1` — delete (guarded by aggregate_version)
- `PROPERTY_PUBLISHED.v1` — upsert (same payload shape as CREATED/UPDATED;
  status flips to ACTIVE in the snapshot, which lets the row through the
  public portal's `WHERE status = ACTIVE` filter)

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
    PROPERTY_LISTING_DELETED_V1,
    PROPERTY_LISTING_NEEDS_ADDRESS_ENRICHMENT_V1,
    PROPERTY_LISTING_UPDATED_V1,
    PROPERTY_UNPUBLISHED_V1,
)

log = structlog.get_logger()


def _parse_occurred_at(value: str) -> datetime:
    """`DomainEvent.occurred_at` is an ISO string; the repo needs a datetime."""
    return datetime.fromisoformat(value)


async def handle_property_event(event: DomainEvent, context: dict) -> None:
    listings = context["listings"]
    data = event.data
    occurred_at = _parse_occurred_at(event.occurred_at)

    # Both PROPERTY_DELETED.v1 (hard delete on the write side) and
    # PROPERTY_UNPUBLISHED.v1 (took off market — property still exists
    # as DRAFT) result in the same projector action: drop the
    # property_listings row. Distinct upstream events so other
    # subscribers (notifications, analytics) can react differently.
    if event.event_type in (PROPERTY_DELETED_V1, PROPERTY_UNPUBLISHED_V1):
        deleted = await listings.property_listing_repo.delete_if_newer(
            property_id=UUID(data["id"]),
            source_aggregate_version=data["aggregate_version"],
            source_occurred_at=occurred_at,
        )
        log.info(
            "property_listings.delete",
            property_id=data["id"],
            source_aggregate_version=data["aggregate_version"],
            source_event_type=event.event_type,
            applied=deleted,
        )
        if deleted:
            await _publish_listing_event(
                context.get("publisher"),
                event_type=PROPERTY_LISTING_DELETED_V1,
                data={"property_id": data["id"]},
                property_id=data["id"],
            )
        return

    # Spec `2026-05-listings-agency-contact`: resolve agency display
    # contact at projection time. Tolerant of a missing port (legacy test
    # paths that build the container without the cross-context adapter)
    # — agency columns stay NULL in that case.
    agency = None
    get_agency = getattr(listings, "get_agency_contact", None)
    if get_agency is not None:
        try:
            agency = await get_agency.execute(UUID(data["organization_id"]))
        except Exception:
            log.exception(
                "property_listings.agency_contact_lookup_failed",
                property_id=data["id"],
                organization_id=data["organization_id"],
            )

    row = await listings.property_listing_repo.upsert_from_event(
        event_data=data,
        source_occurred_at=occurred_at,
        agency=agency,
    )
    applied = row is not None
    log.info(
        "property_listings.upsert",
        property_id=data["id"],
        source_aggregate_version=data["aggregate_version"],
        applied=applied,
    )

    # Skip downstream fan-out when the upsert was idempotency-dropped —
    # the currently-stored row is already as fresh or fresher, and its
    # enrichment + embedding state are preserved.
    if not applied:
        return

    publisher = context.get("publisher")
    if publisher is None:
        return

    # Two listings-internal domain events fire on every applied upsert,
    # routed through SNS for handler isolation (per ADR-008 + the
    # existing NEEDS_ADDRESS_ENRICHMENT precedent):
    # - NEEDS_ADDRESS_ENRICHMENT.v1: the LLM address parser (existing)
    # - PROPERTY_LISTING_UPDATED.v1: the embedding handler (new, spec
    #   `2026-05-listing-semantic-search`). Hash-skip lives on the
    #   handler side, not here, so a publish failure of either event
    #   doesn't gate the other.
    await _publish_listing_event(
        publisher,
        event_type=PROPERTY_LISTING_NEEDS_ADDRESS_ENRICHMENT_V1,
        data={
            "property_id": data["id"],
            "address": data["address"],
            # Postal code rides through to the LLM enrichment handler
            # as an authoritative signal (spec
            # 2026-05-property-address-enrichment-fix). `.get()` is
            # used so events from a pre-spec emitter don't break.
            "postal_code": data.get("postal_code"),
            # Country drives per-country dispatch in the searcher.
            # Defaults to Portugal for legacy events; future
            # `Property.country` will populate this from the upstream
            # event payload directly.
            "country": data.get("country") or "Portugal",
        },
        property_id=data["id"],
    )
    await _publish_listing_event(
        publisher,
        event_type=PROPERTY_LISTING_UPDATED_V1,
        data={"property_id": data["id"]},
        property_id=data["id"],
    )


async def _publish_listing_event(
    publisher,
    *,
    event_type: str,
    data: dict,
    property_id: str,
) -> None:
    """Log-and-swallow publish for listings-internal domain events.

    A missed publish is a monitoring concern, not a transaction abort —
    the row is already committed; the next applied upsert will re-fan
    out to both handlers, and the embedding handler's hash check makes
    that idempotent.
    """
    if publisher is None:
        return
    try:
        await publisher.publish(DomainEvent(event_type=event_type, data=data))
    except Exception:
        log.exception(
            "property_listings.fanout_publish_failed",
            property_id=property_id,
            event_type=event_type,
        )
