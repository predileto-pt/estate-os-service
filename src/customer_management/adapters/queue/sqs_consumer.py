import json
from typing import Any

import aioboto3


class SQSMessageConsumer:
    def __init__(self, session: aioboto3.Session, endpoint_url: str | None = None) -> None:
        self._session = session
        self._endpoint_url = endpoint_url

    def _client_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {}
        if self._endpoint_url:
            kwargs["endpoint_url"] = self._endpoint_url
        return kwargs

    async def poll(self, queue_url: str, max_messages: int = 1) -> list[dict[str, Any]]:
        async with self._session.client("sqs", **self._client_kwargs()) as sqs:
            response = await sqs.receive_message(
                QueueUrl=queue_url,
                MaxNumberOfMessages=max_messages,
                WaitTimeSeconds=20,
            )
            messages = response.get("Messages", [])
            return [
                {
                    "body": json.loads(msg["Body"]),
                    "receipt_handle": msg["ReceiptHandle"],
                }
                for msg in messages
            ]

    async def delete_message(self, queue_url: str, receipt_handle: str) -> None:
        async with self._session.client("sqs", **self._client_kwargs()) as sqs:
            await sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt_handle)
