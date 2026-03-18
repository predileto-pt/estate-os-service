class DomainError(Exception):
    pass


class PropertyNotFoundError(DomainError):
    def __init__(self, identifier: str = "") -> None:
        super().__init__(
            f"Property not found: {identifier}" if identifier else "Property not found"
        )


class PropertyOwnerNotFoundError(DomainError):
    def __init__(self, identifier: str = "") -> None:
        super().__init__(
            f"Property owner not found: {identifier}" if identifier else "Property owner not found"
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


class PropertyExtractionError(DomainError):
    def __init__(self, message: str = "Failed to extract property data") -> None:
        super().__init__(message)


class TooManyDocumentsError(DomainError):
    def __init__(self, count: int = 0, max_count: int = 5) -> None:
        super().__init__(f"Too many documents: {count} (max {max_count})")
