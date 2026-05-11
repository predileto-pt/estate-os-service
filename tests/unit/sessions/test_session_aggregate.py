"""Domain tests for the `Session` aggregate."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from sessions.domain.exceptions import FavoriteLimitExceeded, PrefsTooLarge
from sessions.domain.models.session import Session, SessionKind
from sessions.domain.value_objects import SessionId


def _make(**overrides) -> Session:
    base = dict(
        id=SessionId(uuid4()),
        kind=SessionKind.ANONYMOUS,
        user_id=None,
        favorites=frozenset(),
        prefs={},
        created_at=datetime(2026, 5, 11, tzinfo=timezone.utc),
        last_seen_at=datetime(2026, 5, 11, tzinfo=timezone.utc),
        claimed_at=None,
        revoked=False,
    )
    base.update(overrides)
    return Session(**base)


def test_with_favorite_added_returns_new_session_with_id():
    s = _make()
    pid = uuid4()
    s2 = s.with_favorite_added(pid, cap=10)
    assert s2 is not s
    assert pid in s2.favorites
    assert pid not in s.favorites


def test_with_favorite_added_is_idempotent():
    s = _make()
    pid = uuid4()
    s2 = s.with_favorite_added(pid, cap=10)
    s3 = s2.with_favorite_added(pid, cap=10)
    assert s3 is s2


def test_with_favorite_added_enforces_cap():
    pids = {uuid4() for _ in range(3)}
    s = _make(favorites=frozenset(pids))
    with pytest.raises(FavoriteLimitExceeded):
        s.with_favorite_added(uuid4(), cap=3)


def test_with_favorite_removed_drops_id():
    pid = uuid4()
    s = _make(favorites=frozenset({pid}))
    s2 = s.with_favorite_removed(pid)
    assert pid not in s2.favorites


def test_with_prefs_merged_deep_merges():
    s = _make(prefs={"a": {"b": 1, "c": 2}})
    s2 = s.with_prefs_merged({"a": {"c": 99, "d": 3}}, max_bytes=8192)
    assert s2.prefs == {"a": {"b": 1, "c": 99, "d": 3}}


def test_with_prefs_merged_enforces_byte_cap():
    s = _make()
    big = {"k": "x" * 9000}
    with pytest.raises(PrefsTooLarge):
        s.with_prefs_merged(big, max_bytes=8192)


def test_claimed_by_flips_kind_and_user_id():
    s = _make()
    user_id = uuid4()
    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    s2 = s.claimed_by(user_id, now=now)
    assert s2.kind == SessionKind.AUTHENTICATED
    assert s2.user_id == user_id
    assert s2.claimed_at == now


def test_logged_out_clears_user_favorites_and_prefs():
    user_id = uuid4()
    s = _make(
        kind=SessionKind.AUTHENTICATED,
        user_id=user_id,
        favorites=frozenset({uuid4(), uuid4()}),
        prefs={"theme": "dark"},
        claimed_at=datetime(2026, 5, 10, tzinfo=timezone.utc),
    )
    s2 = s.logged_out(now=datetime(2026, 5, 11, tzinfo=timezone.utc))
    assert s2.kind == SessionKind.ANONYMOUS
    assert s2.user_id is None
    assert s2.favorites == frozenset()
    assert s2.prefs == {}
    assert s2.claimed_at is None


def test_touched_updates_only_last_seen_at():
    s = _make()
    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    s2 = s.touched(now=now)
    assert s2.last_seen_at == now
    assert s2.favorites == s.favorites
    assert s2.prefs == s.prefs
    assert s2.kind == s.kind
