import structlog

from bookings.domain.exceptions import ApplicantRiskTooHighError
from shared.events.base import DomainEvent

logger = structlog.get_logger()


async def handle_applicant_screened(event: DomainEvent, context) -> None:
    """Create booking applicant from APPLICANT_SCREENED.v1 event."""
    container = context["booking"]
    data = event.data
    try:
        applicant = await container.applicant_service.create_from_screening(data)
        logger.info(
            "booking_applicant_created",
            applicant_id=applicant.id,
            external_id=applicant.external_id,
        )
    except ApplicantRiskTooHighError:
        logger.info("booking_applicant_rejected_high_risk", external_id=data.get("applicant_id"))
