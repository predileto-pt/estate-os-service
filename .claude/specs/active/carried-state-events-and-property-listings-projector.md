# Carried-state domain events + PropertyListing read-model projector

**Status:** draft
**Owner:** Peter
**Created:** 2026-04-17

## Problem

Cross-context consumers that need property data currently re-read the write-side DB. The PROPERTY_CREATED event at `src/properties/application/use_cases/create_property.py:56-67` carries only `{"property_id": str(prop.id)}`; the consumer at `src/properties/adapters/workers/discovery_processor.py:12-24` re-fetches the aggregate. This creates three problems:

1. **Chatty and racy.** Consumer issues an extra DB round-trip per event and may see a state that is newer than what the producer intended to communicate.
2. **No PROPERTY_UPDATED / PROPERTY_DELETED events.** The write side can't broadcast state changes at all beyond creation. New consumers have no way to stay in sync without polling.
3. **No separate read-model for listings.** `src/listings/adapters/database/models.py:37-113` maps read-only to the **same** `properties` table via `extend_existing=True`. That forces listings to share the write-side schema, which blocks (a) denormalization for cheap filter queries, (b) structured-location columns that the write side doesn't need, and (c) any CQRS improvements down the line.

The follow-on spec `listings-cursor-pagination-and-filters.md` depends on having a proper read-model table (`property_listings`) with denormalized, indexed columns. This spec is the infrastructure that produces and maintains that table.

## Goal

`DomainEvent` supports carried-state metadata. Every state-mutating property use case emits a carried-state `PROPERTY_CREATED` / `PROPERTY_UPDATED` / `PROPERTY_DELETED`. The listings context owns a new `property_listings` table that a projector handler keeps in sync, with structured parish/municipality/district populated asynchronously by an LLM-backed address parser.

## Non-goals

- Changing `GET /api/v1/listings/properties` or its filter/pagination contract. That's the next spec.
- Deleting the legacy read-path (`ReadPropertyModel` at `src/listings/adapters/database/models.py:37-113`, the existing `ListingRepository` adapter, the existing `list_properties`/`get_property` use cases). During this spec they stay in place and remain wired through `listings/container.py` — the route still reads through them. The swap happens in the follow-on feature spec.
- Changing the write-side `Property.address` schema. Address stays as a single `str` on the aggregate and inside event payloads. Structured location is a **read-side materialisation only**.
- Event sourcing. We emit events for sync, not for reconstruction. The write-side DB remains authoritative.
- Applying this pattern to other bounded contexts (customers, bookings). Properties only.
- The outbox pattern. We'll rely on the existing "publish from use case, log-and-continue on publish failure" pattern (see `create_property.py:63-67`) — an outbox is a future spec if we start losing events in practice.

## Depends on

- **ADR-008** (`docs/adr/008-event-bus-ports-and-fanout.md`) accepted.
- **`event-bus-ports-and-fanout-foundation.md` must ship first.** The foundation spec provides (a) the single `DomainEvent` class, (b) the shared ADR-006-compliant `SQSWorker`, (c) SNS fan-out with per-context SQS queues + DLQs, (d) the versioned event-type convention, (e) per-context worker CLI pattern. Without it, this spec has nowhere to register the projector handler and no DLQ to contain LLM parse failures.
- Listings context gains its own worker CLI (`src/listings/entrypoints/events_worker.py`) during the foundation spec; this spec registers the projector + enrichment handlers on it.

## Approach

### No envelope change

The `DomainEvent` envelope stays as it is today — 4 fields (`event_type`, `data`, `event_id`, `occurred_at`). Per ADR-008, **versioning lives in the event type string** (e.g. `PROPERTY_CREATED.v1`). Schema evolution is "publish V2 alongside V1, migrate consumers, drop V1" — exactly how Kafka/RabbitMQ topic versioning works. No `schema_ref` / `schema_version` fields added.

### PROPERTY_CREATED.v1 is an **overwrite** of the existing payload

The existing `CreateProperty.execute()` already emits PROPERTY_CREATED with `{"property_id": ...}`. After the foundation spec renames the constant to `PROPERTY_CREATED_V1`, this spec changes the payload of `PROPERTY_CREATED.v1` in the same commit that updates its only current consumer (`discovery_processor.handle_property_created`). The new payload is the full carried-state snapshot (shape below). `property_id` becomes `data["id"]` — `discovery_processor` is updated to read from the new location.

**No v2 event type. No dual-write deprecation window.** One commit, both producer and consumer.

### Payload contract (event types: `PROPERTY_CREATED.v1`, `PROPERTY_UPDATED.v1`, `PROPERTY_DELETED.v1`)

Pinned JSON shape for all three event types:

```jsonc
{
  "event_type": "PROPERTY_CREATED.v1" | "PROPERTY_UPDATED.v1" | "PROPERTY_DELETED.v1",
  "event_id": "<uuid>",
  "occurred_at": "<iso>",
  "data": {
    "id": "<uuid>",
    "organization_id": "<uuid>",
    "aggregate_version": <int>,          // monotonic per-aggregate counter; source of idempotency
    "address": "<free-text string>",
    "listing_type": "sale" | "purchase",
    "typology": "house" | "apartment" | "land" | "ruin",
    "status": "draft" | "active" | "sold" | "rented" | "withdrawn",
    "description": "<str|null>",
    "latitude": <float|null>,
    "longitude": <float|null>,
    "characteristics": {
      "area_in_m2": <int|null>,
      "num_of_bedrooms": <int|null>,
      "num_of_bathrooms": <int|null>,
      "built_at": <int|null>,
      "energy_rating": "<str|null>",
      "floor": <int|null>,
      "parking_spaces": <int|null>,
      "has_elevator": <bool|null>,
      "has_garden": <bool|null>,
      "has_pool": <bool|null>
    },
    "prices": [{"amount": "<decimal-str>", "listing_type": "sale"|"purchase"}, ...],
    "images": [{"id": "<uuid>", "s3_key": "<str>", "display_order": <int>}, ...]
  }
}
```

For PROPERTY_DELETED.v1, `data` is the minimal `{id, organization_id, aggregate_version}` — the row is being removed, no snapshot needed.

**`aggregate_version`** is a new column on `properties` (`Integer NOT NULL DEFAULT 0`), incremented inside every state-mutating use case on the same transaction as the state change. It's the idempotency source for the projector (see below).

### Event emission sites

Per-use-case explicit `publisher.publish(...)`. The following use cases all emit events and therefore gain `event_publisher: EventPublisher | None = None` as a constructor dependency (the port from the foundation spec):

| Use case | Emits | File |
|---|---|---|
| `CreateProperty` | PROPERTY_CREATED | `src/properties/application/use_cases/create_property.py` |
| `DeleteProperty` | PROPERTY_DELETED | `src/properties/application/use_cases/delete_property.py` |
| `CreatePropertyOwner` | PROPERTY_UPDATED | `src/properties/application/use_cases/create_property_owner.py` |
| `UpdatePropertyOwnerContact` | PROPERTY_UPDATED | `src/properties/application/use_cases/update_property_owner_contact.py` |
| `ExtractPropertyOwnerFromDocument` | PROPERTY_UPDATED | `src/properties/application/use_cases/extract_property_owner_from_document.py` |
| `CreatePropertyPrice` | PROPERTY_UPDATED | `src/properties/application/use_cases/create_property_price.py` |
| `RecordPropertyImage` | PROPERTY_UPDATED | `src/properties/application/use_cases/record_property_image.py` |
| `DeletePropertyImage` | PROPERTY_UPDATED | `src/properties/application/use_cases/delete_property_image.py` |
| `ReorderPropertyImages` | PROPERTY_UPDATED | `src/properties/application/use_cases/reorder_property_images.py` |
| `ProcessPropertyExtraction` (and batch) | PROPERTY_UPDATED (on final `COMPLETED`) | `src/properties/application/use_cases/process_property_extraction.py` + `process_batch_property_extraction.py` |

Emission pattern is the same as the existing `create_property.py:56-67`: log-and-swallow on publish error, because persistence is already committed. A failed publish is a monitoring concern, not a transaction abort.

A single private helper on the properties container (or a shared module `src/properties/application/events/property_event.py`) builds the snapshot from a `Property` aggregate to avoid repeating the serialization in 10 places.

### Read-model table

New SQLAlchemy model at `src/listings/adapters/database/models.py`:

```python
class PropertyListingModel(Base):
    __tablename__ = "property_listings"

    id: Mapped[UUID] = mapped_column(primary_key=True)   # == properties.id
    organization_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    status: Mapped[PropertyStatus] = mapped_column(..., nullable=False, index=True)
    listing_type: Mapped[ListingType] = mapped_column(..., nullable=False, index=True)
    typology: Mapped[Typology] = mapped_column(..., nullable=False, index=True)

    # Raw free-text, carried through unchanged from the source event
    address: Mapped[str] = mapped_column(Text, nullable=False)

    # Populated asynchronously by the enrichment worker; NULL until enriched or for addresses the parser can't resolve
    parish: Mapped[str | None] = mapped_column(Text, index=True)
    municipality: Mapped[str | None] = mapped_column(Text, index=True)
    district: Mapped[str | None] = mapped_column(Text, index=True)
    location_enriched_at: Mapped[datetime | None] = mapped_column()
    location_enrichment_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))

    # Denormalized characteristic columns — dropped straight into indexed cols so filters hit b-trees, not JSONB
    num_of_bedrooms: Mapped[int | None] = mapped_column(index=True)
    num_of_bathrooms: Mapped[int | None] = mapped_column(index=True)
    area_in_m2: Mapped[int | None] = mapped_column(index=True)
    has_pool: Mapped[bool | None] = mapped_column(index=True)
    has_garden: Mapped[bool | None] = mapped_column(index=True)
    has_elevator: Mapped[bool | None] = mapped_column(index=True)

    # Price snapshot: single lowest-amount price per listing_type captured at event time
    min_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), index=True)

    # First image (display_order == 0) s3 key, for thumbnails
    first_image_s3_key: Mapped[str | None] = mapped_column(Text)

    description: Mapped[str | None] = mapped_column(Text)
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)

    # Idempotency + ordering
    source_aggregate_version: Mapped[int] = mapped_column(Integer, nullable=False)
    source_occurred_at: Mapped[datetime] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        # Supports ORDER BY created_at DESC, id DESC cursor pagination the next spec needs
        Index("idx_property_listings_pagination", "status", "created_at", "id"),
    )
```

### Projector handler

New module `src/listings/adapters/workers/property_event_handler.py`. Registered on the **listings context worker** (`src/listings/entrypoints/events_worker.py`, created in the foundation spec). The listings SQS queue is subscribed (via SNS) to `PROPERTY_CREATED.v1`, `PROPERTY_UPDATED.v1`, `PROPERTY_DELETED.v1`, and `PROPERTY_LISTING_NEEDS_ADDRESS_ENRICHMENT.v1`.

Pseudocode (handler signature per foundation spec: `(event: DomainEvent, ctx) -> None`):

```python
async def handle_property_event(event: DomainEvent, context: dict) -> None:
    """Handles PROPERTY_CREATED.v1, PROPERTY_UPDATED.v1, PROPERTY_DELETED.v1.

    The full envelope is the argument — event_type / event_id / occurred_at
    are first-class, not read from structlog.contextvars.
    """
    listings = context["listings"]
    data = event.data

    if event.event_type == PROPERTY_DELETED_V1:
        await listings.delete_property_listing.execute(
            property_id=UUID(data["id"]),
            source_aggregate_version=data["aggregate_version"],
            source_occurred_at=event.occurred_at,
        )
        return

    # Upsert with NULL location fields (enrichment happens async)
    await listings.upsert_property_listing.execute(
        data=data,
        source_occurred_at=event.occurred_at,
    )

    # Emit a separate enrichment event so the LLM call happens out-of-band,
    # on its own SNS topic. The same listings queue is subscribed to it, so
    # the enrichment handler will pick it up on a subsequent poll.
    await context["publisher"].publish(
        DomainEvent(
            event_type=PROPERTY_LISTING_NEEDS_ADDRESS_ENRICHMENT_V1,
            data={"property_id": data["id"], "address": data["address"]},
        )
    )
```

**One handler function, three event types.** The shared `EventRouter` lets us register the same function for all three:

```python
# in src/listings/entrypoints/events_worker.py
router.on(PROPERTY_CREATED_V1, handle_property_event)
router.on(PROPERTY_UPDATED_V1, handle_property_event)
router.on(PROPERTY_DELETED_V1, handle_property_event)
router.on(PROPERTY_LISTING_NEEDS_ADDRESS_ENRICHMENT_V1, handle_address_enrichment)
```

**Idempotency.** `upsert_property_listing` uses `INSERT ... ON CONFLICT (id) DO UPDATE SET ... WHERE excluded.source_aggregate_version > property_listings.source_aggregate_version`. Older events are silently dropped. Ties on `source_aggregate_version` fall through to `source_occurred_at` for safety.

### Enrichment handler (separate, same worker)

Per the earlier decision ("persist row with NULL location, enrich async"): the projector emits a `PROPERTY_LISTING_NEEDS_ADDRESS_ENRICHMENT.v1` event after upserting the row. That event has its own SNS topic, to which the listings queue subscribes. When the listings worker picks it up, the enrichment handler runs:

```python
async def handle_address_enrichment(event: DomainEvent, context: dict) -> None:
    listings = context["listings"]
    parsed = await listings.address_parser.parse(event.data["address"])
    await listings.update_property_listing_location.execute(
        property_id=UUID(event.data["property_id"]),
        parish=parsed.parish,
        municipality=parsed.municipality,
        district=parsed.district,
    )
```

If `AddressParser.parse()` raises (network / LLM refusal / rate limit), the handler re-raises, the shared `SQSWorker` does not ack the message (per ADR-008 §6), and SQS redelivers after the visibility timeout expires. After `maxReceiveCount=5` the message lands in the listings DLQ. `location_enrichment_attempts` is incremented every successful *or* failed handler run so a monitor query can surface properties whose enrichment is stuck.

Critically: because only the **enrichment** event DLQs (not the original PROPERTY_CREATED.v1), the property still appears in listings with NULL parish/municipality/district. The original event was already ack'd successfully the moment the projector upserted the row. Handler isolation — ADR-008's headline benefit — is what makes this safe.

### Address parser port + adapters

- `src/listings/application/ports/address_parser.py` (new):
  ```python
  class ParsedAddress(BaseModel):
      parish: str | None = None
      municipality: str | None = None
      district: str | None = None

  class AddressParser(Protocol):
      async def parse(self, address: str) -> ParsedAddress: ...
  ```
- `src/listings/adapters/ai/langchain_address_parser.py` (new) — `ChatOpenAI(model=..., temperature=0).with_structured_output(ParsedAddress)`. Exact model string pinned at implementation time against the then-current catalogue; "gpt-5-mini class" is the requirement.
- `src/listings/adapters/inmemory/inmemory_address_parser.py` (new) — deterministic fake for tests: splits on `,`, strips, returns the triple in parish/municipality/district order.

### Test strategy

**Unit**
- `tests/unit/test_property_event_handler.py` — given a sample `PROPERTY_CREATED.v1` payload, asserts the projector calls the right `upsert` / `delete` use case and publishes the enrichment event. Idempotency: a lower `source_aggregate_version` is dropped.
- `tests/unit/test_address_enrichment_handler.py` — parser success writes location; parser exception re-raises.
- `tests/unit/test_inmemory_address_parser.py` — `"Arca, Ponte de Lima, Viana do Castelo"` → parish="Arca", municipality="Ponte de Lima", district="Viana do Castelo".

**Integration** (LocalStack SQS end-to-end, following the fixture pattern from `tests/e2e/test_notification_flow.py` — one shared `testcontainers/localstack` container per session):
- `tests/integration/test_property_event_projection.py`:
  1. `POST /api/v1/admin/properties/` — row appears in `property_listings` after the worker runs one poll loop. `parish/municipality/district` still NULL.
  2. Let the worker run a second loop iteration (the enrichment event is now in the queue). Row gains parish/municipality/district from the fake parser.
  3. Assert `source_aggregate_version == 1` and `location_enrichment_attempts == 1`.
  4. Call `PATCH` on a property owner (any update use case). Row's `source_aggregate_version` increments; re-enrichment re-runs.
  5. Replay the *old* PROPERTY_CREATED event onto the queue. Assert the row does **not** regress (idempotency check fires).
  6. Call `DELETE` on the property. Row is gone.
- `tests/integration/test_property_event_dlq.py`:
  1. Monkeypatch the parser to always raise.
  2. Publish an enrichment event, run the worker 6 times.
  3. Assert the original `property_listings` row still exists with NULL location, `location_enrichment_attempts == 5`, and the SQS DLQ has 1 message.

LangChain parser is never exercised in tests — always the in-memory fake. LocalStack SQS is real.

## Affected files / surfaces

**Shared events:**
- `src/shared/events/types.py` — add `PROPERTY_UPDATED_V1`, `PROPERTY_DELETED_V1`, `PROPERTY_LISTING_NEEDS_ADDRESS_ENRICHMENT_V1`. (`PROPERTY_CREATED_V1` already renamed in the foundation spec; this spec changes its payload.)
- `src/shared/entrypoints/bootstrap.py` — `get_listing_container()` gains the new deps (repo, address parser, use cases) + a handle to the `EventPublisher` so enrichment events can be emitted from handlers.

**Infrastructure (out of this repo):**
- New SNS topics: `domain-events-PROPERTY_UPDATED.v1`, `domain-events-PROPERTY_DELETED.v1`, `domain-events-PROPERTY_LISTING_NEEDS_ADDRESS_ENRICHMENT.v1`.
- Listings-events-queue subscribes to all four topics (three above + existing `PROPERTY_CREATED.v1`).
- Per the foundation spec, the listings queue already has a DLQ with `maxReceiveCount=5`.

**Properties (write-side):**
- `src/properties/domain/models/property.py` — add `aggregate_version: int` (default 0); add an `increment_version()` helper or inline the `+= 1`.
- `src/properties/adapters/database/models.py` — add `aggregate_version` column on the `properties` table.
- `src/properties/application/events/property_event.py` (new) — `build_property_snapshot(prop: Property) -> dict` returning the v1 payload. Used by all emitters.
- The 10 use cases listed in the table above — inject `EventPublisher` (the port from the foundation spec), bump aggregate version on the domain model, emit the right event with the full snapshot. `create_property.py` changes payload of the existing `PROPERTY_CREATED.v1`; `delete_property.py` emits the new `PROPERTY_DELETED.v1`.
- `src/properties/adapters/workers/discovery_processor.py` — read `body["data"]["id"]` from the v1 payload instead of `body["property_id"]`. Low-touch.
- `src/properties/container.py` — wire `domain_event_publisher` into the 10 updated use cases.

**Listings (read-side):**
- `src/listings/domain/models.py` — add a `PropertyListing` dataclass (distinct from the existing `ListedProperty`).
- `src/listings/adapters/database/models.py` — add `PropertyListingModel` as a **new** table. Keep `ReadPropertyModel` and friends untouched (non-goal: this spec does not deprecate them).
- `src/listings/application/ports/address_parser.py` (new) — port.
- `src/listings/application/ports/repositories/property_listing_repository.py` (new) — repository port for the new table (upsert, delete, get_by_id, update_location).
- `src/listings/application/use_cases/upsert_property_listing.py`, `delete_property_listing.py`, `update_property_listing_location.py` (new) — idempotent writers.
- `src/listings/adapters/database/property_listing_repository.py` (new) — SQLAlchemy impl of the upsert-with-version-guard.
- `src/listings/adapters/inmemory/inmemory_property_listing_repo.py` (new) — in-memory test double.
- `src/listings/adapters/ai/langchain_address_parser.py` (new).
- `src/listings/adapters/inmemory/inmemory_address_parser.py` (new).
- `src/listings/adapters/workers/property_event_handler.py` (new) — projector handler (covers PROPERTY_CREATED.v1 / UPDATED.v1 / DELETED.v1).
- `src/listings/adapters/workers/address_enrichment_handler.py` (new) — enrichment handler for PROPERTY_LISTING_NEEDS_ADDRESS_ENRICHMENT.v1.
- `src/listings/entrypoints/events_worker.py` — **created by the foundation spec**. This spec adds the four handler registrations to its router.
- `src/listings/container.py` — register the new use cases, repo, parser, and expose them for handler use.

**Migrations:**
- `alembic/versions/<timestamp>_add_property_aggregate_version.py` — adds `aggregate_version` column to `properties`, backfill `0` for existing rows.
- `alembic/versions/<timestamp>_add_property_listings_table.py` — creates `property_listings` + indexes.
- One-shot data task (manual or a `python -m` CLI): after migration, emit a synthetic PROPERTY_CREATED for every existing property to seed `property_listings`. Not a migration — it uses the event path so LLM enrichment happens via the normal flow. Document the CLI in the spec.

**Tests:**
- Unit tests listed above.
- Integration tests listed above.

**Follow-on spec dependencies satisfied:**
- `listings-cursor-pagination-and-filters.md` can now read from `property_listings` knowing the schema and indexes above.

## Acceptance criteria

- [ ] `aggregate_version` column exists on `properties` with a `NOT NULL DEFAULT 0` migration applied; every state-mutating use case increments it in the same transaction as the state change.
- [ ] All 10 listed property use cases accept an `EventPublisher` (the port from the foundation spec) and emit the correct `PROPERTY_CREATED.v1` / `PROPERTY_UPDATED.v1` / `PROPERTY_DELETED.v1` event with the exact payload shape in the approach.
- [ ] `discovery_processor.handle_property_created` reads the property_id from `data["id"]` (new payload location) and continues to function.
- [ ] `property_listings` table exists with every indexed column listed; `(status, created_at, id)` compound index supports the next spec's cursor pagination.
- [ ] Projector handler `handle_property_event` is registered on the listings context worker for `PROPERTY_CREATED.v1`, `PROPERTY_UPDATED.v1`, `PROPERTY_DELETED.v1`.
- [ ] Idempotency: a replayed event with `source_aggregate_version <= property_listings.source_aggregate_version` is silently dropped (no row mutation).
- [ ] Projector emits `PROPERTY_LISTING_NEEDS_ADDRESS_ENRICHMENT.v1` for every non-DELETED event. Enrichment handler fills `parish` / `municipality` / `district` on success and increments `location_enrichment_attempts`.
- [ ] On parser exception, enrichment handler re-raises; the shared `SQSWorker` does not ack; after `maxReceiveCount` failures the message is in the listings DLQ; the `property_listings` row still exists with NULL location and the original PROPERTY_CREATED/UPDATED event is NOT in the DLQ (handler isolation works because the enrichment has its own topic).
- [ ] Unit + integration tests listed above all pass.
- [ ] Manual backfill CLI (`python -m listings.entrypoints.backfill_property_listings` or similar) can replay every existing property through the event path.
- [ ] All existing tests pass.

## Open questions

None blocking. To confirm at implementation time:
- Exact OpenAI model string for "gpt-5-mini class" — confirm against the live catalogue.
- Whether `build_property_snapshot` lives on the Property aggregate (as a method) or in a separate `properties/application/events/` module. Non-blocking preference — the latter keeps the domain model pure.

## Out of scope follow-ups

- Rewiring `GET /api/v1/listings/properties` to read from `property_listings` (that's `listings-cursor-pagination-and-filters.md`).
- Deleting the legacy `ReadPropertyModel` + `ListingRepository` after the route is swapped.
- Transactional outbox pattern to guarantee "DB commit → event publish" atomicity.
- Event sourcing / projection replay from an event log (we don't retain events long enough to replay today).
- Applying this pattern to other bounded contexts.
