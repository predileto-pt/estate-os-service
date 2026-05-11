"""Capabilities granted to a session, derived from `Session.kind`."""

from __future__ import annotations

import enum


class Capability(str, enum.Enum):
    SAVE_FAVORITE = "SAVE_FAVORITE"
    VIEW_HISTORY = "VIEW_HISTORY"
    SET_PREFERENCES = "SET_PREFERENCES"
    COMMENT = "COMMENT"
    CONTACT_AGENT = "CONTACT_AGENT"
    SAVE_PROPERTY = "SAVE_PROPERTY"


_ANONYMOUS_CAPS: frozenset[Capability] = frozenset(
    {
        Capability.SAVE_FAVORITE,
        Capability.VIEW_HISTORY,
        Capability.SET_PREFERENCES,
    }
)

_AUTHENTICATED_CAPS: frozenset[Capability] = _ANONYMOUS_CAPS | frozenset(
    {
        Capability.COMMENT,
        Capability.CONTACT_AGENT,
        Capability.SAVE_PROPERTY,
    }
)


def capabilities_of(kind: str) -> frozenset[Capability]:
    """Pure mapping from `Session.kind` to its capability set."""
    if kind == "AUTHENTICATED":
        return _AUTHENTICATED_CAPS
    return _ANONYMOUS_CAPS
