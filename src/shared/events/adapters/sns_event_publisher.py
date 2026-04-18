"""SNS-backed `EventPublisher`.

Topic-name rule: AWS SNS permits only `[A-Za-z0-9_-]`. The `event_type`
string (`PROPERTY_CREATED.v1`) keeps its dot form for Kafka/RabbitMQ
portability; we translate dots to dashes at publish time, so
`PROPERTY_CREATED.v1` → topic suffix `PROPERTY_CREATED-v1`.
"""

from typing import Any

import aioboto3
import structlog

from shared.events.base import DomainEvent

log = structlog.get_logger()


class SNSEventPublisher:
    def __init__(
        self,
        session: aioboto3.Session,
        topic_arn_prefix: str,
        endpoint_url: str | None = None,
    ) -> None:
        self._session = session
        self._topic_arn_prefix = topic_arn_prefix
        self._endpoint_url = endpoint_url

    @staticmethod
    def _topic_suffix(event_type: str) -> str:
        return event_type.replace(".", "-")

    async def publish(self, event: DomainEvent) -> None:
        topic_arn = f"{self._topic_arn_prefix}{self._topic_suffix(event.event_type)}"
        kwargs: dict[str, Any] = {}
        if self._endpoint_url:
            kwargs["endpoint_url"] = self._endpoint_url
        async with self._session.client("sns", **kwargs) as sns:
            await sns.publish(TopicArn=topic_arn, Message=event.to_json())
        log.info(
            "domain_event_published",
            event_type=event.event_type,
            event_id=event.event_id,
            topic_arn=topic_arn,
        )
