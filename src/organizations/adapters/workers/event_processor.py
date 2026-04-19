import structlog

from shared.events.base import DomainEvent

log = structlog.get_logger()


async def handle_applicant_screened(event: DomainEvent, context) -> None:
    """Handle APPLICANT_SCREENED.v1 — send screening-complete email to the org owner."""
    container = context["customer"]
    data = event.data
    await container.email_service.send(
        to=data.get("owner_email", ""),
        subject="Screening Complete - " + data.get("name", "Applicant"),
        html=(
            f"<p>The screening for {data.get('name', 'an applicant')} has been completed. "
            f"Risk level: {data.get('screening', {}).get('risk_level', 'N/A')}</p>"
        ),
    )
    log.info("screening_notification_sent", applicant_name=data.get("name"))
