"""Enrichment handler: dispatches to the country-specific
`AddressSearcher` to resolve a property's free-text address into the
universal `ParsedAddress` envelope.

Spec: `2026-05-property-address-enrichment-fix.md`. Replaces the
single-implementation `AddressParser` flow with a country-keyed
dispatcher (`select_address_searcher`); v1 only Portugal is
implemented.

Runs on the listings context worker, same queue as the projector but a
separate event type. If the searcher raises (LLM error, invalid
output, country not yet implemented), the handler re-raises — the
shared `SQSWorker` does not ack, SQS redelivers up to
`maxReceiveCount=5`, message lands in the DLQ. Crucially, the original
`property_listings` row already exists (projector ran successfully
and inserted with NULL location), so users still see the listing
while ops triages the stuck enrichment.

Before re-raising on failure we bump
`location_enrichment_attempts` on the row so a monitor query can
surface properties with repeated failures.
"""

from __future__ import annotations

from uuid import UUID

import structlog

from listings.application.use_cases.select_address_searcher import (
    select_address_searcher,
)
from listings.domain.exceptions import AddressParseError  # noqa: TCH001 (runtime import)
from shared.events.base import DomainEvent

log = structlog.get_logger()


async def handle_address_enrichment(event: DomainEvent, context: dict) -> None:
    listings = context["listings"]
    property_id = UUID(event.data["property_id"])
    address = event.data["address"]
    # `.get()` so events emitted by the previous code version (no
    # postal_code / country fields) still process cleanly. Defaults
    # match the v1 PT-only assumption.
    postal_code = event.data.get("postal_code")
    country = event.data.get("country") or "Portugal"

    try:
        searcher = select_address_searcher(country, portugal=listings.portugal_address_searcher)
        parsed = await searcher.search(address=address, postal_code=postal_code, country=country)
    except Exception:
        # Record the attempt so the stuck row is visible in a monitor
        # query, then re-raise so SQS redelivers.
        await listings.property_listing_repo.increment_enrichment_attempts(property_id=property_id)
        log.exception(
            "property_listings.enrichment_failed",
            property_id=str(property_id),
            address=address,
            postal_code=postal_code,
            country=country,
        )
        raise AddressParseError(address) from None

    row = await listings.property_listing_repo.update_location(
        property_id=property_id, parsed=parsed
    )
    if row is None:
        # Row was deleted between the PROPERTY_CREATED/UPDATED that queued
        # enrichment and now — fine, drop the message.
        log.info(
            "property_listings.enrichment_target_gone",
            property_id=str(property_id),
        )
        return

    log.info(
        "property_listings.enriched",
        property_id=str(property_id),
        country=parsed.country,
        parish=parsed.parish,
        municipality=parsed.municipality,
        district=parsed.district,
    )
