"""Identity container.

Wires the three identity use cases over a `UserRepository` adapter. The
container also exposes `register_user` (bound to `RegisterUserPort`) and
`find_user` (whose `.by_id` method is bound to `UserLookupById`) — these
are the callable bindings passed into the `organizations` container.
"""

from identity.application.ports.repositories.user_repository import UserRepository
from identity.application.use_cases.find_user import FindUser
from identity.application.use_cases.register_user import RegisterUser
from identity.application.use_cases.update_user_profile import UpdateUserProfile


class Container:
    def __init__(self, user_repo: UserRepository) -> None:
        self.user_repo = user_repo
        self.register_user = RegisterUser(user_repo=user_repo)
        self.update_user_profile = UpdateUserProfile(user_repo=user_repo)
        self.find_user = FindUser(user_repo=user_repo)

    # Callable-Protocol bindings for cross-context consumption by organizations.
    # Both satisfy their respective callable Protocols via duck-typing (Q1 = 1.c).
    @property
    def register_user_port(self):
        """Bound method satisfying `RegisterUserPort` callable Protocol."""
        return self.register_user.execute

    @property
    def user_lookup_by_id(self):
        """Bound method satisfying `UserLookupById` callable Protocol."""
        return self.find_user.by_id
