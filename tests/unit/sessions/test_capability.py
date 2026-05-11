"""Capability derivation tests."""

from sessions.domain.models.capability import Capability, capabilities_of


def test_anonymous_capabilities():
    caps = capabilities_of("ANONYMOUS")
    assert caps == frozenset(
        {Capability.SAVE_FAVORITE, Capability.VIEW_HISTORY, Capability.SET_PREFERENCES}
    )


def test_authenticated_capabilities_are_superset():
    anon = capabilities_of("ANONYMOUS")
    auth = capabilities_of("AUTHENTICATED")
    assert anon.issubset(auth)
    assert auth - anon == frozenset(
        {Capability.COMMENT, Capability.CONTACT_AGENT, Capability.SAVE_PROPERTY}
    )


def test_unknown_kind_falls_back_to_anonymous():
    assert capabilities_of("garbage") == capabilities_of("ANONYMOUS")
