"""LocalStack round-trip for `SQSCommandPublisher`.

Proves that a canonical `DomainEvent` makes it through the queue unchanged
(shape-wise) so downstream consumers receive the same envelope the publisher
sent. Complements the unit tests at `tests/unit/shared_events/test_sqs_message.py`
which test the wrapping/unwrapping of SNS-delivered messages.
"""

import json

import aioboto3

from shared.events.adapters.sqs_command_publisher import SQSCommandPublisher
from shared.events.base import DomainEvent
from shared.events.types import PROPERTY_EXTRACTION_REQUESTED_V1


async def test_send_and_receive(localstack_url, sqs_queue_url, sqs_client):
    session = aioboto3.Session(
        aws_access_key_id="test",
        aws_secret_access_key="test",
        region_name="us-east-1",
    )
    command_publisher = SQSCommandPublisher(session=session, endpoint_url=localstack_url)

    event = DomainEvent(
        event_type=PROPERTY_EXTRACTION_REQUESTED_V1,
        data={"job_id": "abc-123"},
    )
    await command_publisher.send(sqs_queue_url, event)

    response = sqs_client.receive_message(QueueUrl=sqs_queue_url, MaxNumberOfMessages=1)
    messages = response.get("Messages", [])
    assert len(messages) == 1

    body = json.loads(messages[0]["Body"])
    assert body["event_type"] == PROPERTY_EXTRACTION_REQUESTED_V1
    assert body["data"]["job_id"] == "abc-123"
    # Envelope carries the canonical fields too.
    assert "event_id" in body
    assert "occurred_at" in body


async def test_send_multiple_messages(localstack_url, sqs_queue_url, sqs_client):
    session = aioboto3.Session(
        aws_access_key_id="test",
        aws_secret_access_key="test",
        region_name="us-east-1",
    )
    command_publisher = SQSCommandPublisher(session=session, endpoint_url=localstack_url)

    for i in range(3):
        await command_publisher.send(
            sqs_queue_url,
            DomainEvent(
                event_type=PROPERTY_EXTRACTION_REQUESTED_V1,
                data={"job_id": f"job-{i}"},
            ),
        )

    received = []
    for _ in range(3):
        response = sqs_client.receive_message(QueueUrl=sqs_queue_url, MaxNumberOfMessages=10)
        received.extend(response.get("Messages", []))

    assert len(received) >= 3
