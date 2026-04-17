"""SQSMessage envelope unwrapping.

Covers both payload shapes the SQS consumer encounters:
  1. Messages delivered via SNS→SQS subscription — SNS wraps the payload.
  2. Messages delivered directly via `SQSCommandPublisher.send` — the body
     IS the DomainEvent JSON, no wrapper.
"""

import json

from shared.events.adapters.sqs_message_consumer import SQSMessage


class _FakeSQS:
    def __init__(self) -> None:
        self.delete_calls: list[dict] = []
        self.visibility_calls: list[dict] = []

    async def delete_message(self, *, QueueUrl: str, ReceiptHandle: str) -> None:
        self.delete_calls.append({"QueueUrl": QueueUrl, "ReceiptHandle": ReceiptHandle})

    async def change_message_visibility(
        self, *, QueueUrl: str, ReceiptHandle: str, VisibilityTimeout: int
    ) -> None:
        self.visibility_calls.append(
            {
                "QueueUrl": QueueUrl,
                "ReceiptHandle": ReceiptHandle,
                "VisibilityTimeout": VisibilityTimeout,
            }
        )


def _domain_event_json(event_type: str) -> str:
    return json.dumps(
        {
            "event_type": event_type,
            "event_id": "evt-1",
            "occurred_at": "2026-04-17T12:00:00+00:00",
            "data": {"applicant_id": "abc"},
        }
    )


class TestSQSMessageUnwrapsSNSEnvelope:
    async def test_unwraps_sns_delivered_payload(self) -> None:
        # SNS→SQS delivery: body is a wrapping dict with `Message` field.
        sns_wrapped = {
            "Type": "Notification",
            "MessageId": "sns-1",
            "TopicArn": "arn:aws:sns:eu-west-1:123:domain-events-APPLICANT_SCREENED-v1",
            "Message": _domain_event_json("APPLICANT_SCREENED.v1"),
        }
        raw = {
            "Body": json.dumps(sns_wrapped),
            "MessageId": "sqs-msg-1",
            "ReceiptHandle": "rh-1",
        }
        msg = SQSMessage(_FakeSQS(), "queue-url", raw)

        assert msg.event.event_type == "APPLICANT_SCREENED.v1"
        assert msg.event.event_id == "evt-1"
        assert msg.event.data == {"applicant_id": "abc"}
        assert msg.message_id == "sqs-msg-1"

    async def test_passes_through_direct_command_payload(self) -> None:
        # SQSCommandPublisher.send path: body IS the DomainEvent JSON already.
        raw = {
            "Body": _domain_event_json("APPLICANT_EXTRACTION_REQUESTED.v1"),
            "MessageId": "sqs-msg-2",
            "ReceiptHandle": "rh-2",
        }
        msg = SQSMessage(_FakeSQS(), "queue-url", raw)

        assert msg.event.event_type == "APPLICANT_EXTRACTION_REQUESTED.v1"
        assert msg.event.data == {"applicant_id": "abc"}


class TestSQSMessageAckNackHeartbeat:
    async def test_ack_deletes_message(self) -> None:
        sqs = _FakeSQS()
        raw = {
            "Body": _domain_event_json("X.v1"),
            "MessageId": "m",
            "ReceiptHandle": "rh",
        }
        msg = SQSMessage(sqs, "q", raw)

        await msg.ack()

        assert sqs.delete_calls == [{"QueueUrl": "q", "ReceiptHandle": "rh"}]

    async def test_nack_is_noop(self) -> None:
        sqs = _FakeSQS()
        raw = {
            "Body": _domain_event_json("X.v1"),
            "MessageId": "m",
            "ReceiptHandle": "rh",
        }
        msg = SQSMessage(sqs, "q", raw)

        await msg.nack()

        # nack on SQS is a no-op — visibility timeout expires, SQS redelivers.
        assert sqs.delete_calls == []
        assert sqs.visibility_calls == []

    async def test_extend_visibility_calls_change_message_visibility(self) -> None:
        sqs = _FakeSQS()
        raw = {
            "Body": _domain_event_json("X.v1"),
            "MessageId": "m",
            "ReceiptHandle": "rh",
        }
        msg = SQSMessage(sqs, "q", raw)

        await msg.extend_visibility(120)

        assert sqs.visibility_calls == [
            {"QueueUrl": "q", "ReceiptHandle": "rh", "VisibilityTimeout": 120}
        ]
