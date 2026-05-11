"""Seed property fixtures end-to-end through the admin HTTP API.

Reads JSON fixtures from `static_data/properties/*.json`, then for each
property runs the full creation flow as the admin dashboard would:

  POST /properties           → create DRAFT
  POST /property-owners      → owner (required for publish)
  POST /property-prices      → price (required for publish)
  POST /property-images/*    → presign → PUT image → record (×N images)
  POST /properties/{id}/publish   → flip to ACTIVE; emits PROPERTY_PUBLISHED.v1
  POST /properties/{id}/enrich    → POI auto-discovery (skipped if no coords)

The publish step triggers the listings projector + address enrichment
asynchronously; coordinates land on the `property_listings` projection
(not on the source `Property`), so `/enrich` only fires successfully if
coordinates were populated through the extraction flow. Set
`--skip-enrich` to suppress 422s.

Auth: forges a Supabase-style HS256 JWT using `SUPABASE_JWT_SECRET` and
the user's `auth.users.id`. Looks up `supabase_user_id` from the local
DB via the internal `User.id`. The org's membership check passes once
the JWT subject hits the in-process IdentityMiddleware.

Images: fetched at runtime from `https://picsum.photos/seed/<seed>/...`
so we don't have to commit binary fixtures. Each property uses a stable
seed (the property's `key`) so re-runs are deterministic per S3 layout.

Usage:
  uv run python scripts/seed_properties.py --user-id <uuid> --org-id <uuid>
  uv run python scripts/seed_properties.py --user-id ... --org-id ... \
      --typology apartment --listing-type sale
  uv run python scripts/seed_properties.py --user-id ... --org-id ... \
      --limit 2 --images-per-property 3 --skip-enrich
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from uuid import UUID

import httpx
import jwt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

# Make `src/` importable so we can reuse Settings.
ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from shared.config import Settings  # noqa: E402  (sys.path manipulation above)

DEFAULT_API_BASE = "http://localhost:8000"

FIXTURE_DIR = ROOT / "static_data" / "properties"
PICSUM_URL = "https://picsum.photos/seed/{seed}/1200/800.jpg"


async def lookup_supabase_user_id(database_url: str, user_id: UUID) -> str:
    """Translate internal `User.id` → `auth.users.id` for JWT forging."""
    # Settings.database_url uses an async driver scheme already; if it
    # was set to a sync `postgresql://` URL fall back manually.
    async_url = database_url
    if async_url.startswith("postgresql://"):
        async_url = async_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(async_url)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text("SELECT supabase_user_id FROM users WHERE id = :id"),
                {"id": str(user_id)},
            )
            row = result.first()
    finally:
        await engine.dispose()
    if not row:
        raise RuntimeError(
            f"User {user_id} not found in `users` table — cannot seed."
        )
    return row[0]


def forge_jwt(supabase_user_id: str, secret: str, ttl_seconds: int = 3600) -> str:
    """HS256 JWT matching what `JWTAuthMiddleware` accepts as a fallback.

    Mirrors the Supabase access-token shape: `sub` is the auth-users
    UUID, `aud` is `authenticated`. The middleware only reads `sub`.
    """
    now = int(time.time())
    payload = {
        "sub": supabase_user_id,
        "aud": "authenticated",
        "role": "authenticated",
        "iat": now,
        "exp": now + ttl_seconds,
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def load_fixtures(typology: str | None) -> list[dict]:
    """Read all JSON fixture files in `static_data/properties/`.

    Each file's top-level shape is `{ "typology": "...", "properties": [...] }`.
    Returns a flat list of property dicts with `typology` baked in so the
    caller doesn't have to read the parent file name.
    """
    out: list[dict] = []
    files = sorted(FIXTURE_DIR.glob("*.json"))
    if not files:
        raise RuntimeError(f"No fixture files found in {FIXTURE_DIR}")
    for path in files:
        with path.open() as f:
            data = json.load(f)
        file_typology = data.get("typology") or path.stem
        if typology and file_typology != typology:
            continue
        for prop in data.get("properties", []):
            prop["typology"] = file_typology
            out.append(prop)
    return out


async def fetch_image(client: httpx.AsyncClient, seed: str) -> bytes:
    """Pull a deterministic JPEG from picsum.photos."""
    url = PICSUM_URL.format(seed=seed)
    # picsum redirects via 302 to fastly; follow.
    response = await client.get(url, follow_redirects=True, timeout=30.0)
    response.raise_for_status()
    return response.content


async def create_property(
    api: httpx.AsyncClient, org_id: str, prop: dict
) -> str:
    response = await api.post(
        "/api/v1/admin/properties/",
        json={
            "organization_id": org_id,
            "address": prop["address"],
            "listing_type": prop["listing_type"],
            "typology": prop["typology"],
            "description": prop.get("description"),
        },
    )
    response.raise_for_status()
    return response.json()["id"]


async def create_owner(
    api: httpx.AsyncClient, org_id: str, property_id: str, owner: dict
) -> None:
    payload = {
        "organization_id": org_id,
        "property_id": property_id,
        "full_name": owner["full_name"],
        "civil_status": owner.get("civil_status", "single"),
        "address": owner.get("address", "Morada por confirmar"),
        "nif": owner["nif"],
        "document_type": owner.get("document_type", "cartao_cidadao"),
        "document_id": owner["document_id"],
        "issued_by": owner["issued_by"],
        "issuing_district": owner.get("issuing_district"),
        "date_of_birth": owner["date_of_birth"],
    }
    response = await api.post("/api/v1/admin/property-owners/", json=payload)
    response.raise_for_status()


async def create_price(
    api: httpx.AsyncClient,
    org_id: str,
    property_id: str,
    amount: float,
    listing_type: str,
) -> None:
    response = await api.post(
        "/api/v1/admin/property-prices/",
        json={
            "organization_id": org_id,
            "property_id": property_id,
            "amount": amount,
            "listing_type": listing_type,
        },
    )
    response.raise_for_status()


async def upload_images(
    api: httpx.AsyncClient,
    image_client: httpx.AsyncClient,
    org_id: str,
    property_id: str,
    key: str,
    count: int,
) -> int:
    """Presign → PUT to S3 → record. Returns the number of images uploaded.

    Done one-image-at-a-time so a single failed download doesn't abort
    the whole batch — the property still publishes if at least one image
    lands.
    """
    uploaded = 0
    for i in range(count):
        seed = f"{key}-{i}"
        try:
            image_bytes = await fetch_image(image_client, seed)
        except httpx.HTTPError as exc:
            print(f"    [warn] image {seed} download failed: {exc}")
            continue

        filename = f"{seed}.jpg"
        presign_resp = await api.post(
            "/api/v1/admin/property-images/presign",
            json={
                "organization_id": org_id,
                "property_id": property_id,
                "files": [{"filename": filename, "content_type": "image/jpeg"}],
            },
        )
        presign_resp.raise_for_status()
        file_meta = presign_resp.json()["files"][0]

        # PUT directly to S3 via the presigned URL — bypass api client
        # so we don't send the Authorization header to S3.
        put_resp = await image_client.put(
            file_meta["upload_url"],
            content=image_bytes,
            headers={"Content-Type": "image/jpeg"},
            timeout=60.0,
        )
        put_resp.raise_for_status()

        record_resp = await api.post(
            "/api/v1/admin/property-images/",
            json={
                "organization_id": org_id,
                "property_id": property_id,
                "image_id": file_meta["image_id"],
                "s3_key": file_meta["s3_key"],
                "filename": filename,
                "content_type": "image/jpeg",
                "size_bytes": len(image_bytes),
            },
        )
        record_resp.raise_for_status()
        uploaded += 1

    return uploaded


async def publish(api: httpx.AsyncClient, org_id: str, property_id: str) -> None:
    response = await api.post(
        f"/api/v1/admin/properties/{property_id}/publish",
        params={"organization_id": org_id},
    )
    response.raise_for_status()


async def enrich(api: httpx.AsyncClient, org_id: str, property_id: str) -> bool:
    """Best-effort POI auto-discovery trigger.

    422 (missing coordinates) is expected when the property was created
    via the seeder rather than the extraction flow — return False so the
    caller can keep going without treating it as a fatal error.
    """
    response = await api.post(
        f"/api/v1/admin/properties/{property_id}/enrich",
        params={"organization_id": org_id},
        json={"force": False},
    )
    if response.status_code == 422:
        return False
    response.raise_for_status()
    return True


async def seed_one(
    api: httpx.AsyncClient,
    image_client: httpx.AsyncClient,
    org_id: str,
    prop: dict,
    images_per_property: int,
    skip_enrich: bool,
) -> None:
    key = prop["key"]
    print(f"\n→ {key} ({prop['typology']} / {prop['listing_type']}) — {prop['address']}")

    property_id = await create_property(api, org_id, prop)
    print(f"  created property_id={property_id}")

    await create_owner(api, org_id, property_id, prop["owner"])
    print(f"  + owner {prop['owner']['full_name']}")

    await create_price(api, org_id, property_id, prop["price"], prop["listing_type"])
    print(f"  + price €{prop['price']:,.0f}")

    uploaded = await upload_images(
        api, image_client, org_id, property_id, key, images_per_property
    )
    print(f"  + {uploaded}/{images_per_property} images")

    if uploaded == 0:
        print("  [skip] no images uploaded — publish would 422 on missing_image")
        return

    await publish(api, org_id, property_id)
    print("  published (PROPERTY_PUBLISHED.v1 emitted)")

    if skip_enrich:
        return
    triggered = await enrich(api, org_id, property_id)
    if triggered:
        print("  enrichment queued")
    else:
        print(
            "  enrichment skipped — property has no coordinates "
            "(would need the extraction flow to populate lat/lng)"
        )


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-base", default=DEFAULT_API_BASE)
    parser.add_argument(
        "--user-id",
        required=True,
        help="Internal User.id (UUID) — used to resolve auth.users.id for JWT forging",
    )
    parser.add_argument(
        "--org-id",
        required=True,
        help="Organization UUID the user has membership in",
    )
    parser.add_argument(
        "--typology",
        choices=["house", "apartment", "land", "ruin"],
        help="Filter to a single typology",
    )
    parser.add_argument(
        "--listing-type",
        choices=["sale", "purchase"],
        help="Filter to a single listing type",
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--images-per-property", type=int, default=4)
    parser.add_argument("--skip-enrich", action="store_true")
    args = parser.parse_args()

    settings = Settings()
    if not settings.supabase_jwt_secret:
        print("error: SUPABASE_JWT_SECRET not set in env", file=sys.stderr)
        return 1
    if not settings.database_url:
        print("error: DATABASE_URL not set in env", file=sys.stderr)
        return 1

    supabase_user_id = await lookup_supabase_user_id(
        settings.database_url, UUID(args.user_id)
    )
    print(f"resolved auth.users.id: {supabase_user_id}")

    token = forge_jwt(supabase_user_id, settings.supabase_jwt_secret)

    fixtures = load_fixtures(args.typology)
    if args.listing_type:
        fixtures = [p for p in fixtures if p["listing_type"] == args.listing_type]
    if args.limit is not None:
        fixtures = fixtures[: args.limit]
    print(f"loaded {len(fixtures)} fixtures")

    async with (
        httpx.AsyncClient(
            base_url=args.api_base,
            headers={"Authorization": f"Bearer {token}"},
            timeout=30.0,
        ) as api,
        httpx.AsyncClient() as image_client,
    ):
        ok = 0
        failed = 0
        for prop in fixtures:
            try:
                await seed_one(
                    api,
                    image_client,
                    args.org_id,
                    prop,
                    args.images_per_property,
                    args.skip_enrich,
                )
                ok += 1
            except httpx.HTTPStatusError as exc:
                failed += 1
                body = exc.response.text[:500]
                print(
                    f"  [error] {exc.request.method} {exc.request.url} "
                    f"→ {exc.response.status_code}: {body}"
                )
            except Exception as exc:
                failed += 1
                print(f"  [error] {type(exc).__name__}: {exc}")

    print(f"\ndone: {ok} ok, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
