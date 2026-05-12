"""Enhance a property's free-text description via an LLM.

Loads the aggregate, asks the `DescriptionEnhancer` port to rewrite the
description using the property's structured facts as anchors, persists
the new value, bumps `aggregate_version`, and emits `PROPERTY_UPDATED.v1`
so the listings projector re-indexes. Same shape as
`UpdatePropertyAddress` — single-aggregate update + version bump + event.
"""

from __future__ import annotations

from uuid import UUID

import structlog

from properties.application.events.property_event import emit_property_updated
from properties.application.ports.description_enhancer import (
    DescriptionEnhancer,
    PropertyDescriptionContext,
)
from properties.application.ports.repositories.property_repository import (
    PropertyRepository,
)
from properties.domain.exceptions import PropertyNotFoundError
from properties.domain.models.property import Property
from shared.events.ports import EventPublisher

log = structlog.get_logger()


class EnhancePropertyDescription:
    def __init__(
        self,
        property_repo: PropertyRepository,
        description_enhancer: DescriptionEnhancer,
        domain_event_publisher: EventPublisher | None = None,
    ) -> None:
        self.property_repo = property_repo
        self.description_enhancer = description_enhancer
        self.domain_event_publisher = domain_event_publisher

    async def execute(
        self,
        *,
        property_id: UUID,
        organization_id: UUID,
    ) -> Property:
        prop = await self.property_repo.get_by_id(property_id)
        if prop is None or prop.organization_id != organization_id:
            raise PropertyNotFoundError(str(property_id))

        context = PropertyDescriptionContext(
            current_description=prop.description,
            title=prop.title,
            address=prop.address,
            listing_type=prop.listing_type.value,
            typology=prop.typology.value,
            area_in_m2=(
                prop.characteristics.area_in_m2 if prop.characteristics is not None else None
            ),
            num_of_bedrooms=(
                prop.characteristics.num_of_bedrooms if prop.characteristics is not None else None
            ),
            num_of_bathrooms=(
                prop.characteristics.num_of_bathrooms if prop.characteristics is not None else None
            ),
            has_pool=(prop.characteristics.has_pool if prop.characteristics is not None else None),
            has_garden=(
                prop.characteristics.has_garden if prop.characteristics is not None else None
            ),
            has_elevator=(
                prop.characteristics.has_elevator if prop.characteristics is not None else None
            ),
        )

        enhanced = await self.description_enhancer.enhance(context)
        prop.update_description(enhanced)

        await self.property_repo.update_description(property_id, prop.description)
        refreshed = await self.property_repo.bump_aggregate_version(property_id)

        log.info(
            "property.description_enhanced",
            property_id=str(property_id),
            old_length=len(context.current_description or ""),
            new_length=len(prop.description or ""),
        )
        await emit_property_updated(self.domain_event_publisher, refreshed)
        return refreshed
