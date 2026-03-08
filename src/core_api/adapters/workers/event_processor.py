import structlog

log = structlog.get_logger()


async def process_event(message_body: dict, container) -> None:
    event_type = message_body.get("event_type")

    if event_type == "APPLICANT_SCREENED":
        await container.process_screening_result.execute(message_body)
    else:
        log.warning("unknown_event_type", event_type=event_type)
