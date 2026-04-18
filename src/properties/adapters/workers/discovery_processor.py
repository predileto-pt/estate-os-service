import structlog

from properties.domain.exceptions import (
    PropertyMissingCoordinatesError,
    PropertyNotFoundError,
)
from shared.events.base import DomainEvent

log = structlog.get_logger()


async def handle_property_created(event: DomainEvent, context) -> None:
    """Handle PROPERTY_CREATED.v1 — discover amenities for the new property."""
    container = context["property"]
    property_id = event.data.get("property_id")
    if not property_id:
        log.warning("discovery.missing_property_id", event_id=event.event_id)
        return
    try:
        await container.discover_property_amenities.execute(property_id=property_id)
    except PropertyMissingCoordinatesError:
        log.info("discovery.skipped_no_coordinates", property_id=property_id)
    except PropertyNotFoundError:
        log.warning("discovery.property_not_found", property_id=property_id)
