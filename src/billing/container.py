"""Billing bounded context container.

Owns `Subscription` and all Stripe integration surface — Checkout,
Customer Portal, webhook idempotency, price catalog.

Exposes one callable-Protocol binding for cross-context consumption by
`organizations` — `seed_freemium_subscription_port` — which
`RegisterAdminAccount` calls during compound admin-registration to
create the default Subscription row for a new Organization.

Mirrors `identity.container.Container.register_user_port` in shape: the
port is a bound method on a use case instance, duck-typing to the
Protocol. No adapter class in between.
"""

from billing.application.ports.billing_gateway import BillingGateway
from billing.application.ports.repositories.stripe_webhook_events_repository import (
    StripeWebhookEventsRepository,
)
from billing.application.ports.repositories.subscription_repository import (
    SubscriptionRepository,
)
from billing.application.use_cases.handle_stripe_webhook import HandleStripeWebhookEvent
from billing.application.use_cases.price_catalog import PriceCatalog
from billing.application.use_cases.seed_freemium_subscription import (
    SeedFreemiumSubscriptionUseCase,
)
from billing.application.use_cases.start_billing_portal_session import (
    StartBillingPortalSession,
)
from billing.application.use_cases.start_checkout_session import StartCheckoutSession


class Container:
    def __init__(
        self,
        *,
        subscription_repo: SubscriptionRepository,
        billing_gateway: BillingGateway,
        stripe_webhook_events_repo: StripeWebhookEventsRepository,
        price_catalog: PriceCatalog,
        trial_period_days: int,
        checkout_success_url: str,
        checkout_cancel_url: str,
        portal_return_url: str,
    ) -> None:
        self.subscription_repo = subscription_repo
        self.billing_gateway = billing_gateway
        self.stripe_webhook_events_repo = stripe_webhook_events_repo
        self.price_catalog = price_catalog

        self.seed_freemium_subscription = SeedFreemiumSubscriptionUseCase(
            subscription_repo=subscription_repo,
        )
        self.start_checkout_session = StartCheckoutSession(
            subscription_repo=subscription_repo,
            billing_gateway=billing_gateway,
            price_catalog=price_catalog,
            trial_period_days=trial_period_days,
            checkout_success_url=checkout_success_url,
            checkout_cancel_url=checkout_cancel_url,
        )
        self.start_billing_portal_session = StartBillingPortalSession(
            subscription_repo=subscription_repo,
            billing_gateway=billing_gateway,
            portal_return_url=portal_return_url,
        )
        self.handle_stripe_webhook = HandleStripeWebhookEvent(
            subscription_repo=subscription_repo,
            webhook_events_repo=stripe_webhook_events_repo,
            price_catalog=price_catalog,
        )

    @property
    def seed_freemium_subscription_port(self):
        """Bound callable satisfying the `SeedFreemiumSubscription` Protocol.

        Injected into `organizations.container.Container` at composition time
        so `RegisterAdminAccount` can seed the default Subscription without
        importing billing internals.
        """
        return self.seed_freemium_subscription.__call__
