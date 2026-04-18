from uuid import UUID

import structlog

from shared.events.base import DomainEvent

logger = structlog.get_logger()


async def handle_applicant_screening_requested(event: DomainEvent, container) -> None:
    applicant_id = UUID(event.data["applicant_id"])
    force = event.data.get("force", False)
    logger.info("screening_event_received", applicant_id=str(applicant_id))
    await container.screening_service.screen_applicant(applicant_id, force=force)
