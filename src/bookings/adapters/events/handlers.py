import structlog

from bookings.domain.exceptions import ApplicantRiskTooHighError

logger = structlog.get_logger()


async def handle_applicant_screened(data: dict, context) -> None:
    """Create booking applicant from APPLICANT_SCREENED event."""
    container = context["booking"]
    try:
        applicant = await container.applicant_service.create_from_screening(data)
        logger.info(
            "booking_applicant_created",
            applicant_id=applicant.id,
            external_id=applicant.external_id,
        )
    except ApplicantRiskTooHighError:
        logger.info("booking_applicant_rejected_high_risk", external_id=data.get("applicant_id"))
