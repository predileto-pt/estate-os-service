from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PropertyCharacteristics:
    area_in_m2: float | None = None
    num_of_bedrooms: int | None = None
    num_of_bathrooms: int | None = None
    built_at: int | None = None
    energy_rating: str | None = None
    floor: int | None = None
    parking_spaces: int | None = None
    has_elevator: bool | None = None
    has_garden: bool | None = None
    has_pool: bool | None = None

    def __post_init__(self) -> None:
        if self.area_in_m2 is not None and self.area_in_m2 <= 0:
            raise ValueError("area_in_m2 must be positive")
        for field_name in ("num_of_bedrooms", "num_of_bathrooms", "parking_spaces"):
            value = getattr(self, field_name)
            if value is not None and value < 0:
                raise ValueError(f"{field_name} must be non-negative")
        if self.built_at is not None and (self.built_at < 1000 or self.built_at > 2100):
            raise ValueError("built_at must be a valid year")

    def to_dict(self) -> dict:
        return {
            "area_in_m2": self.area_in_m2,
            "num_of_bedrooms": self.num_of_bedrooms,
            "num_of_bathrooms": self.num_of_bathrooms,
            "built_at": self.built_at,
            "energy_rating": self.energy_rating,
            "floor": self.floor,
            "parking_spaces": self.parking_spaces,
            "has_elevator": self.has_elevator,
            "has_garden": self.has_garden,
            "has_pool": self.has_pool,
        }

    @classmethod
    def from_dict(cls, data: dict) -> PropertyCharacteristics:
        return cls(
            area_in_m2=data.get("area_in_m2"),
            num_of_bedrooms=data.get("num_of_bedrooms"),
            num_of_bathrooms=data.get("num_of_bathrooms"),
            built_at=data.get("built_at"),
            energy_rating=data.get("energy_rating"),
            floor=data.get("floor"),
            parking_spaces=data.get("parking_spaces"),
            has_elevator=data.get("has_elevator"),
            has_garden=data.get("has_garden"),
            has_pool=data.get("has_pool"),
        )
