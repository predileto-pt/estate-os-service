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


@dataclass(frozen=True)
class Address:
    street: str
    parish: str | None  # Freguesia (PT)
    municipality: str | None  # Concelho (PT) / Municipio (ES)
    district: str | None  # Distrito (PT) / Provincia (ES)
    postal_code: str | None
    country: str  # "PT" or "ES"

    def __post_init__(self) -> None:
        if self.country not in ("PT", "ES"):
            raise ValueError(f"Country must be 'PT' or 'ES', got '{self.country}'")
