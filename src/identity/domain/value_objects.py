from dataclasses import dataclass


@dataclass(frozen=True)
class PhoneNumber:
    country_code: str  # "+351", "+34"
    number: str

    def __post_init__(self) -> None:
        if not self.country_code.startswith("+"):
            raise ValueError(f"Country code must start with '+', got '{self.country_code}'")
        if not self.number.strip():
            raise ValueError("Phone number cannot be empty")
