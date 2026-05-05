from __future__ import annotations


class DomainError(Exception):
    pass


class PropertyNotFoundError(DomainError):
    def __init__(self, identifier: str = "") -> None:
        super().__init__(
            f"Property not found: {identifier}" if identifier else "Property not found"
        )


class PropertyNotPublishableError(DomainError):
    def __init__(self, reasons: list[str]) -> None:
        self.reasons = reasons
        super().__init__(f"Property is not publishable: {', '.join(reasons)}")


class PropertyAddressInvalidError(DomainError):
    def __init__(self, message: str = "address must not be empty") -> None:
        super().__init__(message)


class PropertyOwnerNotFoundError(DomainError):
    def __init__(self, identifier: str = "") -> None:
        super().__init__(
            f"Property owner not found: {identifier}" if identifier else "Property owner not found"
        )


class PropertyImageNotFoundError(DomainError):
    def __init__(self, identifier: str = "") -> None:
        super().__init__(
            f"Property image not found: {identifier}" if identifier else "Property image not found"
        )


class PropertyPriceNotFoundError(DomainError):
    def __init__(self, identifier: str = "") -> None:
        super().__init__(
            f"Property price not found: {identifier}" if identifier else "Property price not found"
        )


class InvalidNIFError(DomainError):
    def __init__(self, nif: str = "") -> None:
        super().__init__(f"Invalid NIF: {nif}" if nif else "Invalid NIF")


class DocumentExtractionError(DomainError):
    def __init__(self, message: str = "Failed to extract data from document") -> None:
        super().__init__(message)


class ExtractionJobNotFoundError(DomainError):
    def __init__(self, identifier: str = "") -> None:
        super().__init__(
            f"Extraction job not found: {identifier}" if identifier else "Extraction job not found"
        )


class InvalidJobTransitionError(DomainError):
    """Raised when an extraction job is asked to transition to an illegal status."""

    pass


class PropertyExtractionError(DomainError):
    def __init__(self, message: str = "Failed to extract property data") -> None:
        super().__init__(message)


class TooManyDocumentsError(DomainError):
    def __init__(self, count: int = 0, max_count: int = 5) -> None:
        super().__init__(f"Too many documents: {count} (max {max_count})")


class PropertyMissingCoordinatesError(DomainError):
    def __init__(self, identifier: str = "") -> None:
        super().__init__(
            f"Property missing coordinates: {identifier}"
            if identifier
            else "Property missing coordinates"
        )
