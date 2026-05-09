"""Carried-state snapshot builder for property domain events.

Every emission site (`CreateProperty`, `DeleteProperty`, and the 8
update use cases) calls `build_property_snapshot(prop)` to produce the
`data` dict that ships inside `PROPERTY_CREATED.v1` /
`PROPERTY_UPDATED.v1` / `PROPERTY_DELETED.v1` events. Single source of
serialization so the payload shape can't drift across sites.

Payload contract — see
`.claude/specs/active/carried-state-events-and-property-listings-projector.md`
§Payload contract.

POIs (spec `2026-05-listing-semantic-search`): `build_property_snapshot`
accepts an optional `pois` parameter — a list of `PropertyPoi` aggregate
rows. When provided, the snapshot includes a `pois` key with the lean
shape `[{category, name, distance_meters}, ...]`. When omitted, the
`pois` key is **absent** — the listings projector treats this as
"preserve existing pois on the row" (semantically distinct from
`pois: []` which means "no pois"). Only emit sites that actually want
to publish authoritative POI state need to fetch + pass them.

Minimal shape for `PROPERTY_DELETED.v1`: `{id, organization_id,
aggregate_version}`. Use `build_deletion_payload()` for that.
"""

from __future__ import annotations

import re

from properties.domain.models.property import Property
from properties.domain.models.property_poi import PropertyPoi


# Portuguese postal-code format: NNNN-NNN. Used by the listings address
# enrichment LLM as an authoritative signal — see spec
# `2026-05-property-address-enrichment-fix` §Postal-code extraction.
# Word-boundary anchors prevent matches embedded in longer numeric runs.
_POSTAL_CODE_RE = re.compile(r"\b(\d{4}-\d{3})\b")


def _extract_postal_code(address: str) -> str | None:
    """Extract a Portuguese postal code (`NNNN-NNN`) from a free-text
    address. Returns None when no match — the searcher falls back to
    parsing the city name from the address text alone."""
    if not address:
        return None
    match = _POSTAL_CODE_RE.search(address)
    return match.group(1) if match else None


def build_property_snapshot(prop: Property, pois: list[PropertyPoi] | None = None) -> dict:
    """Build the full carried-state payload from a Property aggregate.

    Used by `PROPERTY_CREATED.v1` and `PROPERTY_UPDATED.v1`. The
    listings projector upserts a `property_listings` row directly from
    this dict; it does not re-read the write-side `properties` table.

    `pois`: optional. When provided, each POI is serialized as
    `{category, name, distance_meters}` — the lean shape consumed by the
    listings canonical-text composer. When omitted, the `pois` key is
    not present in the returned dict.
    """
    characteristics = None
    if prop.characteristics is not None:
        characteristics = {
            "area_in_m2": prop.characteristics.area_in_m2,
            "num_of_bedrooms": prop.characteristics.num_of_bedrooms,
            "num_of_bathrooms": prop.characteristics.num_of_bathrooms,
            "built_at": prop.characteristics.built_at,
            "energy_rating": prop.characteristics.energy_rating,
            "floor": prop.characteristics.floor,
            "parking_spaces": prop.characteristics.parking_spaces,
            "has_elevator": prop.characteristics.has_elevator,
            "has_garden": prop.characteristics.has_garden,
            "has_pool": prop.characteristics.has_pool,
        }

    payload: dict = {
        "id": str(prop.id),
        "organization_id": str(prop.organization_id),
        "aggregate_version": prop.aggregate_version,
        "address": prop.address,
        # Extracted postal code rides on every event so the listings
        # address-enrichment handler has an authoritative geographic
        # signal when calling the LLM. Null when no PT postal code
        # appears in the free-text address.
        "postal_code": _extract_postal_code(prop.address),
        "listing_type": prop.listing_type.value,
        "typology": prop.typology.value,
        "status": prop.status.value,
        "description": prop.description,
        "latitude": prop.latitude,
        "longitude": prop.longitude,
        "characteristics": characteristics,
        "prices": [
            {
                "amount": str(p.amount),
                "listing_type": p.listing_type.value,
            }
            for p in prop.prices
        ],
        "images": [
            {
                "id": str(img.id),
                "s3_key": img.s3_key,
                "display_order": img.display_order,
            }
            for img in prop.images
        ],
    }
    if pois is not None:
        payload["pois"] = [
            {
                "category": poi.category.value,
                "name": poi.name,
                "distance_meters": poi.distance_meters,
            }
            for poi in pois
        ]
    return payload


def build_deletion_payload(prop: Property) -> dict:
    """Minimal payload for `PROPERTY_DELETED.v1` — the listings projector
    just needs the id + version guard."""
    return {
        "id": str(prop.id),
        "organization_id": str(prop.organization_id),
        "aggregate_version": prop.aggregate_version,
    }


async def emit_property_updated(
    publisher, prop: Property, pois: list[PropertyPoi] | None = None
) -> None:
    """Publish `PROPERTY_UPDATED.v1` with a fresh snapshot.

    Log-and-swallow on publish failure — matches the existing pattern in
    `CreateProperty` where persistence is already committed and a failed
    publish is a monitoring concern rather than a transaction abort.

    `pois`: forwarded to `build_property_snapshot`. Only callers that
    are publishing authoritative POI state should pass this.
    """
    import structlog

    from shared.events.base import DomainEvent
    from shared.events.types import PROPERTY_UPDATED_V1

    log = structlog.get_logger()
    if publisher is None:
        return
    try:
        await publisher.publish(
            DomainEvent(event_type=PROPERTY_UPDATED_V1, data=build_property_snapshot(prop, pois))
        )
    except Exception:
        log.exception("property.domain_event_failed", property_id=str(prop.id))


async def emit_property_deleted(publisher, prop: Property) -> None:
    """Publish `PROPERTY_DELETED.v1` with the minimal deletion payload."""
    import structlog

    from shared.events.base import DomainEvent
    from shared.events.types import PROPERTY_DELETED_V1

    log = structlog.get_logger()
    if publisher is None:
        return
    try:
        await publisher.publish(
            DomainEvent(event_type=PROPERTY_DELETED_V1, data=build_deletion_payload(prop))
        )
    except Exception:
        log.exception("property.domain_event_failed", property_id=str(prop.id))


async def emit_property_published(
    publisher, prop: Property, pois: list[PropertyPoi] | None = None
) -> None:
    """Publish `PROPERTY_PUBLISHED.v1` with a fresh snapshot.

    Distinct business event for the "went live" moment — downstream
    consumers (notifications, analytics, search indexers) subscribe to
    this specifically rather than treating it as another UPDATED.

    Log-and-swallow on publish failure — matches the existing pattern;
    persistence is already committed when we get here.

    `pois`: forwarded to `build_property_snapshot`. The publish use
    case fetches POIs from the catalog so the listings projector seeds
    `property_listings.pois` with whatever's discovered at publish time.
    """
    import structlog

    from shared.events.base import DomainEvent
    from shared.events.types import PROPERTY_PUBLISHED_V1

    log = structlog.get_logger()
    if publisher is None:
        return
    try:
        await publisher.publish(
            DomainEvent(event_type=PROPERTY_PUBLISHED_V1, data=build_property_snapshot(prop, pois))
        )
    except Exception:
        log.exception("property.domain_event_failed", property_id=str(prop.id))


async def emit_property_unpublished(publisher, prop: Property) -> None:
    """Publish `PROPERTY_UNPUBLISHED.v1` with the minimal id/version
    payload — symmetric to `PROPERTY_DELETED.v1`.

    The listings projector deletes the `property_listings` row on
    receipt; other subscribers (notifications, analytics) can react
    distinctly from a hard delete.

    Log-and-swallow on publish failure — the property's status flip
    to DRAFT is already committed; a missed publish is monitoring
    territory.
    """
    import structlog

    from shared.events.base import DomainEvent
    from shared.events.types import PROPERTY_UNPUBLISHED_V1

    log = structlog.get_logger()
    if publisher is None:
        return
    try:
        await publisher.publish(
            DomainEvent(event_type=PROPERTY_UNPUBLISHED_V1, data=build_deletion_payload(prop))
        )
    except Exception:
        log.exception("property.domain_event_failed", property_id=str(prop.id))
