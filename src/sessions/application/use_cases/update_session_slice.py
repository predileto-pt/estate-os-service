"""PATCH /me — apply favorites + prefs slice writes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping
from uuid import UUID

from sessions.application.ports.session_repository import SessionRepository
from sessions.domain.exceptions import InvalidFavoriteId
from sessions.domain.models.session import Session
from sessions.domain.value_objects import CookiesConsent


@dataclass(frozen=True)
class FavoritesPatch:
    add: tuple[UUID, ...] = ()
    remove: tuple[UUID, ...] = ()


@dataclass(frozen=True)
class PrefsPatch:
    merge: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SessionPatch:
    favorites: FavoritesPatch | None = None
    prefs: PrefsPatch | None = None
    # `cookies_consent` is a top-level patch, not nested under prefs, because
    # it's column-backed for compliance/analytics queries. `None` here means
    # "don't touch"; the only writable values are ACCEPTED / DECLINED. Clearing
    # back to "undecided" isn't a normal flow and isn't exposed.
    cookies_consent: CookiesConsent | None = None


def parse_favorite_ids(raw: list[str]) -> tuple[UUID, ...]:
    out: list[UUID] = []
    for s in raw:
        try:
            out.append(UUID(s))
        except (ValueError, TypeError, AttributeError) as e:
            raise InvalidFavoriteId(f"not a uuid: {s!r}") from e
    return tuple(out)


class UpdateSessionSlice:
    def __init__(
        self,
        repo: SessionRepository,
        *,
        favorites_cap: int,
        prefs_max_bytes: int,
    ) -> None:
        self._repo = repo
        self._favorites_cap = favorites_cap
        self._prefs_max_bytes = prefs_max_bytes

    async def execute(self, session: Session, patch: SessionPatch) -> Session:
        updated = session
        if patch.favorites is not None:
            for pid in patch.favorites.remove:
                updated = updated.with_favorite_removed(pid)
            for pid in patch.favorites.add:
                updated = updated.with_favorite_added(pid, cap=self._favorites_cap)
        if patch.prefs is not None:
            updated = updated.with_prefs_merged(patch.prefs.merge, max_bytes=self._prefs_max_bytes)
        if patch.cookies_consent is not None:
            updated = updated.with_cookies_consent(patch.cookies_consent)
        if updated is session:
            return session
        return await self._repo.update(updated)
