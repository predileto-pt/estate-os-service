"""Sessions container — composition root for the bounded context.

Constructs the repository internally from a session maker (mirrors
identity_container's pattern). Cross-context dependencies enter via the
constructor: cookie signer, portal token validator, clock.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sessions.adapters.database.repository import SqlAlchemySessionRepository
from sessions.application.ports.clock import Clock, SystemClock
from sessions.application.ports.cookie_signer import CookieSigner
from sessions.application.ports.session_repository import SessionRepository
from sessions.application.ports.validate_portal_auth_token import (
    ValidatePortalAuthToken,
)
from sessions.application.use_cases.claim_session import ClaimSession
from sessions.application.use_cases.get_session_view import GetSessionView
from sessions.application.use_cases.init_session import InitSession
from sessions.application.use_cases.logout_session import LogoutSession
from sessions.application.use_cases.prune_stale_anonymous_sessions import (
    PruneStaleAnonymousSessions,
)
from sessions.application.use_cases.update_session_slice import UpdateSessionSlice


class SessionsContainer:
    def __init__(
        self,
        *,
        cookie_signer: CookieSigner,
        portal_token_validator: ValidatePortalAuthToken,
        # Either a session maker (production) or a pre-built repository (tests).
        session_maker: async_sessionmaker[AsyncSession] | None = None,
        session_repository: SessionRepository | None = None,
        clock: Clock | None = None,
        favorites_cap: int = 500,
        prefs_max_bytes: int = 8192,
        last_seen_debounce_seconds: int = 60,
        anonymous_ttl_days: int = 90,
        cookie_domain: str = "",
        cookie_secure: bool = True,
        cookie_max_age_seconds: int = 31_536_000,
    ) -> None:
        if session_repository is None:
            if session_maker is None:
                raise ValueError(
                    "SessionsContainer requires either session_maker or session_repository"
                )
            session_repository = SqlAlchemySessionRepository(session_maker)
        self.repo: SessionRepository = session_repository
        self.cookie_signer: CookieSigner = cookie_signer
        self.portal_token_validator: ValidatePortalAuthToken = portal_token_validator
        self.clock: Clock = clock or SystemClock()

        self.favorites_cap = favorites_cap
        self.prefs_max_bytes = prefs_max_bytes
        self.last_seen_debounce_seconds = last_seen_debounce_seconds
        self.anonymous_ttl_days = anonymous_ttl_days
        self.cookie_domain = cookie_domain
        self.cookie_secure = cookie_secure
        self.cookie_max_age_seconds = cookie_max_age_seconds

        self.init_session = InitSession(self.repo, self.clock)
        self.get_session_view = GetSessionView(self.repo, self.clock)
        self.update_session_slice = UpdateSessionSlice(
            self.repo,
            favorites_cap=favorites_cap,
            prefs_max_bytes=prefs_max_bytes,
        )
        self.claim_session = ClaimSession(self.repo, self.portal_token_validator, self.clock)
        self.logout_session = LogoutSession(self.repo, self.clock)
        self.prune_stale_anonymous = PruneStaleAnonymousSessions(
            self.repo, ttl_days=anonymous_ttl_days
        )
