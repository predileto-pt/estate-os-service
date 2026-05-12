from datetime import date
from decimal import Decimal
from uuid import UUID

import structlog
from supabase import AsyncClient

from properties.application.ports.repositories.property_repository import (
    PropertyRepository,
)
from properties.domain.models.property import (
    ListingType,
    Property,
    PropertyStatus,
    Typology,
)
from properties.domain.models.property_image import PropertyImage
from properties.domain.models.property_owner import (
    CivilStatus,
    DocumentType,
    PropertyOwner,
)
from properties.domain.models.property_price import PropertyPrice

log = structlog.get_logger()


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
            email=row.get("email"),
            phone_number=row.get("phone_number"),
            email_verified=row.get("email_verified", False),
            phone_verified=row.get("phone_verified", False),
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
            "email": owner.email,
            "phone_number": owner.phone_number,
            "email_verified": owner.email_verified,
            "phone_verified": owner.phone_verified,
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

    def _image_to_domain(self, row: dict) -> PropertyImage:
        return PropertyImage(
            id=UUID(row["id"]),
            property_id=UUID(row["property_id"]),
            s3_key=row["s3_key"],
            filename=row["filename"],
            content_type=row["content_type"],
            size_bytes=row["size_bytes"],
            display_order=row["display_order"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            # `.get()` so rows created before the `url` column existed
            # don't crash the read path. They return "" — the FE renders
            # a placeholder until backfill or the next upload populates it.
            url=row.get("url") or "",
        )

    def _image_to_row(self, image: PropertyImage) -> dict:
        return {
            "id": str(image.id),
            "property_id": str(image.property_id),
            "s3_key": image.s3_key,
            "filename": image.filename,
            "content_type": image.content_type,
            "size_bytes": image.size_bytes,
            "display_order": image.display_order,
            "url": image.url,
        }

    def _to_domain(
        self,
        row: dict,
        owner_rows: list[dict] | None = None,
        price_rows: list[dict] | None = None,
        image_rows: list[dict] | None = None,
    ) -> Property:
        owners = [self._owner_to_domain(o) for o in (owner_rows or [])]
        prices = [self._price_to_domain(p) for p in (price_rows or [])]
        images = [self._image_to_domain(i) for i in (image_rows or [])]
        return Property(
            id=UUID(row["id"]),
            organization_id=UUID(row["organization_id"]),
            title=row["title"],
            address=row["address"],
            listing_type=ListingType(row["listing_type"]),
            typology=Typology(row["typology"]),
            status=PropertyStatus(row["status"]),
            description=row.get("description"),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            latitude=row.get("latitude"),
            longitude=row.get("longitude"),
            # Read aggregate_version from the row; without this it
            # defaults to 0 and `bump_aggregate_version` does
            # `0 + 1 = 1` on every call, perpetually. Then the
            # listings projector rejects every event for being equal
            # to the stored version and `property_listings.pois`
            # stays at its initial empty state. Spec
            # `2026-05-listing-semantic-search` debugging session.
            aggregate_version=row.get("aggregate_version", 0),
            owners=owners,
            prices=prices,
            images=images,
        )

    def _to_row(self, prop: Property) -> dict:
        return {
            "id": str(prop.id),
            "organization_id": str(prop.organization_id),
            "title": prop.title,
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

    async def _load_images(self, property_id: str) -> list[dict]:
        result = (
            await self._client.table("property_images")
            .select("*")
            .eq("property_id", property_id)
            .order("display_order", desc=False)
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

    # PostgREST resource-embedding via supabase-py: one HTTP request
    # returns properties with their owners/prices/images nested. Replaces
    # the previous 1 + 3N round-trip pattern that was hitting the 10s timeout.
    _EMBEDDED_SELECT = (
        "*, property_owners(*), property_prices(*), property_images(*)"
    )

    def _unpack_embedded(self, row: dict) -> tuple[dict, list[dict], list[dict], list[dict]]:
        owners = sorted(
            row.pop("property_owners", None) or [],
            key=lambda o: o.get("created_at", ""),
            reverse=True,
        )
        prices = sorted(
            row.pop("property_prices", None) or [],
            key=lambda p: p.get("created_at", ""),
            reverse=True,
        )
        images = sorted(
            row.pop("property_images", None) or [],
            key=lambda i: i.get("display_order", 0),
        )
        return row, owners, prices, images

    async def get_by_id(self, property_id: UUID) -> Property | None:
        result = (
            await self._client.table("properties")
            .select(self._EMBEDDED_SELECT)
            .eq("id", str(property_id))
            .execute()
        )
        if not result.data:
            return None
        row, owners, prices, images = self._unpack_embedded(result.data[0])
        return self._to_domain(row, owners, prices, images)

    async def list_by_organization(self, organization_id: UUID) -> list[Property]:
        result = (
            await self._client.table("properties")
            .select(self._EMBEDDED_SELECT)
            .eq("organization_id", str(organization_id))
            .order("created_at", desc=True)
            .execute()
        )
        props = []
        for raw in result.data:
            row, owners, prices, images = self._unpack_embedded(raw)
            props.append(self._to_domain(row, owners, prices, images))
        return props

    async def list_active(self) -> list[Property]:
        result = (
            await self._client.table("properties")
            .select(self._EMBEDDED_SELECT)
            .eq("status", PropertyStatus.ACTIVE.value)
            .order("created_at", desc=True)
            .execute()
        )
        props = []
        for raw in result.data:
            row, owners, prices, images = self._unpack_embedded(raw)
            props.append(self._to_domain(row, owners, prices, images))
        return props

    async def save(self, prop: Property) -> Property:
        result = await self._client.table("properties").insert(self._to_row(prop)).execute()
        return self._to_domain(result.data[0], [])

    async def save_owner(self, prop: Property, owner: PropertyOwner) -> Property:
        await self._client.table("property_owners").insert(self._owner_to_row(owner)).execute()
        prop.add_owner(owner)
        return prop

    async def update_owner(self, prop: Property, owner: PropertyOwner) -> Property:
        await (
            self._client.table("property_owners")
            .update(
                {
                    "email": owner.email,
                    "phone_number": owner.phone_number,
                    "email_verified": owner.email_verified,
                    "phone_verified": owner.phone_verified,
                }
            )
            .eq("id", str(owner.id))
            .execute()
        )
        prop.owners = [owner if o.id == owner.id else o for o in prop.owners]
        return prop

    async def save_price(self, prop: Property, price: PropertyPrice) -> Property:
        await self._client.table("property_prices").insert(self._price_to_row(price)).execute()
        prop.add_price(price)
        return prop

    async def save_image(self, prop: Property, image: PropertyImage) -> Property:
        await self._client.table("property_images").insert(self._image_to_row(image)).execute()
        prop.add_image(image)
        return prop

    async def delete_image(self, prop: Property, image_id: UUID) -> Property:
        await self._client.table("property_images").delete().eq("id", str(image_id)).execute()
        prop.remove_image(image_id)
        return prop

    async def update_image_orders(
        self, prop: Property, image_orders: list[tuple[UUID, int]]
    ) -> Property:
        for image_id, order in image_orders:
            await (
                self._client.table("property_images")
                .update({"display_order": order})
                .eq("id", str(image_id))
                .execute()
            )
        # Reload images in correct order
        image_rows = await self._load_images(str(prop.id))
        prop.images = [self._image_to_domain(r) for r in image_rows]
        return prop

    async def delete(self, property_id: UUID) -> None:
        pid = str(property_id)
        # Delete child rows first to satisfy FK constraints (no ondelete=CASCADE).
        # extraction_jobs.property_id is nullable and handled separately by
        # ExtractionJobRepository.delete_by_property_id().
        for table in (
            "property_amenities",
            "property_owners",
            "property_prices",
            "property_images",
        ):
            await self._client.table(table).delete().eq("property_id", pid).execute()
        await self._client.table("properties").delete().eq("id", pid).execute()

    async def update_status(self, property_id: UUID, status: PropertyStatus) -> None:
        from datetime import datetime, timezone

        await (
            self._client.table("properties")
            .update(
                {
                    "status": status.value,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            .eq("id", str(property_id))
            .execute()
        )

    async def update_address(self, property_id: UUID, address: str) -> None:
        from datetime import datetime, timezone

        await (
            self._client.table("properties")
            .update(
                {
                    "address": address,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            .eq("id", str(property_id))
            .execute()
        )

    async def bump_aggregate_version(self, property_id: UUID) -> Property:
        # PostgREST can't do column arithmetic in updates — read-modify-write.
        # Two round-trips at worst; fine at our scale.
        from datetime import datetime, timezone

        from properties.domain.exceptions import PropertyNotFoundError

        prop = await self.get_by_id(property_id)
        if not prop:
            raise PropertyNotFoundError(str(property_id))
        new_version = prop.aggregate_version + 1
        result = await (
            self._client.table("properties")
            .update(
                {
                    "aggregate_version": new_version,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            .eq("id", str(property_id))
            .execute()
        )
        # Defense against silent RLS / PostgREST rejections — without
        # this, an empty `result.data` would still return a Property
        # with the bumped version, and downstream `emit_property_updated`
        # would publish a snapshot whose aggregate_version is ahead of
        # what's actually in the DB. Refuse to lie to the caller.
        if not result.data:
            raise RuntimeError(
                f"properties UPDATE returned 0 rows for property_id={property_id}. "
                "Possible causes: RLS policy denying writes, the row was deleted "
                "between the SELECT and the UPDATE, or PostgREST swallowing an error."
            )
        log.info(
            "property_repo.bump_aggregate_version",
            property_id=str(property_id),
            previous_version=prop.aggregate_version,
            new_version=new_version,
            returned_rows=len(result.data),
        )
        prop.aggregate_version = new_version
        return prop
