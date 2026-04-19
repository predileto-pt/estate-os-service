import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from properties.adapters.workers.discovery_processor import handle_property_created
from properties.domain.exceptions import (
    PropertyMissingCoordinatesError,
    PropertyNotFoundError,
)
from shared.events.base import DomainEvent
from shared.events.types import PROPERTY_CREATED_V1


@pytest.fixture
def container():
    c = MagicMock()
    c.discover_property_amenities = MagicMock()
    c.discover_property_amenities.execute = AsyncMock(return_value=[])
    return c


@pytest.fixture
def context(container):
    return {"property": container}


class TestDiscoveryProcessor:
    async def test_property_created_event(self, container, context):
        property_id = str(uuid4())
        event = DomainEvent(
            event_type=PROPERTY_CREATED_V1,
            data={"id": property_id},
        )

        await handle_property_created(event, context)

        container.discover_property_amenities.execute.assert_called_once_with(
            property_id=property_id
        )

    async def test_missing_property_id(self, container, context):
        event = DomainEvent(event_type=PROPERTY_CREATED_V1, data={})

        await handle_property_created(event, context)

        container.discover_property_amenities.execute.assert_not_called()

    async def test_missing_coordinates_handled_gracefully(self, container, context):
        container.discover_property_amenities.execute = AsyncMock(
            side_effect=PropertyMissingCoordinatesError("test-id")
        )
        event = DomainEvent(
            event_type=PROPERTY_CREATED_V1,
            data={"id": str(uuid4())},
        )

        # Should not raise
        await handle_property_created(event, context)

    async def test_property_not_found_handled_gracefully(self, container, context):
        container.discover_property_amenities.execute = AsyncMock(
            side_effect=PropertyNotFoundError("test-id")
        )
        event = DomainEvent(
            event_type=PROPERTY_CREATED_V1,
            data={"id": str(uuid4())},
        )

        # Should not raise
        await handle_property_created(event, context)
