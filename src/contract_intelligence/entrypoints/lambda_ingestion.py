import asyncio
import json

import logfire
import structlog

from shared.config import Settings

log = structlog.get_logger()

_settings: Settings | None = None


def _get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def handler(event, context):
    """SQS Lambda handler for contract ingestion queue."""
    for record in event["Records"]:
        body = json.loads(record["body"])
        asyncio.run(_handle_ingestion(body))

    logfire.force_flush()


async def _handle_ingestion(body: dict) -> None:
    from shared.entrypoints.bootstrap import get_contract_intelligence_container

    container = await get_contract_intelligence_container()

    with logfire.span("contract_ingest_document", document_id=body["document_id"]):
        from contract_intelligence.adapters.workers import ingestion_processor

        await ingestion_processor.process_event(body, container)
