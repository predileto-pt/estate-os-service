import json
from dataclasses import asdict

import boto3
import structlog

from core_api.application.ports.event_bus import EventBus
from core_api.domain.events import DomainEvent

log = structlog.get_logger()


class SQSEventBus(EventBus):
    def __init__(
        self,
        queue_url: str,
        region: str = "eu-west-1",
        endpoint_url: str | None = None,
        aws_access_key_id: str = "",
        aws_secret_access_key: str = "",
    ) -> None:
        self._queue_url = queue_url
        self._client = boto3.client(
            "sqs",
            region_name=region,
            endpoint_url=endpoint_url,
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
        )

    async def publish(self, event: DomainEvent) -> None:
        event_data = asdict(event)
        # Convert UUIDs and datetimes to strings
        for key, value in event_data.items():
            if hasattr(value, "isoformat"):
                event_data[key] = value.isoformat()
            elif hasattr(value, "hex"):
                event_data[key] = str(value)

        message = {
            "event_type": type(event).__name__,
            "data": event_data,
        }

        self._client.send_message(
            QueueUrl=self._queue_url,
            MessageBody=json.dumps(message, default=str),
        )
        log.info("event_published", event_type=type(event).__name__)
