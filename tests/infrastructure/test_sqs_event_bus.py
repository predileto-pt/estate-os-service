import json

from properties.adapters.queue.sqs_event_bus import SQSEventBus
from shared.events.base import DomainEvent
from shared.events.types import PROPERTY_EXTRACTION_REQUESTED_V1


async def test_publish_and_receive(localstack_url, sqs_queue_url, sqs_client):
    event_bus = SQSEventBus(
        queue_url=sqs_queue_url,
        region="us-east-1",
        endpoint_url=localstack_url,
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )

    event = DomainEvent(
        event_type=PROPERTY_EXTRACTION_REQUESTED_V1,
        data={"job_id": "abc-123"},
    )
    await event_bus.publish(event)

    response = sqs_client.receive_message(QueueUrl=sqs_queue_url, MaxNumberOfMessages=1)
    messages = response.get("Messages", [])
    assert len(messages) == 1

    body = json.loads(messages[0]["Body"])
    assert body["event_type"] == PROPERTY_EXTRACTION_REQUESTED_V1
    assert body["data"]["job_id"] == "abc-123"


async def test_publish_multiple_messages(localstack_url, sqs_queue_url, sqs_client):
    event_bus = SQSEventBus(
        queue_url=sqs_queue_url,
        region="us-east-1",
        endpoint_url=localstack_url,
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )

    for i in range(3):
        await event_bus.publish(
            DomainEvent(
                event_type=PROPERTY_EXTRACTION_REQUESTED_V1,
                data={"job_id": f"job-{i}"},
            )
        )

    received = []
    for _ in range(3):
        response = sqs_client.receive_message(QueueUrl=sqs_queue_url, MaxNumberOfMessages=10)
        received.extend(response.get("Messages", []))

    assert len(received) >= 3
