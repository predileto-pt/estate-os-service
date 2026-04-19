class DomainError(Exception):
    pass


class UserNotFoundError(DomainError):
    def __init__(self, identifier: str = "") -> None:
        super().__init__(f"User not found: {identifier}" if identifier else "User not found")


class UserAlreadyExistsError(DomainError):
    def __init__(self, email: str = "") -> None:
        super().__init__(f"User already exists: {email}" if email else "User already exists")
