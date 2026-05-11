"""Value objects for the sessions bounded context."""

from __future__ import annotations

from typing import NewType
from uuid import UUID

SessionId = NewType("SessionId", UUID)
