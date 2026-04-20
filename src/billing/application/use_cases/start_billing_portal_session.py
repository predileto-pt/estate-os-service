from uuid import UUID

import structlog

from billing.application.ports.billing_gateway import BillingGateway
from billing.application.ports.repositories.subscription_repository import (
    SubscriptionRepository,
)
from billing.domain.exceptions import BillingCustomerMissingError

log = structlog.get_logger()


class StartBillingPortalSession:
    def __init__(
        self,
        *,
        subscription_repo: SubscriptionRepository,
        billing_gateway: BillingGateway,
        portal_return_url: str,
    ) -> None:
        self._subscriptions = subscription_repo
        self._gateway = billing_gateway
        self._return_url = portal_return_url

    async def execute(self, *, organization_id: UUID) -> str:
        subscription = await self._subscriptions.get_by_organization_id(organization_id)
        if subscription is None or not subscription.stripe_customer_id:
            raise BillingCustomerMissingError()

        url = await self._gateway.create_portal_session(
            customer_id=subscription.stripe_customer_id,
            return_url=self._return_url,
        )
        log.info(
            "billing_portal_session_started",
            organization_id=str(organization_id),
        )
        return url
