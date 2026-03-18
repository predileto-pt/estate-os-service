from datetime import date
from decimal import Decimal
from uuid import UUID

from supabase import AsyncClient

from property_management.application.ports.repositories.property_repository import (
    PropertyRepository,
)
from property_management.domain.models.property import (
    ListingType,
    Property,
    PropertyStatus,
    Typology,
)
from property_management.domain.models.property_owner import (
    CivilStatus,
    DocumentType,
    PropertyOwner,
)
from property_management.domain.models.property_price import PropertyPrice


class SupabasePropertyRepository(PropertyRepository):
    def __init__(self, client: AsyncClient) -> None:
        self._client = client

    def _owner_to_domain(self, row: dict) -> PropertyOwner:
        dob = row.get("date_of_birth")
        if isinstance(dob, str):
            dob = date.fromisoformat(dob)
        civil_status_raw = row.get("civil_status")
        doc_type_raw = row.get("document_type")
        return PropertyOwner(
            id=UUID(row["id"]),
            property_id=UUID(row["property_id"]),
            full_name=row["full_name"],
            civil_status=CivilStatus(civil_status_raw) if civil_status_raw else None,
            address=row["address"],
            nif=row["nif"],
            document_type=DocumentType(doc_type_raw) if doc_type_raw else None,
            document_id=row.get("document_id"),
            issued_by=row.get("issued_by"),
            issuing_district=row.get("issuing_district"),
            date_of_birth=dob,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _owner_to_row(self, owner: PropertyOwner) -> dict:
        return {
            "id": str(owner.id),
            "property_id": str(owner.property_id),
            "full_name": owner.full_name,
            "civil_status": owner.civil_status.value if owner.civil_status else None,
            "address": owner.address,
            "nif": owner.nif,
            "document_type": owner.document_type.value if owner.document_type else None,
            "document_id": owner.document_id,
            "issued_by": owner.issued_by,
            "issuing_district": owner.issuing_district,
            "date_of_birth": owner.date_of_birth.isoformat() if owner.date_of_birth else None,
        }

    def _price_to_domain(self, row: dict) -> PropertyPrice:
        return PropertyPrice(
            id=UUID(row["id"]),
            property_id=UUID(row["property_id"]),
            amount=Decimal(str(row["amount"])),
            listing_type=ListingType(row["listing_type"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _price_to_row(self, price: PropertyPrice) -> dict:
        return {
            "id": str(price.id),
            "property_id": str(price.property_id),
            "amount": str(price.amount),
            "listing_type": price.listing_type.value,
        }

    def _to_domain(
        self,
        row: dict,
        owner_rows: list[dict] | None = None,
        price_rows: list[dict] | None = None,
    ) -> Property:
        owners = [self._owner_to_domain(o) for o in (owner_rows or [])]
        prices = [self._price_to_domain(p) for p in (price_rows or [])]
        return Property(
            id=UUID(row["id"]),
            organization_id=UUID(row["organization_id"]),
            address=row["address"],
            listing_type=ListingType(row["listing_type"]),
            typology=Typology(row["typology"]),
            status=PropertyStatus(row["status"]),
            description=row.get("description"),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            latitude=row.get("latitude"),
            longitude=row.get("longitude"),
            owners=owners,
            prices=prices,
        )

    def _to_row(self, prop: Property) -> dict:
        return {
            "id": str(prop.id),
            "organization_id": str(prop.organization_id),
            "address": prop.address,
            "listing_type": prop.listing_type.value,
            "typology": prop.typology.value,
            "status": prop.status.value,
            "description": prop.description,
            "latitude": prop.latitude,
            "longitude": prop.longitude,
        }

    async def _load_owners(self, property_id: str) -> list[dict]:
        result = (
            await self._client.table("property_owners")
            .select("*")
            .eq("property_id", property_id)
            .order("created_at", desc=True)
            .execute()
        )
        return result.data

    async def _load_prices(self, property_id: str) -> list[dict]:
        result = (
            await self._client.table("property_prices")
            .select("*")
            .eq("property_id", property_id)
            .order("created_at", desc=True)
            .execute()
        )
        return result.data

    async def get_by_id(self, property_id: UUID) -> Property | None:
        result = (
            await self._client.table("properties").select("*").eq("id", str(property_id)).execute()
        )
        if not result.data:
            return None
        owner_rows = await self._load_owners(str(property_id))
        price_rows = await self._load_prices(str(property_id))
        return self._to_domain(result.data[0], owner_rows, price_rows)

    async def list_by_organization(self, organization_id: UUID) -> list[Property]:
        result = (
            await self._client.table("properties")
            .select("*")
            .eq("organization_id", str(organization_id))
            .order("created_at", desc=True)
            .execute()
        )
        props = []
        for row in result.data:
            owner_rows = await self._load_owners(row["id"])
            price_rows = await self._load_prices(row["id"])
            props.append(self._to_domain(row, owner_rows, price_rows))
        return props

    async def save(self, prop: Property) -> Property:
        result = await self._client.table("properties").insert(self._to_row(prop)).execute()
        return self._to_domain(result.data[0], [])

    async def save_owner(self, prop: Property, owner: PropertyOwner) -> Property:
        await self._client.table("property_owners").insert(self._owner_to_row(owner)).execute()
        prop.add_owner(owner)
        return prop

    async def save_price(self, prop: Property, price: PropertyPrice) -> Property:
        await self._client.table("property_prices").insert(self._price_to_row(price)).execute()
        prop.add_price(price)
        return prop
