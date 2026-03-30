from collections.abc import Callable, Coroutine
from typing import Any

import structlog

log = structlog.get_logger()

type EventHandler = Callable[[dict, Any], Coroutine[Any, Any, None]]


async def _handle_applicant_screened(data: dict, context: Any) -> None:
    container = context["customer"]
    await container.email_service.send(
        to=data.get("owner_email", ""),
        subject="Screening Complete - " + data.get("name", "Applicant"),
        html=(
            f"<p>The screening for {data.get('name', 'an applicant')} has been completed. "
            f"Risk level: {data.get('screening', {}).get('risk_level', 'N/A')}</p>"
        ),
    )
    log.info("screening_notification_sent", applicant_name=data.get("name"))


HANDLERS: dict[str, EventHandler] = {
    "APPLICANT_SCREENED": _handle_applicant_screened,
}


async def process_event(message_body: dict, container: Any) -> None:
    event_type = message_body.get("event_type", "")
    handler = HANDLERS.get(event_type)
    if handler:
        await handler(message_body.get("data", {}), container)
    else:
        log.warning("unknown_event_type", event_type=event_type)
