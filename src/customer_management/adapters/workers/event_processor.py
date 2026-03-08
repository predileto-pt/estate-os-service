import structlog

log = structlog.get_logger()


async def process_event(message_body: dict, container) -> None:
    event_type = message_body.get("event_type")

    if event_type == "APPLICANT_SCREENED":
        data = message_body.get("data", {})
        await container.email_service.send(
            to=data.get("owner_email", ""),
            subject="Screening Complete - " + data.get("name", "Applicant"),
            html=f"<p>The screening for {data.get('name', 'an applicant')} has been completed. Risk level: {data.get('screening', {}).get('risk_level', 'N/A')}</p>",
        )
        log.info("screening_notification_sent", applicant_name=data.get("name"))
    else:
        log.warning("unknown_event_type", event_type=event_type)
