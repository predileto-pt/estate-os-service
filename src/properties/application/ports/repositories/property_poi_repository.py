from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from properties.domain.models.property_poi import PropertyPoi


class PropertyPoiRepository(ABC):
    @abstractmethod
    async def list_by_property(self, property_id: UUID) -> list[PropertyPoi]: ...

    @abstractmethod
    async def get_by_id(self, poi_id: UUID) -> PropertyPoi | None: ...

    @abstractmethod
    async def replace_for_property(
        self, *, property_id: UUID, pois: list[PropertyPoi]
    ) -> list[PropertyPoi]:
        """Replace the entire POI catalog for one property.

        Existing rows are deleted; the new list is inserted with their
        provided `manually_edited` flag (the manual-entry use case sets
        this to True; future auto-discovery writes from the worker set
        it to False). Returns the persisted rows with their ids and
        timestamps.
        """
        ...

    @abstractmethod
    async def update(self, poi: PropertyPoi) -> PropertyPoi:
        """Update a single POI by id. Caller is responsible for setting
        `manually_edited=True` if appropriate — the manual-edit use case
        does this; future auto-discovery writes do not.
        """
        ...

    @abstractmethod
    async def update_place_details(
        self,
        *,
        poi_id: UUID,
        address: str | None,
        image_urls: list[str],
        reviews: list[dict] | None,
    ) -> None:
        """Touch only the place-details columns (address, image_urls,
        reviews). Used by Phase 2 of the enrichment workflow so we
        don't clobber ranking-time fields between Phase 1 (insert) and
        Phase 2 (metadata) writes. Named distinctly from `update` to
        avoid confusion with the existing `metadata: dict` column on
        the aggregate.
        """
        ...

    @abstractmethod
    async def delete(self, poi_id: UUID) -> bool:
        """Returns True if the row existed and was deleted."""
        ...
