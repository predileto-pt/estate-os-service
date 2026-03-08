import asyncio
import json

import structlog

from core_api.adapters.workers.event_processor import process_event
from core_api.entrypoints.bootstrap import get_container

log = structlog.get_logger()


def handler(event, context):
    for record in event["Records"]:
        body = json.loads(record["body"])
        asyncio.run(_process(body))


async def _process(body: dict) -> None:
    container = await get_container()
    await process_event(body, container)
