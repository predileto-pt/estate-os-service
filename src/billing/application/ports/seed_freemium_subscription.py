"""Callable Protocol — the one cross-context port billing exposes.

Consumed by `organizations.RegisterAdminAccount` so the compound
registration flow (create Org + OwnerMembership + Subscription) can
seed the default freemium Subscription without importing any billing
internals. Mirrors the `identity.RegisterUserPort` pattern.

The concrete implementation lives at
`billing.application.use_cases.seed_freemium_subscription.SeedFreemiumSubscriptionUseCase`
and is bound to the port by `billing.container.Container.seed_freemium_subscription_port`.
"""

from typing import Protocol
from uuid import UUID

from billing.domain.models.subscription import Subscription


class SeedFreemiumSubscription(Protocol):
    async def __call__(self, *, organization_id: UUID) -> Subscription: ...
