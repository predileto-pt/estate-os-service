"""Embedding handler — driven by `PROPERTY_LISTING_UPDATED.v1`.

Composes canonical text from the freshly-projected `property_listings`
row, hash-checks against the persisted `(text_hash, version, model)`
tuple, and on mismatch embeds + upserts to the vector index. Two
independent code paths run on every event (ADR-013 §2c):

1. **Text path.** If the new tuple differs from the persisted one, or
   the row is in `FAILED` state, re-embed and upsert. Persists the new
   tuple + flips status to `INDEXED` atomically.
2. **Metadata path.** If text is unchanged but a metadata field
   changed (notably `status` flipping to WITHDRAWN/SOLD), call
   `update_metadata` so stage-1 filtering excludes the listing without
   wasting an embed call.

Failure path: row state flips to `FAILED`, exception re-raised so SQS
redrives. After `maxReceiveCount=5` (ADR-008) the message DLQs and the
row sits at FAILED until ops investigates. The listing remains visible
in the public structured-filter query — embedding state is best-effort.

Gate: when `vector_index` or `embedding_provider` is None on the
container (i.e. `LISTINGS_EMBEDDING_ENABLED=false`), the handler is a
no-op and the message is acknowledged. This is how staged rollouts
work: ship the code with the gate off, flip in staging, observe, then
flip in prod.

Also handles `PROPERTY_LISTING_DELETED.v1` — deletes the vector by
listing id from the configured namespace.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import structlog

from listings.application.services.canonical_text import compose_canonical_text
from listings.domain.property_listing import PropertyListing
from shared.events.base import DomainEvent

log = structlog.get_logger()


async def handle_listing_embedding(event: DomainEvent, context: dict) -> None:
    listings = context["listings"]
    vector_index = listings.vector_index
    embedding_provider = listings.embedding_provider
    if vector_index is None or embedding_provider is None:
        # Gate disabled — message acknowledged without work.
        log.debug(
            "listing_embedding.gate_disabled",
            property_id=event.data.get("property_id"),
        )
        return

    namespace: str = listings.vector_index_namespace
    embedding_model_version: str = listings.embedding_model_version

    property_id = UUID(event.data["property_id"])
    row = await listings.property_listing_repo.get_by_id(property_id)
    if row is None:
        log.info("listing_embedding.row_gone", property_id=str(property_id))
        return

    canonical = compose_canonical_text(row)
    persisted_tuple = (
        row.embedding_text_hash,
        row.canonical_text_version,
        row.embedding_model_version,
    )
    new_tuple = (canonical.hash, canonical.version, embedding_model_version)
    needs_reembed = persisted_tuple != new_tuple or row.embedding_status == "FAILED"

    metadata = _index_metadata(row)

    try:
        if needs_reembed:
            vector = await embedding_provider.embed(canonical.text)
            await vector_index.upsert(
                vector_id=str(property_id),
                vector=vector,
                metadata=metadata,
                namespace=namespace,
            )
            await listings.property_listing_repo.set_embedding_indexed(
                property_id=property_id,
                embedding_text_hash=canonical.hash,
                canonical_text_version=canonical.version,
                embedding_model_version=embedding_model_version,
                embedded_at=datetime.now(timezone.utc),
            )
            log.info(
                "listing_embedding.indexed",
                property_id=str(property_id),
                text_hash=canonical.hash,
            )
        else:
            # Hash unchanged — only metadata could have drifted.
            await vector_index.update_metadata(
                vector_id=str(property_id),
                metadata=metadata,
                namespace=namespace,
            )
            log.debug(
                "listing_embedding.metadata_only",
                property_id=str(property_id),
            )
    except Exception:
        await listings.property_listing_repo.set_embedding_status(
            property_id=property_id, status="FAILED"
        )
        log.exception("listing_embedding.failed", property_id=str(property_id))
        raise


async def handle_listing_deleted(event: DomainEvent, context: dict) -> None:
    """Delete the listing's vector from the index. No-op when the gate
    is disabled."""
    listings = context["listings"]
    vector_index = listings.vector_index
    if vector_index is None:
        return
    namespace: str = listings.vector_index_namespace
    property_id = event.data["property_id"]
    await vector_index.delete(vector_id=property_id, namespace=namespace)
    log.info("listing_embedding.deleted", property_id=property_id)


def _index_metadata(row: PropertyListing) -> dict:
    """`LISTING_INDEX_METADATA_V1` (ADR-013 §3b) — the structured fields
    stored alongside the vector for stage-1 filtering. None values are
    dropped so the metadata stays compact (Pinecone has a 40KB cap).
    Strings are lowercased and trimmed where the spec calls for it."""
    raw = {
        "listing_id": str(row.id),
        "property_id": str(row.id),  # 1:1 with listing in v1
        "organization_id": str(row.organization_id),
        "parish": row.parish.lower().strip() if row.parish else None,
        "municipality": (row.municipality.lower().strip() if row.municipality else None),
        "district": row.district.lower().strip() if row.district else None,
        "listing_type": row.listing_type.value,
        "typology": row.typology.value,
        "status": row.status.value,
        "price_eur": float(row.min_price) if row.min_price is not None else None,
    }
    return {k: v for k, v in raw.items() if v is not None}
