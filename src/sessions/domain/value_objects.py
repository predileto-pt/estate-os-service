"""Value objects for the sessions bounded context."""

from __future__ import annotations

import enum
from typing import NewType
from uuid import UUID

SessionId = NewType("SessionId", UUID)


class CookiesConsent(str, enum.Enum):
    """GDPR cookie consent state.

    `None` (column nullable) represents "undecided" and is intentionally
    not modeled as an enum member — absence is the natural pre-decision
    signal in both the DB and the API view.
    """

    ACCEPTED = "accepted"
    DECLINED = "declined"
