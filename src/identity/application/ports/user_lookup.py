"""Cross-context read port: look up a User by their aggregate id.

Consumed by the `organizations` bounded context (e.g. rendering invitation
emails or membership lists that need the inviter/member's name or email).

Callable Protocol — bound at container-construction time to `FindUser.by_id`.
No adapter class. See Q1 = 1.c in the spec.
"""

from typing import Protocol
from uuid import UUID

from identity.domain.models.user import User


class UserLookupById(Protocol):
    async def __call__(self, id: UUID) -> User | None: ...
