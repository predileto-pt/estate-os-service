"""SQS-backed `MessageConsumer` + `Message` implementations.

Handles two payload shapes:
  1. Messages delivered via SNS→SQS subscription — SNS wraps the payload in
     an envelope keyed by `Message`. We unwrap it.
  2. Messages delivered directly via `SQSCommandPublisher.send` — the body
     IS the `DomainEvent` JSON. Pass through as-is.

Client reuse: `__aenter__` opens ONE aioboto3 SQS client that is used for
every poll / ack / nack / heartbeat for the worker's entire lifetime.
"""

import json
from typing import Any

import aioboto3

from shared.events.base import DomainEvent


class SQSMessage:
    def __init__(self, sqs_client: Any, queue_url: str, raw: dict[str, Any]) -> None:
        self._sqs = sqs_client
        self._queue_url = queue_url
        self._raw = raw
        body = json.loads(raw["Body"])
        event_json = (
            json.loads(body["Message"]) if isinstance(body, dict) and "Message" in body else body
        )
        self._event = DomainEvent.from_dict(event_json)

    @property
    def event(self) -> DomainEvent:
        return self._event

    @property
    def message_id(self) -> str:
        return self._raw["MessageId"]

    async def ack(self) -> None:
        await self._sqs.delete_message(
            QueueUrl=self._queue_url,
            ReceiptHandle=self._raw["ReceiptHandle"],
        )

    async def nack(self) -> None:
        # No-op on SQS: failing to ack lets the visibility timeout expire,
        # SQS redelivers. The queue's redrive policy (`maxReceiveCount`)
        # decides when the message lands in the DLQ.
        return None

    async def extend_visibility(self, seconds: int) -> None:
        await self._sqs.change_message_visibility(
            QueueUrl=self._queue_url,
            ReceiptHandle=self._raw["ReceiptHandle"],
            VisibilityTimeout=seconds,
        )


class SQSMessageConsumer:
    def __init__(
        self,
        session: aioboto3.Session,
        queue_url: str,
        endpoint_url: str | None = None,
    ) -> None:
        if not queue_url:
            raise ValueError(
                "SQSMessageConsumer requires a non-empty queue_url. The matching "
                "SQS_*_QUEUE_URL env var is unset — sync your .env against .env.example."
            )
        self._session = session
        self._queue_url = queue_url
        self._endpoint_url = endpoint_url
        self._sqs: Any = None
        self._ctx: Any = None

    async def __aenter__(self) -> "SQSMessageConsumer":
        kwargs: dict[str, Any] = {}
        if self._endpoint_url:
            kwargs["endpoint_url"] = self._endpoint_url
        self._ctx = self._session.client("sqs", **kwargs)
        self._sqs = await self._ctx.__aenter__()
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self._ctx is not None:
            await self._ctx.__aexit__(exc_type, exc, tb)
            self._ctx = None
            self._sqs = None

    async def poll(self, max_messages: int, wait_seconds: int) -> list[SQSMessage]:
        response = await self._sqs.receive_message(
            QueueUrl=self._queue_url,
            MaxNumberOfMessages=max_messages,
            WaitTimeSeconds=wait_seconds,
        )
        return [SQSMessage(self._sqs, self._queue_url, raw) for raw in response.get("Messages", [])]
