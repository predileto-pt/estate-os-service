class DomainError(Exception):
    pass


class UserNotFoundError(DomainError):
    def __init__(self, identifier: str = "") -> None:
        super().__init__(f"User not found: {identifier}" if identifier else "User not found")


class OrganizationNotFoundError(DomainError):
    def __init__(self, identifier: str = "") -> None:
        super().__init__(
            f"Organization not found: {identifier}" if identifier else "Organization not found"
        )


class UserAlreadyExistsError(DomainError):
    def __init__(self, email: str = "") -> None:
        super().__init__(f"User already exists: {email}" if email else "User already exists")


class AuthorizationError(DomainError):
    def __init__(self, message: str = "Not authorized") -> None:
        super().__init__(message)


class InvitationNotFoundError(DomainError):
    def __init__(self, identifier: str = "") -> None:
        super().__init__(
            f"Invitation not found: {identifier}" if identifier else "Invitation not found"
        )


class InvitationExpiredError(DomainError):
    def __init__(self, identifier: str = "") -> None:
        super().__init__(
            f"Invitation expired: {identifier}" if identifier else "Invitation expired"
        )


class MembershipNotFoundError(DomainError):
    def __init__(self, identifier: str = "") -> None:
        super().__init__(
            f"Membership not found: {identifier}" if identifier else "Membership not found"
        )


class MembershipAlreadyExistsError(DomainError):
    def __init__(self, identifier: str = "") -> None:
        super().__init__(
            f"Membership already exists: {identifier}"
            if identifier
            else "Membership already exists"
        )


class LastOwnerError(DomainError):
    def __init__(self) -> None:
        super().__init__("Cannot remove or demote the last owner of the organization")


class InsufficientPermissionError(DomainError):
    def __init__(self, permission: str = "") -> None:
        super().__init__(
            f"Insufficient permission: {permission}" if permission else "Insufficient permission"
        )
