import structlog

from properties.domain.exceptions import (
    PropertyMissingCoordinatesError,
    PropertyNotFoundError,
)
from shared.events.base import DomainEvent

log = structlog.get_logger()


async def handle_property_created(event: DomainEvent, context) -> None:
    """Handle PROPERTY_CREATED.v1 — discover amenities for the new property.

    Post-carried-state migration: the payload now carries the full Property
    snapshot (`data["id"]`, plus address/status/characteristics/...). This
    handler only needs `data["id"]` — it resolves everything else via the
    property's own aggregate repo. Kept small so the discovery concern
    stays where it lives.
    """
    container = context["property"]
    property_id = event.data.get("id")
    if not property_id:
        log.warning("discovery.missing_property_id", event_id=event.event_id)
        return
    try:
        await container.discover_property_amenities.execute(property_id=property_id)
    except PropertyMissingCoordinatesError:
        log.info("discovery.skipped_no_coordinates", property_id=property_id)
    except PropertyNotFoundError:
        log.warning("discovery.property_not_found", property_id=property_id)
