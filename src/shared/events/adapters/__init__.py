"""Transport adapters for the event-bus ports.

Outbound:
- `RabbitMQEventPublisher` — fan-out via topic exchange `domain-events`.
- `RabbitMQCommandPublisher` — point-to-point via default exchange.
- `SNSEventPublisher` / `SQSCommandPublisher` — dormant; retained for
  emergency revert (see ADR-008 addendum 2026-05-13).

Inbound:
- `RabbitMQMessageConsumer` — quorum-queue consumer with internal asyncio
  buffer bridging RabbitMQ's push model to the `MessageConsumer.poll()`
  pull contract.
- `SQSMessageConsumer` — dormant counterpart.

Test doubles:
- `InMemoryEventBus` — fan-out + queue for unit tests; no broker required.

Reliability helpers:
- `_publish_retry.publish_with_retry` wraps both RabbitMQ publishers with
  a bounded retry over transient AMQP failures (reconnect windows) and
  emits structured `event_publish_attempt_failed` / `event_publish_failed`
  logs. See ADR-008 addendum 2026-05-16 for the full contract.
"""
