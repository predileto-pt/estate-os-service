import json

import boto3
import structlog

from properties.application.ports.event_bus import EventBus
from properties.domain.events import DomainEvent

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
        message = event.to_dict()
        self._client.send_message(
            QueueUrl=self._queue_url,
            MessageBody=json.dumps(message, default=str),
        )
        log.info("event_published", event_type=message.get("event_type"))
