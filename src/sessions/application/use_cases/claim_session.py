"""Claim a session — flip anonymous → authenticated via portal Supabase JWT."""

from __future__ import annotations

from sessions.application.ports.clock import Clock
from sessions.application.ports.session_repository import SessionRepository
from sessions.application.ports.validate_portal_auth_token import (
    ValidatePortalAuthToken,
)
from sessions.domain.exceptions import SessionBoundToOtherUser
from sessions.domain.models.session import Session, SessionKind


class ClaimSession:
    def __init__(
        self,
        repo: SessionRepository,
        token_validator: ValidatePortalAuthToken,
        clock: Clock,
    ) -> None:
        self._repo = repo
        self._token_validator = token_validator
        self._clock = clock

    async def execute(self, session: Session, auth_token: str) -> Session:
        identity = await self._token_validator.execute(auth_token)
        if (
            session.kind == SessionKind.AUTHENTICATED
            and session.user_id is not None
            and session.user_id != identity.user_id
        ):
            raise SessionBoundToOtherUser(
                f"session {session.id} is already bound to a different user"
            )
        if session.kind == SessionKind.AUTHENTICATED and session.user_id == identity.user_id:
            # Idempotent re-claim by the same user.
            return session
        claimed = session.claimed_by(identity.user_id, now=self._clock.now())
        return await self._repo.update(claimed)
