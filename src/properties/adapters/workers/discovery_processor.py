import structlog

from properties.container import Container
from properties.domain.exceptions import (
    PropertyMissingCoordinatesError,
    PropertyNotFoundError,
)

log = structlog.get_logger()


async def handle_property_created(data: dict, context) -> None:
    """Handle PROPERTY_CREATED event — discover amenities for the new property."""
    container = context["property"]
    property_id = data.get("property_id")
    if not property_id:
        log.warning("discovery.missing_property_id", data=data)
        return
    try:
        await container.discover_property_amenities.execute(property_id=property_id)
    except PropertyMissingCoordinatesError:
        log.info("discovery.skipped_no_coordinates", property_id=property_id)
    except PropertyNotFoundError:
        log.warning("discovery.property_not_found", property_id=property_id)


async def process_event(body: dict, container: Container) -> None:
    """Legacy entry point for direct worker calls."""
    data = body.get("data", {})
    context = {"property": container}
    await handle_property_created(data, context)
