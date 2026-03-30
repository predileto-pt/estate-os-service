from uuid import UUID

import structlog

logger = structlog.get_logger()


async def process_event(message_body: dict, container) -> None:
    applicant_id = UUID(message_body["applicant_id"])
    force = message_body.get("force", False)
    logger.info("screening_event_received", applicant_id=str(applicant_id))
    await container.screening_service.screen_applicant(applicant_id, force=force)
