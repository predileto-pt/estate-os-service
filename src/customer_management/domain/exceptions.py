class DomainError(Exception):
    pass


class UserNotFoundError(DomainError):
    def __init__(self, identifier: str = "") -> None:
        super().__init__(f"User not found: {identifier}" if identifier else "User not found")


class CompanyNotFoundError(DomainError):
    def __init__(self, identifier: str = "") -> None:
        super().__init__(
            f"Company not found: {identifier}" if identifier else "Company not found"
        )


class SubscriptionNotFoundError(DomainError):
    def __init__(self, identifier: str = "") -> None:
        super().__init__(
            f"Subscription not found: {identifier}" if identifier else "Subscription not found"
        )


class UserAlreadyExistsError(DomainError):
    def __init__(self, email: str = "") -> None:
        super().__init__(
            f"User already exists: {email}" if email else "User already exists"
        )


class AuthorizationError(DomainError):
    def __init__(self, message: str = "Not authorized") -> None:
        super().__init__(message)
