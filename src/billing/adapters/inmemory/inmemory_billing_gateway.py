"""In-memory billing gateway for tests.

Records every call for assertion. Generates deterministic fake ids and
URLs. Webhook verification checks a fake signature format so tests can
simulate both valid and invalid signatures.
"""

from dataclasses import dataclass, field
from uuid import UUID

from billing.application.ports.billing_gateway import (
    BillingGateway,
    CheckoutSession,
    SignatureVerificationError,
    StripeEventData,
)


@dataclass
class CreateCustomerCall:
    org_id: UUID
    email: str
    name: str


@dataclass
class CreateCheckoutCall:
    customer_id: str
    price_id: str
    success_url: str
    cancel_url: str
    trial_days: int


@dataclass
class CreatePortalCall:
    customer_id: str
    return_url: str


@dataclass
class InMemoryBillingGateway(BillingGateway):
    fake_webhook_secret: str = "whsec_test"
    customers: list[CreateCustomerCall] = field(default_factory=list)
    checkouts: list[CreateCheckoutCall] = field(default_factory=list)
    portals: list[CreatePortalCall] = field(default_factory=list)
    # Canned subscription objects keyed by id, returned by `get_subscription`.
    # Tests populate this to drive `checkout.session.completed` provisioning.
    subscriptions: dict[str, dict] = field(default_factory=dict)
    _next_customer: int = 0
    _next_session: int = 0

    async def create_customer(self, *, org_id: UUID, email: str, name: str) -> str:
        self.customers.append(CreateCustomerCall(org_id, email, name))
        self._next_customer += 1
        return f"cus_test_{self._next_customer:04d}"

    async def create_checkout_session(
        self,
        *,
        customer_id: str,
        price_id: str,
        success_url: str,
        cancel_url: str,
        trial_days: int,
    ) -> CheckoutSession:
        self.checkouts.append(
            CreateCheckoutCall(customer_id, price_id, success_url, cancel_url, trial_days)
        )
        self._next_session += 1
        sid = f"cs_test_{self._next_session:04d}"
        return CheckoutSession(id=sid, url=f"https://checkout.stripe.test/{sid}")

    async def create_portal_session(self, *, customer_id: str, return_url: str) -> str:
        self.portals.append(CreatePortalCall(customer_id, return_url))
        self._next_session += 1
        return f"https://portal.stripe.test/ps_test_{self._next_session:04d}"

    async def get_subscription(self, *, subscription_id: str) -> dict:
        # Return the canned object if the test seeded one; otherwise a
        # minimal active subscription carrying just the id.
        return self.subscriptions.get(
            subscription_id, {"id": subscription_id, "status": "active"}
        )

    def verify_webhook(self, *, payload: bytes, signature: str) -> StripeEventData:
        # Tests set `signature` to the literal fake secret on valid
        # payloads, or anything else to simulate an invalid signature.
        if signature != self.fake_webhook_secret:
            raise SignatureVerificationError("invalid signature (test double)")

        import json

        event = json.loads(payload)
        return StripeEventData(
            id=event["id"],
            type=event["type"],
            data_object=event["data"]["object"],
            raw_payload=event,
        )
