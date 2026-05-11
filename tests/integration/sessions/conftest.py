"""Test fixtures for the session endpoints — in-memory repo + stub validator."""

from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from sessions.adapters.inmemory.portal_token_validator import StubPortalTokenValidator
from sessions.adapters.inmemory.repository import InMemorySessionRepository
from sessions.adapters.signing.hmac_cookie_signer import HmacCookieSigner
from sessions.application.ports.validate_portal_auth_token import ValidatedPortalIdentity
from sessions.container import SessionsContainer
from shared.main import create_app


PORTAL_USER_ID = UUID("00000000-0000-0000-0000-000000000aaa")
VALID_TOKEN = "valid-portal-token"


@pytest.fixture
def session_repository():
    return InMemorySessionRepository()


@pytest.fixture
def cookie_signer():
    return HmacCookieSigner(active_key_version=1, keys={1: b"test-key-do-not-use-in-prod"})


@pytest.fixture
def portal_token_validator():
    validator = StubPortalTokenValidator()
    validator.register(
        VALID_TOKEN,
        ValidatedPortalIdentity(user_id=PORTAL_USER_ID, email="portal@example.com"),
    )
    return validator


@pytest.fixture
def sessions_container(session_repository, cookie_signer, portal_token_validator):
    return SessionsContainer(
        session_repository=session_repository,
        cookie_signer=cookie_signer,
        portal_token_validator=portal_token_validator,
        favorites_cap=500,
        prefs_max_bytes=8192,
        last_seen_debounce_seconds=0,  # always refresh in tests for determinism
        anonymous_ttl_days=90,
        cookie_domain="",
        cookie_secure=False,
        cookie_max_age_seconds=31_536_000,
    )


@pytest.fixture
def session_app(sessions_container, monkeypatch):
    """Minimal app: only the session container injected; other containers
    are wired by the default `create_app` lifespan path, which would try to
    contact Supabase. We monkeypatch so the app boots without external services.
    """
    # The full app lifespan tries to reach out to Supabase / S3 / etc. For
    # session integration tests we want a fresh app with **just** the
    # container injected via the kwargs path. The lifespan still runs but
    # short-circuits because `app.state.container` is already set.
    from organizations.container import Container as OrgContainer

    monkeypatch.setattr("shared.config.settings.supabase_jwt_secret", "test-admin-secret")

    # Stand up a placeholder organizations container so `app.state.container`
    # is truthy and the lifespan's "if not set" branch short-circuits.
    placeholder = OrgContainer.__new__(OrgContainer)
    app = create_app(container=placeholder, sessions_container=sessions_container)
    return app


@pytest.fixture
async def client(session_app):
    transport = ASGITransport(app=session_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def fresh_property_id():
    return uuid4()
