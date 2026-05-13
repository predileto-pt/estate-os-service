from __future__ import annotations

from dataclasses import replace
from uuid import UUID

from properties.application.events.property_event import emit_property_updated
from properties.application.ports.repositories.property_repository import (
    PropertyRepository,
)
from properties.domain.exceptions import PropertyNotFoundError
from properties.domain.models.property import Property
from properties.domain.models.property_characteristics import PropertyCharacteristics
from shared.events.ports import EventPublisher

# Sentinel — distinguishes "field omitted from patch" (keep current value)
# from "field set to None" (clear it). Mirrors the partial-update pattern
# used in UpdatePropertyOwnerContact.
_UNSET: object = object()


class UpdatePropertyCharacteristics:
    """Patch a property's `characteristics`, bump aggregate_version, and emit
    PROPERTY_UPDATED.v1.

    Partial update: only the keyword args explicitly passed (non-`_UNSET`)
    are merged onto the current characteristics. Pass `None` for a field
    to clear it. No-op short-circuits when the merged result equals the
    current characteristics.
    """

    def __init__(
        self,
        property_repo: PropertyRepository,
        domain_event_publisher: EventPublisher | None = None,
    ) -> None:
        self.property_repo = property_repo
        self.domain_event_publisher = domain_event_publisher

    async def execute(
        self,
        *,
        property_id: UUID,
        organization_id: UUID,
        area_in_m2: float | None | object = _UNSET,
        num_of_bedrooms: int | None | object = _UNSET,
        num_of_bathrooms: int | None | object = _UNSET,
        built_at: int | None | object = _UNSET,
        energy_rating: str | None | object = _UNSET,
        floor: int | None | object = _UNSET,
        parking_spaces: int | None | object = _UNSET,
        has_elevator: bool | None | object = _UNSET,
        has_garden: bool | None | object = _UNSET,
        has_pool: bool | None | object = _UNSET,
    ) -> Property:
        prop = await self.property_repo.get_by_id(property_id)
        if prop is None or prop.organization_id != organization_id:
            raise PropertyNotFoundError(str(property_id))

        current = prop.characteristics or PropertyCharacteristics()
        updates: dict = {}
        for name, value in (
            ("area_in_m2", area_in_m2),
            ("num_of_bedrooms", num_of_bedrooms),
            ("num_of_bathrooms", num_of_bathrooms),
            ("built_at", built_at),
            ("energy_rating", energy_rating),
            ("floor", floor),
            ("parking_spaces", parking_spaces),
            ("has_elevator", has_elevator),
            ("has_garden", has_garden),
            ("has_pool", has_pool),
        ):
            if value is not _UNSET:
                updates[name] = value

        merged = replace(current, **updates) if updates else current
        if merged == prop.characteristics:
            return prop

        prop.characteristics = merged
        await self.property_repo.update_characteristics(property_id, merged.to_dict())
        refreshed = await self.property_repo.bump_aggregate_version(property_id)
        await emit_property_updated(self.domain_event_publisher, refreshed)
        return refreshed
