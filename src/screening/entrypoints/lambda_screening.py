import asyncio
import json

import logfire
import structlog
from langfuse import get_client

from shared.config import Settings
from shared.entrypoints.bootstrap import get_screening_container

log = structlog.get_logger()

_settings: Settings | None = None


def _get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def handler(event, context):
    """SQS Lambda handler for applicant screening queue."""
    for record in event["Records"]:
        body = json.loads(record["body"])
        asyncio.run(_handle_screening(body))

    try:
        langfuse = get_client()
        langfuse.flush()
    except Exception:
        pass

    logfire.force_flush()


async def _handle_screening(body: dict) -> None:
    container = await get_screening_container()

    with logfire.span("screen_applicant", applicant_id=body["applicant_id"]):
        from screening.adapters.workers import screening_processor

        await screening_processor.process_event(body, container)
