"""Lambda handler factory — payload shapes, raise-on-failure, batch invariants.

The factory wraps an `EventRouter` so the same handler registration code
that powers `SQSWorker` drives an AWS Lambda invocation. Verifies:

- Raw-SQS body shape (SNS raw_message_delivery=true) → dispatched.
- SNS-envelope body shape → unwrapped and dispatched.
- Handler exception → propagated (lets SQS redrive).
- Event shape validation — empty/missing Records, batch > 1.
"""

import json

import pytest

from shared.events.base import DomainEvent
from shared.events.lambda_handler import make_handler
from shared.events.router import EventRouter


class _DummyContainer:
    pass


async def _build_context() -> _DummyContainer:
    return _DummyContainer()


def _sqs_record(body: str, message_id: str = "msg-1") -> dict:
    return {"body": body, "messageId": message_id}


def _domain_event_payload(event_type: str = "PROPERTY_UPDATED.v1") -> dict:
    return {
        "event_type": event_type,
        "event_id": "evt-1",
        "occurred_at": "2026-04-17T12:00:00+00:00",
        "data": {"property_id": "abc"},
    }


class TestRawSQSPayload:
    def test_dispatches_raw_domain_event(self) -> None:
        calls: list[DomainEvent] = []

        async def handler(event: DomainEvent, context: _DummyContainer) -> None:
            calls.append(event)

        router = EventRouter()
        router.on("PROPERTY_UPDATED.v1", handler)
        lambda_handler = make_handler(router, _build_context)

        record = _sqs_record(json.dumps(_domain_event_payload()))
        lambda_handler({"Records": [record]}, None)

        assert len(calls) == 1
        assert calls[0].event_type == "PROPERTY_UPDATED.v1"
        assert calls[0].data == {"property_id": "abc"}


class TestSNSEnvelopePayload:
    def test_unwraps_sns_envelope(self) -> None:
        calls: list[DomainEvent] = []

        async def handler(event: DomainEvent, context: _DummyContainer) -> None:
            calls.append(event)

        router = EventRouter()
        router.on("PROPERTY_UPDATED.v1", handler)
        lambda_handler = make_handler(router, _build_context)

        # SNS→SQS without raw_message_delivery: body wraps the DomainEvent
        # JSON in a `Message` field along with SNS metadata.
        envelope = {
            "Type": "Notification",
            "MessageId": "sns-1",
            "TopicArn": "arn:aws:sns:eu-west-3:123:topic",
            "Message": json.dumps(_domain_event_payload()),
        }
        record = _sqs_record(json.dumps(envelope))
        lambda_handler({"Records": [record]}, None)

        assert len(calls) == 1
        assert calls[0].event_type == "PROPERTY_UPDATED.v1"


class TestHandlerExceptionPropagates:
    def test_handler_raise_bubbles_up(self) -> None:
        async def failing(event: DomainEvent, context: _DummyContainer) -> None:
            raise RuntimeError("handler boom")

        router = EventRouter()
        router.on("PROPERTY_UPDATED.v1", failing)
        lambda_handler = make_handler(router, _build_context)

        record = _sqs_record(json.dumps(_domain_event_payload()))
        with pytest.raises(RuntimeError, match="handler boom"):
            lambda_handler({"Records": [record]}, None)


class TestEventShapeValidation:
    def test_missing_records_raises(self) -> None:
        router = EventRouter()
        lambda_handler = make_handler(router, _build_context)

        with pytest.raises(ValueError, match="SQS records"):
            lambda_handler({}, None)

    def test_empty_records_raises(self) -> None:
        router = EventRouter()
        lambda_handler = make_handler(router, _build_context)

        with pytest.raises(ValueError, match="SQS records"):
            lambda_handler({"Records": []}, None)

    def test_batch_greater_than_one_raises(self) -> None:
        router = EventRouter()
        lambda_handler = make_handler(router, _build_context)

        record = _sqs_record(json.dumps(_domain_event_payload()))
        with pytest.raises(ValueError, match="batch_size"):
            lambda_handler({"Records": [record, record]}, None)

    def test_non_dict_event_raises(self) -> None:
        router = EventRouter()
        lambda_handler = make_handler(router, _build_context)

        with pytest.raises(ValueError, match="SQS records"):
            lambda_handler([], None)


class TestUnknownEventType:
    def test_unknown_event_does_not_raise(self) -> None:
        # EventRouter logs a warning for unknown event types but does not
        # raise — Lambda invocation succeeds, SQS deletes the message.
        router = EventRouter()
        lambda_handler = make_handler(router, _build_context)

        record = _sqs_record(json.dumps(_domain_event_payload("UNKNOWN.v1")))
        lambda_handler({"Records": [record]}, None)
