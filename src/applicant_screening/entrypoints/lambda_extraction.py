import asyncio
import json

import logfire
import structlog
from langfuse import get_client

from shared.config import Settings
from shared.entrypoints.bootstrap import get_applicant_screening_container

log = structlog.get_logger()

_settings: Settings | None = None


def _get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def handler(event, context):
    """SQS Lambda handler for applicant extraction queue."""
    for record in event["Records"]:
        body = json.loads(record["body"])
        asyncio.run(_handle_extraction(body))

    try:
        langfuse = get_client()
        langfuse.flush()
    except Exception:
        pass

    logfire.force_flush()


async def _handle_extraction(body: dict) -> None:
    container = await get_applicant_screening_container()

    with logfire.span(
        "extract_document",
        applicant_id=body["applicant_id"],
        document_id=body["document_id"],
    ):
        from applicant_screening.adapters.workers import extraction_processor

        await extraction_processor.process_event(body, container)
