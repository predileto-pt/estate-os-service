import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from properties.adapters.workers.discovery_processor import process_event
from properties.domain.exceptions import (
    PropertyMissingCoordinatesError,
    PropertyNotFoundError,
)


@pytest.fixture
def container():
    c = MagicMock()
    c.discover_property_amenities = MagicMock()
    c.discover_property_amenities.execute = AsyncMock(return_value=[])
    return c


class TestDiscoveryProcessor:
    async def test_property_created_event(self, container):
        property_id = str(uuid4())
        body = {
            "event_type": "PROPERTY_CREATED.v1",
            "data": {"property_id": property_id},
        }

        await process_event(body, container)

        container.discover_property_amenities.execute.assert_called_once_with(
            property_id=property_id
        )

    async def test_missing_property_id(self, container):
        body = {
            "event_type": "PROPERTY_CREATED.v1",
            "data": {},
        }

        await process_event(body, container)

        container.discover_property_amenities.execute.assert_not_called()

    async def test_unknown_event_type_still_processes(self, container):
        """Event type filtering is now done by the shared EventRouter.
        The processor always calls handle_property_created with the data."""
        body = {
            "event_type": "UNKNOWN_EVENT",
            "data": {"property_id": str(uuid4())},
        }

        await process_event(body, container)

        container.discover_property_amenities.execute.assert_called_once()

    async def test_missing_coordinates_handled_gracefully(self, container):
        container.discover_property_amenities.execute = AsyncMock(
            side_effect=PropertyMissingCoordinatesError("test-id")
        )

        body = {
            "event_type": "PROPERTY_CREATED.v1",
            "data": {"property_id": str(uuid4())},
        }

        # Should not raise
        await process_event(body, container)

    async def test_property_not_found_handled_gracefully(self, container):
        container.discover_property_amenities.execute = AsyncMock(
            side_effect=PropertyNotFoundError("test-id")
        )

        body = {
            "event_type": "PROPERTY_CREATED.v1",
            "data": {"property_id": str(uuid4())},
        }

        # Should not raise
        await process_event(body, container)
