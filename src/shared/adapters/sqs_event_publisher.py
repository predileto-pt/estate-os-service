import aioboto3
import structlog

from shared.events.base import DomainEvent
from shared.events.publisher import DomainEventPublisher

logger = structlog.get_logger()


class SQSDomainEventPublisher(DomainEventPublisher):
    def __init__(
        self,
        session: aioboto3.Session,
        queue_url: str,
        endpoint_url: str | None = None,
    ) -> None:
        self._session = session
        self._queue_url = queue_url
        self._endpoint_url = endpoint_url

    def _client_kwargs(self) -> dict:
        kwargs: dict = {}
        if self._endpoint_url:
            kwargs["endpoint_url"] = self._endpoint_url
        return kwargs

    async def publish(self, event: DomainEvent) -> None:
        async with self._session.client("sqs", **self._client_kwargs()) as sqs:
            await sqs.send_message(
                QueueUrl=self._queue_url,
                MessageBody=event.to_json(),
            )
        logger.info(
            "domain_event_published",
            event_type=event.event_type,
            event_id=event.event_id,
        )
