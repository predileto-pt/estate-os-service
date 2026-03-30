"""Integration test for document extraction using the text-based
OpenAIIdDocumentExtractor with a mocked LangChain LLM."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from customer_management.adapters.inmemory.inmemory_email_service import InMemoryEmailService
from customer_management.adapters.inmemory.inmemory_invitation_repo import (
    InMemoryInvitationRepository,
)
from customer_management.adapters.inmemory.inmemory_membership_repo import (
    InMemoryMembershipRepository,
)
from customer_management.adapters.inmemory.inmemory_notification_repo import (
    InMemoryNotificationRepository,
)
from customer_management.adapters.inmemory.inmemory_organization_repo import (
    InMemoryOrganizationRepository,
)
from customer_management.adapters.inmemory.inmemory_subscription_repo import (
    InMemorySubscriptionRepository,
)
from customer_management.adapters.inmemory.inmemory_user_repo import InMemoryUserRepository
from customer_management.container import Container
from shared.main import create_app
from property_management.adapters.ai.openai_id_document_extractor import (
    IdOwnerSchema,
    OpenAIIdDocumentExtractor,
)
from property_management.adapters.inmemory.inmemory_document_parser import InMemoryDocumentParser
from property_management.adapters.inmemory.inmemory_property_repo import InMemoryPropertyRepository
from property_management.container import Container as PropertyContainer
from tests.conftest import TEST_JWT_SECRET, TEST_ORGANIZATION_ID, make_test_token

EXTRACTED_OWNER = IdOwnerSchema(
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


@pytest.fixture
def id_extractor():
    return OpenAIIdDocumentExtractor(api_key="sk-test-fake-key")


@pytest.fixture
def openai_app(id_extractor, monkeypatch):
    monkeypatch.setattr("shared.config.settings.supabase_jwt_secret", TEST_JWT_SECRET)

    container = Container(
        user_repo=InMemoryUserRepository(),
        organization_repo=InMemoryOrganizationRepository(),
        subscription_repo=InMemorySubscriptionRepository(),
        notification_repo=InMemoryNotificationRepository(),
        membership_repo=InMemoryMembershipRepository(),
        invitation_repo=InMemoryInvitationRepository(),
        email_service=InMemoryEmailService(),
    )
    property_container = PropertyContainer(
        property_repo=InMemoryPropertyRepository(),
        document_extractor=id_extractor,
        document_parser=InMemoryDocumentParser(),
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
        "/api/v1/admin/properties/",
        json={
            "organization_id": TEST_ORGANIZATION_ID,
            "address": "Av. da Liberdade 10, Lisboa",
            "listing_type": "sale",
            "typology": "house",
        },
        headers=headers,
    )
    assert resp.status_code == 201
    return resp.json()["id"]


def _mock_structured_llm(return_value):
    """Create a mock that mimics ChatOpenAI.with_structured_output().ainvoke()."""
    structured_llm = AsyncMock()
    structured_llm.ainvoke = AsyncMock(return_value=return_value)
    mock_llm = MagicMock()
    mock_llm.with_structured_output = MagicMock(return_value=structured_llm)
    return mock_llm


class TestExtractFromDocumentWithOpenAI:
    async def test_successful_extraction(self, openai_client, openai_auth_headers, id_extractor):
        property_id = await _create_property(openai_client, openai_auth_headers)

        with patch(
            "property_management.adapters.ai.openai_id_document_extractor.ChatOpenAI"
        ) as mock_cls:
            mock_cls.return_value = _mock_structured_llm(EXTRACTED_OWNER)

            response = await openai_client.post(
                "/api/v1/admin/property-owners/extract-from-document",
                data={"property_id": property_id, "organization_id": TEST_ORGANIZATION_ID},
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

    async def test_extraction_with_null_issuing_district(
        self, openai_client, openai_auth_headers, id_extractor
    ):
        property_id = await _create_property(openai_client, openai_auth_headers)

        extracted = IdOwnerSchema(
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

        with patch(
            "property_management.adapters.ai.openai_id_document_extractor.ChatOpenAI"
        ) as mock_cls:
            mock_cls.return_value = _mock_structured_llm(extracted)

            response = await openai_client.post(
                "/api/v1/admin/property-owners/extract-from-document",
                data={"property_id": property_id, "organization_id": TEST_ORGANIZATION_ID},
                files={"file": ("passport.jpg", b"fake-data", "image/jpeg")},
                headers=openai_auth_headers,
            )

        assert response.status_code == 201
        owner = response.json()["owners"][0]
        assert owner["issuing_district"] is None
        assert owner["document_type"] == "passport"

    async def test_extraction_ai_error(self, openai_client, openai_auth_headers, id_extractor):
        property_id = await _create_property(openai_client, openai_auth_headers)

        with patch(
            "property_management.adapters.ai.openai_id_document_extractor.ChatOpenAI"
        ) as mock_cls:
            structured = AsyncMock()
            structured.ainvoke = AsyncMock(side_effect=Exception("API rate limit exceeded"))
            mock_llm = MagicMock()
            mock_llm.with_structured_output = MagicMock(return_value=structured)
            mock_cls.return_value = mock_llm

            response = await openai_client.post(
                "/api/v1/admin/property-owners/extract-from-document",
                data={"property_id": property_id, "organization_id": TEST_ORGANIZATION_ID},
                files={"file": ("doc.jpg", b"fake", "image/jpeg")},
                headers=openai_auth_headers,
            )

        assert response.status_code == 422
        assert "AI ID extraction failed" in response.json()["detail"]

    async def test_extraction_invalid_civil_status(
        self, openai_client, openai_auth_headers, id_extractor
    ):
        """OpenAI returns a civil_status value not in our enum."""
        property_id = await _create_property(openai_client, openai_auth_headers)

        extracted = IdOwnerSchema(
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

        with patch(
            "property_management.adapters.ai.openai_id_document_extractor.ChatOpenAI"
        ) as mock_cls:
            mock_cls.return_value = _mock_structured_llm(extracted)

            response = await openai_client.post(
                "/api/v1/admin/property-owners/extract-from-document",
                data={"property_id": property_id, "organization_id": TEST_ORGANIZATION_ID},
                files={"file": ("doc.jpg", b"fake", "image/jpeg")},
                headers=openai_auth_headers,
            )

        assert response.status_code == 422
        assert "Invalid extracted data" in response.json()["detail"]

    async def test_extraction_property_not_found(
        self, openai_client, openai_auth_headers, id_extractor
    ):
        response = await openai_client.post(
            "/api/v1/admin/property-owners/extract-from-document",
            data={
                "property_id": "00000000-0000-0000-0000-000000000099",
                "organization_id": TEST_ORGANIZATION_ID,
            },
            files={"file": ("doc.jpg", b"fake", "image/jpeg")},
            headers=openai_auth_headers,
        )

        assert response.status_code == 404

    async def test_extraction_not_authorized(
        self, openai_client, openai_auth_headers, id_extractor
    ):
        property_id = await _create_property(openai_client, openai_auth_headers)

        response = await openai_client.post(
            "/api/v1/admin/property-owners/extract-from-document",
            data={
                "property_id": property_id,
                "organization_id": "00000000-0000-0000-0000-000000000099",
            },
            files={"file": ("doc.jpg", b"fake", "image/jpeg")},
            headers=openai_auth_headers,
        )

        assert response.status_code == 403
