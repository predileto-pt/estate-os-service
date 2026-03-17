import asyncio
import json

import structlog

from property_management.adapters.workers.extraction_processor import process_event

log = structlog.get_logger()

_container = None


async def _get_container():
    global _container
    if _container is not None:
        return _container

    from shared.entrypoints.bootstrap import get_property_container

    _container = await get_property_container()
    return _container


def handler(event, context):
    for record in event["Records"]:
        body = json.loads(record["body"])
        asyncio.run(_process(body))

    try:
        from langfuse import get_client

        langfuse = get_client()
        langfuse.flush()
    except Exception:
        pass


async def _process(body: dict) -> None:
    container = await _get_container()
    await process_event(body, container)
