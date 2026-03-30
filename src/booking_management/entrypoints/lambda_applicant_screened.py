import asyncio
import json

import structlog

from booking_management.domain.events import ApplicantScreenedEvent
from booking_management.domain.exceptions import ApplicantRiskTooHighError
from shared.entrypoints.bootstrap import get_booking_container

log = structlog.get_logger()


def handler(event, context):
    """SQS Lambda handler for APPLICANT_SCREENED events."""
    for record in event["Records"]:
        body = json.loads(record["body"])
        if body.get("event_type") != "APPLICANT_SCREENED":
            log.info("skipping_non_screening_event", event_type=body.get("event_type"))
            continue
        asyncio.run(_handle_applicant_screened(body))


async def _handle_applicant_screened(body: dict) -> None:
    container = await get_booking_container()

    screening_event = ApplicantScreenedEvent(
        applicant_id=body["applicant_id"],
        organization_id=body["organization_id"],
        form_request_id=body.get("form_request_id", ""),
        name=body["name"],
        email=body["email"],
        risk_level=body["risk_level"],
    )

    try:
        applicant = await container.applicant_service.create_from_screening(screening_event)
        log.info(
            "applicant_created_from_screening",
            applicant_id=applicant.id,
            external_id=applicant.external_id,
            risk_level=applicant.risk_level,
        )
    except ApplicantRiskTooHighError:
        log.info(
            "applicant_rejected_high_risk",
            external_id=body["applicant_id"],
            risk_level=body["risk_level"],
        )
