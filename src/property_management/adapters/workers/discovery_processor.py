import structlog

from property_management.container import Container
from property_management.domain.exceptions import (
    PropertyMissingCoordinatesError,
    PropertyNotFoundError,
)

log = structlog.get_logger()


async def process_event(body: dict, container: Container) -> None:
    event_type = body.get("event_type")
    data = body.get("data", {})
    property_id = data.get("property_id")

    if event_type == "PROPERTY_CREATED":
        if not property_id:
            log.warning("discovery.missing_property_id", body=body)
            return
        try:
            await container.discover_property_amenities.execute(property_id=property_id)
        except PropertyMissingCoordinatesError:
            log.info(
                "discovery.skipped_no_coordinates",
                property_id=property_id,
            )
        except PropertyNotFoundError:
            log.warning(
                "discovery.property_not_found",
                property_id=property_id,
            )
    else:
        log.warning("discovery.unknown_event_type", event_type=event_type)
