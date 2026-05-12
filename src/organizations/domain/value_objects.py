from dataclasses import dataclass


@dataclass(frozen=True)
class PhoneNumber:
    """Organization phone number. Same shape as identity's PhoneNumber
    — mirrored here so organizations doesn't import from identity
    (cross-context dependency rule). The repo layer stores the two
    fields as separate columns; the domain composes them into a
    value object."""

    country_code: str  # "+351", "+34"
    number: str

    def __post_init__(self) -> None:
        if not self.country_code.startswith("+"):
            raise ValueError(f"Country code must start with '+', got '{self.country_code}'")
        if not self.number.strip():
            raise ValueError("Phone number cannot be empty")
