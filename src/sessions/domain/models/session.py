"""Session aggregate — root of the sessions bounded context.

Immutable transitions: each `with_*` / `claimed_by` / `logged_out` / `touched`
returns a new `Session` rather than mutating in place. Repository persists
the returned value.
"""

from __future__ import annotations

import enum
import json
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Mapping
from uuid import UUID

from sessions.domain.exceptions import (
    FavoriteLimitExceeded,
    PrefsTooLarge,
)
from sessions.domain.value_objects import CookiesConsent, SessionId


class SessionKind(str, enum.Enum):
    ANONYMOUS = "ANONYMOUS"
    AUTHENTICATED = "AUTHENTICATED"


@dataclass(frozen=True)
class Session:
    id: SessionId
    kind: SessionKind
    user_id: UUID | None
    favorites: frozenset[UUID]
    prefs: Mapping[str, Any]
    created_at: datetime
    last_seen_at: datetime
    claimed_at: datetime | None
    revoked: bool
    cookies_consent: CookiesConsent | None = None

    # ── Favorites ───────────────────────────────────────────────────────

    def with_favorite_added(self, property_id: UUID, *, cap: int) -> "Session":
        if property_id in self.favorites:
            return self
        if len(self.favorites) + 1 > cap:
            raise FavoriteLimitExceeded(f"favorite cap {cap} reached; cannot add {property_id}")
        return replace(self, favorites=self.favorites | {property_id})

    def with_favorite_removed(self, property_id: UUID) -> "Session":
        if property_id not in self.favorites:
            return self
        return replace(self, favorites=self.favorites - {property_id})

    # ── Prefs ───────────────────────────────────────────────────────────

    def with_prefs_merged(self, patch: Mapping[str, Any], *, max_bytes: int) -> "Session":
        merged = _deep_merge(dict(self.prefs), patch)
        size = len(json.dumps(merged, separators=(",", ":")).encode("utf-8"))
        if size > max_bytes:
            raise PrefsTooLarge(f"prefs serialized to {size} bytes; cap is {max_bytes}")
        return replace(self, prefs=merged)

    # ── Cookies consent ────────────────────────────────────────────────

    def with_cookies_consent(self, value: CookiesConsent | None) -> "Session":
        if value == self.cookies_consent:
            return self
        return replace(self, cookies_consent=value)

    # ── Auth state ──────────────────────────────────────────────────────

    def claimed_by(self, user_id: UUID, *, now: datetime) -> "Session":
        return replace(
            self,
            kind=SessionKind.AUTHENTICATED,
            user_id=user_id,
            claimed_at=now,
        )

    def logged_out(self, *, now: datetime) -> "Session":
        """Flip to anonymous and clear favorites + prefs.

        See spec §6.5 — clearing on logout avoids shared-device data leaks.
        Idempotent: logging out an already-anonymous session is a no-op
        beyond `last_seen_at` refresh.
        """
        return replace(
            self,
            kind=SessionKind.ANONYMOUS,
            user_id=None,
            claimed_at=None,
            favorites=frozenset(),
            prefs={},
            last_seen_at=now,
        )

    def touched(self, *, now: datetime) -> "Session":
        return replace(self, last_seen_at=now)


def _deep_merge(base: dict, patch: Mapping[str, Any]) -> dict:
    """Recursive merge — patch values override base; dicts merge recursively."""
    out = dict(base)
    for key, value in patch.items():
        if isinstance(value, Mapping) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out
