"""SQS-backed `CommandPublisher`.

Commands are point-to-point — one dedicated queue per command type.
Payload is the canonical `DomainEvent` envelope via `event.to_json()`,
same shape as what `SNSEventPublisher` emits for broadcast events.
"""

from typing import Any

import aioboto3
import structlog

from shared.events.base import DomainEvent

log = structlog.get_logger()


class SQSCommandPublisher:
    def __init__(
        self,
        session: aioboto3.Session,
        endpoint_url: str | None = None,
    ) -> None:
        self._session = session
        self._endpoint_url = endpoint_url

    async def send(self, queue_url: str, event: DomainEvent) -> None:
        kwargs: dict[str, Any] = {}
        if self._endpoint_url:
            kwargs["endpoint_url"] = self._endpoint_url
        async with self._session.client("sqs", **kwargs) as sqs:
            await sqs.send_message(QueueUrl=queue_url, MessageBody=event.to_json())
        log.info(
            "command_sent",
            event_type=event.event_type,
            event_id=event.event_id,
            queue_url=queue_url,
        )
