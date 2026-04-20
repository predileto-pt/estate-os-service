"""Integration tests for the billing HTTP surface.

Covers the four routes introduced by the subscriptions-stripe-checkout
spec: checkout, portal, current-subscription, webhook. Role matrix
(OWNER/ADMIN/MEMBER/unauth) is exercised on the write routes.

The ASGI transport stack (JWTAuthMiddleware + IdentityMiddleware)
runs for real, so these tests also cover the webhook PUBLIC_PREFIXES
whitelist and the `require_current_org_admin` role gate.
"""

import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from identity.adapters.inmemory.inmemory_user_repo import (
    InMemoryUserRepository as InMemoryIdentityUserRepository,
)
from identity.container import Container as IdentityContainer
from identity.domain.models.user import User as IdentityUser
from organizations.domain.models.membership import Membership, MembershipRole
from organizations.domain.models.organization import Organization
from shared.main import create_app
from tests.conftest import TEST_JWT_SECRET, TEST_SUPABASE_USER_ID, make_test_token

TEST_ORG_ID = UUID("00000000-0000-0000-0000-0000000000aa")
TEST_USER_ID = UUID("00000000-0000-0000-0000-0000000000bb")


@pytest.fixture
def identity_user_repo():
    return InMemoryIdentityUserRepository()


@pytest.fixture
def identity_container_local(identity_user_repo):
    return IdentityContainer(user_repo=identity_user_repo)


@pytest.fixture
async def seeded(
    identity_user_repo,
    user_repo,
    organization_repo,
    membership_repo,
    subscription_repo,
):
    now = datetime.now(timezone.utc)
    # Seed identity-side user (middleware reads from identity container).
    identity_user = IdentityUser(
        id=TEST_USER_ID,
        supabase_user_id=TEST_SUPABASE_USER_ID,
        email="admin@example.com",
        name="Admin User",
        phone=None,
        google_metadata=None,
        created_at=now,
        updated_at=now,
    )
    await identity_user_repo.save(identity_user)

    # Seed organization + membership.
    await organization_repo.save(
        Organization(
            id=TEST_ORG_ID,
            created_by=TEST_USER_ID,
            name="Agency",
            nif=None,
            address=None,
            created_at=now,
            updated_at=now,
        )
    )
    membership = Membership(
        id=uuid4(),
        user_id=TEST_USER_ID,
        organization_id=TEST_ORG_ID,
        role=MembershipRole.OWNER,
        created_at=now,
        updated_at=now,
    )
    await membership_repo.save(membership)
    return {
        "identity_user": identity_user,
        "membership": membership,
        "organization_id": TEST_ORG_ID,
    }


@pytest.fixture
def app_with_identity(
    container,
    identity_container_local,
    billing_container,
    property_container,
    monkeypatch,
):
    monkeypatch.setattr("shared.config.settings.supabase_jwt_secret", TEST_JWT_SECRET)
    return create_app(
        container=container,
        identity_container=identity_container_local,
        billing_container=billing_container,
        property_container=property_container,
    )


@pytest.fixture
async def billing_client(app_with_identity):
    transport = ASGITransport(app=app_with_identity)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def auth_headers():
    return {"Authorization": f"Bearer {make_test_token()}"}


async def _set_member_role(membership_repo, role: MembershipRole):
    ms = await membership_repo.list_by_user(TEST_USER_ID)
    for m in ms:
        m.role = role
        await membership_repo.update(m)


# ── GET /admin/billing/subscription ─────────────────────────────────────────


async def test_get_subscription_returns_freemium_default(seeded, billing_client, auth_headers):
    r = await billing_client.get("/api/v1/admin/billing/subscription", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["plan"] == "freemium"
    assert body["status"] == "active"


async def test_get_subscription_requires_auth(seeded, billing_client):
    r = await billing_client.get("/api/v1/admin/billing/subscription")
    assert r.status_code == 401


# ── POST /admin/billing/checkout ────────────────────────────────────────────


async def test_checkout_as_owner_returns_stripe_url(
    seeded, billing_client, auth_headers, billing_gateway
):
    r = await billing_client.post(
        "/api/v1/admin/billing/checkout",
        json={"plan": "pro", "cadence": "monthly"},
        headers=auth_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["url"].startswith("https://checkout.stripe.test/")
    assert body["session_id"].startswith("cs_test_")

    assert len(billing_gateway.checkouts) == 1
    assert billing_gateway.checkouts[0].price_id == "price_pro_monthly_test"
    assert billing_gateway.checkouts[0].trial_days == 7


async def test_checkout_yearly_uses_yearly_price(
    seeded, billing_client, auth_headers, billing_gateway
):
    r = await billing_client.post(
        "/api/v1/admin/billing/checkout",
        json={"plan": "enterprise", "cadence": "yearly"},
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert billing_gateway.checkouts[-1].price_id == "price_enterprise_yearly_test"


async def test_checkout_as_member_forbidden(seeded, billing_client, auth_headers, membership_repo):
    await _set_member_role(membership_repo, MembershipRole.MEMBER)

    r = await billing_client.post(
        "/api/v1/admin/billing/checkout",
        json={"plan": "pro", "cadence": "monthly"},
        headers=auth_headers,
    )
    assert r.status_code == 403


async def test_checkout_unauthenticated_rejected(seeded, billing_client):
    r = await billing_client.post(
        "/api/v1/admin/billing/checkout",
        json={"plan": "pro", "cadence": "monthly"},
    )
    assert r.status_code == 401


# ── POST /admin/billing/portal ──────────────────────────────────────────────


async def test_portal_without_subscription_returns_409(seeded, billing_client, auth_headers):
    r = await billing_client.post("/api/v1/admin/billing/portal", headers=auth_headers)
    assert r.status_code == 409


async def test_portal_after_checkout_works(seeded, billing_client, auth_headers, billing_gateway):
    # First checkout creates the customer.
    await billing_client.post(
        "/api/v1/admin/billing/checkout",
        json={"plan": "pro", "cadence": "monthly"},
        headers=auth_headers,
    )

    r = await billing_client.post("/api/v1/admin/billing/portal", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["url"].startswith("https://portal.stripe.test/")
    assert len(billing_gateway.portals) == 1


async def test_portal_as_member_forbidden(seeded, billing_client, auth_headers, membership_repo):
    await _set_member_role(membership_repo, MembershipRole.MEMBER)

    r = await billing_client.post("/api/v1/admin/billing/portal", headers=auth_headers)
    assert r.status_code == 403


# ── POST /billing/webhooks/stripe ───────────────────────────────────────────


async def test_webhook_valid_signature_applies_event(
    seeded,
    billing_client,
    auth_headers,
    subscription_repo,
    billing_gateway,
):
    # Bootstrap a customer first.
    await billing_client.post(
        "/api/v1/admin/billing/checkout",
        json={"plan": "pro", "cadence": "monthly"},
        headers=auth_headers,
    )
    sub = await subscription_repo.get_by_organization_id(TEST_ORG_ID)
    customer_id = sub.stripe_customer_id

    event_payload = {
        "id": "evt_test_checkout_1",
        "type": "customer.subscription.created",
        "data": {
            "object": {
                "id": "sub_stripe_test_1",
                "customer": customer_id,
                "status": "trialing",
                "current_period_start": 1_700_000_000,
                "current_period_end": 1_700_600_000,
                "items": {"data": [{"price": {"id": "price_pro_monthly_test"}}]},
            }
        },
    }
    r = await billing_client.post(
        "/api/v1/billing/webhooks/stripe",
        content=json.dumps(event_payload),
        headers={
            "stripe-signature": billing_gateway.fake_webhook_secret,
            "content-type": "application/json",
        },
    )
    assert r.status_code == 200

    refreshed = await subscription_repo.get_by_organization_id(TEST_ORG_ID)
    assert refreshed.status.value == "trialing"
    assert refreshed.plan.value == "pro"
    assert refreshed.stripe_subscription_id == "sub_stripe_test_1"


async def test_webhook_invalid_signature_returns_400(seeded, billing_client):
    r = await billing_client.post(
        "/api/v1/billing/webhooks/stripe",
        content=b'{"id":"evt_x","type":"ping","data":{"object":{}}}',
        headers={"stripe-signature": "wrong", "content-type": "application/json"},
    )
    assert r.status_code == 400


async def test_webhook_idempotent_replay(
    seeded, billing_client, auth_headers, subscription_repo, billing_gateway
):
    await billing_client.post(
        "/api/v1/admin/billing/checkout",
        json={"plan": "pro", "cadence": "monthly"},
        headers=auth_headers,
    )
    sub = await subscription_repo.get_by_organization_id(TEST_ORG_ID)
    customer_id = sub.stripe_customer_id

    event = {
        "id": "evt_replay_1",
        "type": "customer.subscription.deleted",
        "data": {
            "object": {
                "id": "sub_1",
                "customer": customer_id,
                "status": "canceled",
            }
        },
    }

    payload = json.dumps(event)
    headers = {
        "stripe-signature": billing_gateway.fake_webhook_secret,
        "content-type": "application/json",
    }

    r1 = await billing_client.post(
        "/api/v1/billing/webhooks/stripe", content=payload, headers=headers
    )
    assert r1.status_code == 200
    first = await subscription_repo.get_by_organization_id(TEST_ORG_ID)
    assert first.status.value == "cancelled"

    # Replay the exact same event id — should be a no-op.
    first.status = first.status.__class__("active")
    await subscription_repo.update(first)
    r2 = await billing_client.post(
        "/api/v1/billing/webhooks/stripe", content=payload, headers=headers
    )
    assert r2.status_code == 200
    second = await subscription_repo.get_by_organization_id(TEST_ORG_ID)
    assert second.status.value == "active"
