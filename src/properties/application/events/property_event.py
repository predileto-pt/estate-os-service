"""Carried-state snapshot builder for property domain events.

Every emission site (`CreateProperty`, `DeleteProperty`, and the 8
update use cases) calls `build_property_snapshot(prop)` to produce the
`data` dict that ships inside `PROPERTY_CREATED.v1` /
`PROPERTY_UPDATED.v1` / `PROPERTY_DELETED.v1` events. Single source of
serialization so the payload shape can't drift across sites.

Payload contract — see
`.claude/specs/active/carried-state-events-and-property-listings-projector.md`
§Payload contract.

Minimal shape for `PROPERTY_DELETED.v1`: `{id, organization_id,
aggregate_version}`. Use `build_deletion_payload()` for that.
"""

from __future__ import annotations

from properties.domain.models.property import Property


def build_property_snapshot(prop: Property) -> dict:
    """Build the full carried-state payload from a Property aggregate.

    Used by `PROPERTY_CREATED.v1` and `PROPERTY_UPDATED.v1`. The
    listings projector upserts a `property_listings` row directly from
    this dict; it does not re-read the write-side `properties` table.
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

    return {
        "id": str(prop.id),
        "organization_id": str(prop.organization_id),
        "aggregate_version": prop.aggregate_version,
        "address": prop.address,
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


def build_deletion_payload(prop: Property) -> dict:
    """Minimal payload for `PROPERTY_DELETED.v1` — the listings projector
    just needs the id + version guard."""
    return {
        "id": str(prop.id),
        "organization_id": str(prop.organization_id),
        "aggregate_version": prop.aggregate_version,
    }


async def emit_property_updated(publisher, prop: Property) -> None:
    """Publish `PROPERTY_UPDATED.v1` with a fresh snapshot.

    Log-and-swallow on publish failure — matches the existing pattern in
    `CreateProperty` where persistence is already committed and a failed
    publish is a monitoring concern rather than a transaction abort.
    """
    import structlog

    from shared.events.base import DomainEvent
    from shared.events.types import PROPERTY_UPDATED_V1

    log = structlog.get_logger()
    if publisher is None:
        return
    try:
        await publisher.publish(
            DomainEvent(event_type=PROPERTY_UPDATED_V1, data=build_property_snapshot(prop))
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


async def emit_property_published(publisher, prop: Property) -> None:
    """Publish `PROPERTY_PUBLISHED.v1` with a fresh snapshot.

    Distinct business event for the "went live" moment — downstream
    consumers (notifications, analytics, search indexers) subscribe to
    this specifically rather than treating it as another UPDATED.

    Log-and-swallow on publish failure — matches the existing pattern;
    persistence is already committed when we get here.
    """
    import structlog

    from shared.events.base import DomainEvent
    from shared.events.types import PROPERTY_PUBLISHED_V1

    log = structlog.get_logger()
    if publisher is None:
        return
    try:
        await publisher.publish(
            DomainEvent(event_type=PROPERTY_PUBLISHED_V1, data=build_property_snapshot(prop))
        )
    except Exception:
        log.exception("property.domain_event_failed", property_id=str(prop.id))
