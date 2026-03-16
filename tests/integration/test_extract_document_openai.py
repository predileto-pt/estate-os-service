"""Integration test for document extraction using the real OpenAIDocumentExtractor
with a mocked OpenAI client returning structured output."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from customer_management.adapters.inmemory.inmemory_company_repo import InMemoryCompanyRepository
from customer_management.adapters.inmemory.inmemory_email_service import InMemoryEmailService
from customer_management.adapters.inmemory.inmemory_event_bus import InMemoryEventBus
from customer_management.adapters.inmemory.inmemory_notification_repo import (
    InMemoryNotificationRepository,
)
from customer_management.adapters.inmemory.inmemory_subscription_repo import (
    InMemorySubscriptionRepository,
)
from customer_management.adapters.inmemory.inmemory_user_repo import InMemoryUserRepository
from customer_management.container import Container
from shared.main import create_app
from property_management.adapters.ai.openai_document_extractor import (
    OpenAIDocumentExtractor,
    PropertyOwnerExtraction,
)
from property_management.adapters.inmemory.inmemory_property_repo import InMemoryPropertyRepository
from property_management.container import Container as PropertyContainer
from tests.conftest import TEST_JWT_SECRET, make_test_token

EXTRACTED_OWNER = PropertyOwnerExtraction(
    full_name="João Manuel Pereira",
    civil_status="married",
    address="Rua Augusta 45, 1100-053 Lisboa",
    nif="987654321",
    document_type="cartao_cidadao",
    document_id="99887766",
    issued_by="República Portuguesa",
    issuing_district="Lisboa",
    date_of_birth="1978-11-20",
)


def _mock_openai_response(parsed: PropertyOwnerExtraction) -> MagicMock:
    """Build a mock that mirrors the OpenAI structured output response shape."""
    message = MagicMock()
    message.parsed = parsed

    choice = MagicMock()
    choice.message = message

    response = MagicMock()
    response.choices = [choice]
    return response


@pytest.fixture
def openai_extractor():
    return OpenAIDocumentExtractor(api_key="sk-test-fake-key")


@pytest.fixture
def openai_app(openai_extractor, monkeypatch):
    monkeypatch.setattr("shared.config.settings.supabase_jwt_secret", TEST_JWT_SECRET)

    container = Container(
        user_repo=InMemoryUserRepository(),
        company_repo=InMemoryCompanyRepository(),
        subscription_repo=InMemorySubscriptionRepository(),
        notification_repo=InMemoryNotificationRepository(),
        email_service=InMemoryEmailService(),
        event_bus=InMemoryEventBus(),
    )
    property_container = PropertyContainer(
        property_repo=InMemoryPropertyRepository(),
        document_extractor=openai_extractor,
    )
    return create_app(container=container, property_container=property_container)


@pytest.fixture
async def openai_client(openai_app):
    transport = ASGITransport(app=openai_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def openai_auth_headers():
    token = make_test_token()
    return {"Authorization": f"Bearer {token}"}


async def _create_property(client, headers) -> str:
    resp = await client.post(
        "/api/v1/properties/",
        json={
            "address": "Av. da Liberdade 10, Lisboa",
            "listing_type": "sale",
            "typology": "house",
        },
        headers=headers,
    )
    assert resp.status_code == 201
    return resp.json()["id"]


class TestExtractFromDocumentWithOpenAI:
    async def test_successful_extraction(
        self, openai_client, openai_auth_headers, openai_extractor
    ):
        property_id = await _create_property(openai_client, openai_auth_headers)

        mock_response = _mock_openai_response(EXTRACTED_OWNER)
        openai_extractor._client.beta.chat.completions.parse = AsyncMock(return_value=mock_response)

        response = await openai_client.post(
            "/api/v1/property-owners/extract-from-document",
            data={"property_id": property_id},
            files={"file": ("cidadao.jpg", b"fake-image-bytes", "image/jpeg")},
            headers=openai_auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["id"] == property_id
        assert len(data["owners"]) == 1

        owner = data["owners"][0]
        assert owner["full_name"] == "João Manuel Pereira"
        assert owner["civil_status"] == "married"
        assert owner["nif"] == "987654321"
        assert owner["document_type"] == "cartao_cidadao"
        assert owner["document_id"] == "99887766"
        assert owner["issued_by"] == "República Portuguesa"
        assert owner["issuing_district"] == "Lisboa"
        assert owner["date_of_birth"] == "1978-11-20"
        assert owner["address"] == "Rua Augusta 45, 1100-053 Lisboa"

        # Verify the OpenAI client was called with structured output
        call_kwargs = openai_extractor._client.beta.chat.completions.parse.call_args.kwargs
        assert call_kwargs["response_format"] is PropertyOwnerExtraction
        assert call_kwargs["model"] == "gpt-4o"

    async def test_extraction_with_null_issuing_district(
        self, openai_client, openai_auth_headers, openai_extractor
    ):
        property_id = await _create_property(openai_client, openai_auth_headers)

        extracted = PropertyOwnerExtraction(
            full_name="Ana Costa",
            civil_status="single",
            address="Rua do Carmo 5, Porto",
            nif="111222333",
            document_type="passport",
            document_id="AB123456",
            issued_by="SEF",
            issuing_district=None,
            date_of_birth="1995-03-10",
        )
        openai_extractor._client.beta.chat.completions.parse = AsyncMock(
            return_value=_mock_openai_response(extracted)
        )

        response = await openai_client.post(
            "/api/v1/property-owners/extract-from-document",
            data={"property_id": property_id},
            files={"file": ("passport.jpg", b"fake-data", "image/jpeg")},
            headers=openai_auth_headers,
        )

        assert response.status_code == 201
        owner = response.json()["owners"][0]
        assert owner["issuing_district"] is None
        assert owner["document_type"] == "passport"

    async def test_extraction_empty_response(
        self, openai_client, openai_auth_headers, openai_extractor
    ):
        property_id = await _create_property(openai_client, openai_auth_headers)

        # Simulate parsed=None (empty response)
        message = MagicMock()
        message.parsed = None
        choice = MagicMock()
        choice.message = message
        mock_resp = MagicMock()
        mock_resp.choices = [choice]

        openai_extractor._client.beta.chat.completions.parse = AsyncMock(return_value=mock_resp)

        response = await openai_client.post(
            "/api/v1/property-owners/extract-from-document",
            data={"property_id": property_id},
            files={"file": ("doc.jpg", b"fake", "image/jpeg")},
            headers=openai_auth_headers,
        )

        assert response.status_code == 422
        assert "Empty response" in response.json()["detail"]

    async def test_extraction_openai_api_error(
        self, openai_client, openai_auth_headers, openai_extractor
    ):
        property_id = await _create_property(openai_client, openai_auth_headers)

        openai_extractor._client.beta.chat.completions.parse = AsyncMock(
            side_effect=Exception("API rate limit exceeded")
        )

        response = await openai_client.post(
            "/api/v1/property-owners/extract-from-document",
            data={"property_id": property_id},
            files={"file": ("doc.jpg", b"fake", "image/jpeg")},
            headers=openai_auth_headers,
        )

        assert response.status_code == 422
        assert "AI extraction failed" in response.json()["detail"]

    async def test_extraction_invalid_civil_status(
        self, openai_client, openai_auth_headers, openai_extractor
    ):
        """OpenAI returns a civil_status value not in our enum."""
        property_id = await _create_property(openai_client, openai_auth_headers)

        extracted = PropertyOwnerExtraction(
            full_name="Test Person",
            civil_status="unknown_status",
            address="Rua X",
            nif="123456789",
            document_type="cartao_cidadao",
            document_id="12345678",
            issued_by="SEF",
            issuing_district=None,
            date_of_birth="1990-01-01",
        )
        openai_extractor._client.beta.chat.completions.parse = AsyncMock(
            return_value=_mock_openai_response(extracted)
        )

        response = await openai_client.post(
            "/api/v1/property-owners/extract-from-document",
            data={"property_id": property_id},
            files={"file": ("doc.jpg", b"fake", "image/jpeg")},
            headers=openai_auth_headers,
        )

        assert response.status_code == 422
        assert "Invalid extracted data" in response.json()["detail"]

    async def test_extraction_property_not_found(
        self, openai_client, openai_auth_headers, openai_extractor
    ):
        response = await openai_client.post(
            "/api/v1/property-owners/extract-from-document",
            data={"property_id": "00000000-0000-0000-0000-000000000099"},
            files={"file": ("doc.jpg", b"fake", "image/jpeg")},
            headers=openai_auth_headers,
        )

        assert response.status_code == 404

    async def test_extraction_not_authorized(
        self, openai_client, openai_auth_headers, openai_extractor
    ):
        property_id = await _create_property(openai_client, openai_auth_headers)

        other_token = make_test_token(sub="00000000-0000-0000-0000-000000000099")
        other_headers = {"Authorization": f"Bearer {other_token}"}

        response = await openai_client.post(
            "/api/v1/property-owners/extract-from-document",
            data={"property_id": property_id},
            files={"file": ("doc.jpg", b"fake", "image/jpeg")},
            headers=other_headers,
        )

        assert response.status_code == 403
