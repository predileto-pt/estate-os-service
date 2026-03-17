import json

from property_management.adapters.queue.sqs_event_bus import SQSEventBus


async def test_publish_and_receive(localstack_url, sqs_queue_url, sqs_client):
    event_bus = SQSEventBus(
        queue_url=sqs_queue_url,
        region="us-east-1",
        endpoint_url=localstack_url,
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )

    message = {"event_type": "extraction.submitted", "job_id": "abc-123"}
    await event_bus.publish(message)

    response = sqs_client.receive_message(QueueUrl=sqs_queue_url, MaxNumberOfMessages=1)
    messages = response.get("Messages", [])
    assert len(messages) == 1

    body = json.loads(messages[0]["Body"])
    assert body["event_type"] == "extraction.submitted"
    assert body["job_id"] == "abc-123"


async def test_publish_multiple_messages(localstack_url, sqs_queue_url, sqs_client):
    event_bus = SQSEventBus(
        queue_url=sqs_queue_url,
        region="us-east-1",
        endpoint_url=localstack_url,
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )

    for i in range(3):
        await event_bus.publish({"event_type": "test.event", "index": i})

    received = []
    for _ in range(3):
        response = sqs_client.receive_message(QueueUrl=sqs_queue_url, MaxNumberOfMessages=10)
        received.extend(response.get("Messages", []))

    assert len(received) >= 3
