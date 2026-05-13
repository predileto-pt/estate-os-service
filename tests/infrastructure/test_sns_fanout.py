"""SNS fan-out + handler isolation — LocalStack integration.

Two acceptance criteria from the foundation spec:

1. **Cross-context fan-out**: one `SNSEventPublisher.publish(event)` call
   produces one message in each of two subscribed SQS queues.
2. **Handler isolation**: the same event lands in two queues. One queue's
   worker raises on every message; the other succeeds. After redrive,
   the failing queue's message is in its DLQ; the succeeding queue is
   unaffected.

These tests provision SNS topics + SQS queues + DLQs + SNS→SQS
subscriptions at test-setup time, mirroring the production IaC shape
documented in scripts/localstack-init.sh.
"""

import asyncio
import json
from typing import Any

import aioboto3
import pytest

from shared.events.adapters.sns_event_publisher import SNSEventPublisher
from shared.events.adapters.sqs_message_consumer import SQSMessageConsumer
from shared.events.base import DomainEvent
from shared.events.router import EventRouter
from shared.events.worker import EventBusWorker

TOPIC_SUFFIX = "PROPERTY_CREATED-v1"
EVENT_TYPE = "PROPERTY_CREATED.v1"


def _create_topic(sns_client, name: str) -> str:
    response = sns_client.create_topic(Name=name)
    return response["TopicArn"]


def _create_queue_with_redrive(sqs_client, name: str, dlq_name: str) -> tuple[str, str, str]:
    dlq_resp = sqs_client.create_queue(QueueName=dlq_name)
    dlq_url = dlq_resp["QueueUrl"]
    dlq_attrs = sqs_client.get_queue_attributes(QueueUrl=dlq_url, AttributeNames=["QueueArn"])
    dlq_arn = dlq_attrs["Attributes"]["QueueArn"]

    redrive = {"deadLetterTargetArn": dlq_arn, "maxReceiveCount": "2"}
    queue_resp = sqs_client.create_queue(
        QueueName=name,
        Attributes={
            "VisibilityTimeout": "1",  # short so redelivery is fast in tests
            "RedrivePolicy": json.dumps(redrive),
        },
    )
    queue_url = queue_resp["QueueUrl"]
    queue_attrs = sqs_client.get_queue_attributes(QueueUrl=queue_url, AttributeNames=["QueueArn"])
    queue_arn = queue_attrs["Attributes"]["QueueArn"]
    return queue_url, queue_arn, dlq_url


def _subscribe_sqs_to_sns(sns_client, topic_arn: str, queue_arn: str) -> None:
    sns_client.subscribe(TopicArn=topic_arn, Protocol="sqs", Endpoint=queue_arn)


@pytest.fixture
def sns_client(localstack_url, aws_credentials):
    import boto3

    return boto3.client("sns", endpoint_url=localstack_url, **aws_credentials)


async def _run_worker_until(
    worker: EventBusWorker, condition, max_iterations: int = 20, iteration_sleep: float = 0.2
) -> None:
    """Run the worker in the background until `condition()` returns True or we give up.

    The worker's `run()` loop blocks on long-polls, so we drive it via short-poll
    mode (`wait_seconds=0`) + a timeout iteration cap to avoid indefinite blocks
    when the test's expected side-effect never materializes.
    """
    task = asyncio.create_task(worker.run())
    try:
        for _ in range(max_iterations):
            if condition():
                break
            await asyncio.sleep(iteration_sleep)
    finally:
        worker._running = False  # noqa: SLF001
        try:
            await asyncio.wait_for(task, timeout=5)
        except TimeoutError:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


async def test_fanout_one_publish_two_queues(
    localstack_url, aws_credentials, sns_client, sqs_client
):
    """A single SNS publish lands on both subscribed queues."""
    topic_arn = _create_topic(sns_client, f"domain-events-{TOPIC_SUFFIX}")
    q_a_url, q_a_arn, _ = _create_queue_with_redrive(
        sqs_client, "fanout-test-a", "fanout-test-a-dlq"
    )
    q_b_url, q_b_arn, _ = _create_queue_with_redrive(
        sqs_client, "fanout-test-b", "fanout-test-b-dlq"
    )
    _subscribe_sqs_to_sns(sns_client, topic_arn, q_a_arn)
    _subscribe_sqs_to_sns(sns_client, topic_arn, q_b_arn)

    topic_arn_prefix = topic_arn[: -len(TOPIC_SUFFIX)]

    session = aioboto3.Session(**aws_credentials)
    publisher = SNSEventPublisher(
        session=session,
        topic_arn_prefix=topic_arn_prefix,
        endpoint_url=localstack_url,
    )
    await publisher.publish(DomainEvent(event_type=EVENT_TYPE, data={"property_id": "p-1"}))

    # Poll each queue independently — SNS delivery is async, give it a beat.
    async def _wait_for_message(queue_url: str) -> dict[str, Any]:
        for _ in range(30):
            resp = sqs_client.receive_message(
                QueueUrl=queue_url, MaxNumberOfMessages=1, WaitTimeSeconds=0
            )
            msgs = resp.get("Messages", [])
            if msgs:
                return msgs[0]
            await asyncio.sleep(0.2)
        raise AssertionError(f"no message on {queue_url}")

    msg_a = await _wait_for_message(q_a_url)
    msg_b = await _wait_for_message(q_b_url)

    # Both messages wrap the same published DomainEvent.
    body_a = json.loads(msg_a["Body"])
    body_b = json.loads(msg_b["Body"])
    event_a = json.loads(body_a["Message"])
    event_b = json.loads(body_b["Message"])

    assert event_a["event_type"] == EVENT_TYPE
    assert event_a["data"]["property_id"] == "p-1"
    assert event_b["event_type"] == EVENT_TYPE
    assert event_b["data"]["property_id"] == "p-1"
    assert event_a["event_id"] == event_b["event_id"]


async def test_handler_isolation_failing_queue_dlqs_succeeding_queue_unaffected(
    localstack_url, aws_credentials, sns_client, sqs_client
):
    """One queue fails; its message goes to DLQ. Other queue succeeds cleanly."""
    topic_arn = _create_topic(sns_client, f"domain-events-{TOPIC_SUFFIX}")
    fail_q_url, fail_q_arn, fail_dlq_url = _create_queue_with_redrive(
        sqs_client, "iso-fail", "iso-fail-dlq"
    )
    ok_q_url, ok_q_arn, ok_dlq_url = _create_queue_with_redrive(sqs_client, "iso-ok", "iso-ok-dlq")
    _subscribe_sqs_to_sns(sns_client, topic_arn, fail_q_arn)
    _subscribe_sqs_to_sns(sns_client, topic_arn, ok_q_arn)

    topic_arn_prefix = topic_arn[: -len(TOPIC_SUFFIX)]

    session = aioboto3.Session(**aws_credentials)
    publisher = SNSEventPublisher(
        session=session, topic_arn_prefix=topic_arn_prefix, endpoint_url=localstack_url
    )
    await publisher.publish(DomainEvent(event_type=EVENT_TYPE, data={"property_id": "p-iso"}))

    # Worker A: raises on every message. After maxReceiveCount=2, the message
    # should land in fail-dlq.
    failing_router = EventRouter()

    async def always_fails(event: DomainEvent, ctx) -> None:
        raise RuntimeError("intentional failure")

    failing_router.on(EVENT_TYPE, always_fails)

    failing_worker = EventBusWorker(
        consumer=SQSMessageConsumer(
            session=session, queue_url=fail_q_url, endpoint_url=localstack_url
        ),
        router=failing_router,
        context={},
        worker_name="failing_worker",
        use_heartbeat=False,
        max_concurrency=1,
        max_messages_per_poll=1,
        wait_seconds=0,
    )

    # Worker B: succeeds on every message.
    success_received: list[DomainEvent] = []
    ok_router = EventRouter()

    async def succeeds(event: DomainEvent, ctx) -> None:
        success_received.append(event)

    ok_router.on(EVENT_TYPE, succeeds)

    ok_worker = EventBusWorker(
        consumer=SQSMessageConsumer(
            session=session, queue_url=ok_q_url, endpoint_url=localstack_url
        ),
        router=ok_router,
        context={},
        worker_name="ok_worker",
        use_heartbeat=False,
        max_concurrency=1,
        max_messages_per_poll=1,
        wait_seconds=0,
    )

    # Run both workers in parallel. Stop when both terminal states are observed:
    # success_received has 1 event AND fail-dlq has 1 message.
    def _fail_dlq_has_message() -> bool:
        resp = sqs_client.get_queue_attributes(
            QueueUrl=fail_dlq_url,
            AttributeNames=["ApproximateNumberOfMessages"],
        )
        return int(resp["Attributes"]["ApproximateNumberOfMessages"]) > 0

    def _both_done() -> bool:
        return len(success_received) >= 1 and _fail_dlq_has_message()

    # Coordinated shutdown after both workers observe their terminal state.
    async def _shared_watcher():
        for _ in range(60):
            if _both_done():
                break
            await asyncio.sleep(0.2)
        failing_worker._running = False  # noqa: SLF001
        ok_worker._running = False  # noqa: SLF001

    await asyncio.gather(
        failing_worker.run(),
        ok_worker.run(),
        _shared_watcher(),
        return_exceptions=True,
    )

    # Success queue ack'd: handler received exactly one event.
    assert len(success_received) == 1
    assert success_received[0].data["property_id"] == "p-iso"

    # Success queue's DLQ is empty.
    ok_dlq_depth = sqs_client.get_queue_attributes(
        QueueUrl=ok_dlq_url, AttributeNames=["ApproximateNumberOfMessages"]
    )["Attributes"]["ApproximateNumberOfMessages"]
    assert int(ok_dlq_depth) == 0

    # Failing queue's DLQ has the poison message.
    assert _fail_dlq_has_message()
