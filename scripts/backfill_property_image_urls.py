"""Backfill `property_images.url` for rows created before the column existed.

Reads every row whose `url` is NULL, computes the public URL from `s3_key`
via the configured `S3DocumentStorage`, and writes it back. Idempotent —
re-running is a no-op once everything is populated.

Usage:
    uv run python scripts/backfill_property_image_urls.py
"""

from __future__ import annotations

import asyncio
import sys

from supabase import acreate_client

from shared.adapters.s3_document_storage import S3DocumentStorage
from shared.config import settings


async def main() -> int:
    if not settings.supabase_url or not settings.supabase_service_role_key:
        print("ERROR: SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY required", file=sys.stderr)
        return 2

    client = await acreate_client(settings.supabase_url, settings.supabase_service_role_key)
    storage = S3DocumentStorage(
        bucket_name=settings.s3_bucket_name,
        region=settings.aws_region,
        endpoint_url=settings.aws_endpoint_url,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
    )

    rows = (
        await client.table("property_images").select("id,s3_key,url").is_("url", "null").execute()
    )
    pending = rows.data or []
    print(f"found {len(pending)} rows with NULL url")

    updated = 0
    for row in pending:
        url = storage.get_public_url(row["s3_key"])
        await client.table("property_images").update({"url": url}).eq("id", row["id"]).execute()
        updated += 1
        if updated % 25 == 0:
            print(f"  {updated}/{len(pending)}")

    print(f"done — updated {updated} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
