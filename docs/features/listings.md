# Listings

The `listings` bounded context exposes public, read-only property listings. It reads the same database tables as `properties` but defines its own ORM models to keep the boundary explicit. There is no authentication on these endpoints — they back the public property search portal.

**Source:** `src/listings/`

## Domain entities

| Entity                    | Description                                                                                                                    |
| ------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| `ListedProperty`          | Read-only view of a property. Includes characteristics, prices, images. **No owners** — owner data is private to `properties`. |
| `PropertyCharacteristics` | Frozen value object: area, bedrooms, bathrooms, year built, energy rating, etc.                                                |
| `PropertyPrice`           | Frozen value object: amount + listing type.                                                                                    |
| `PropertyImage`           | Frozen value object: S3 key, filename, ordering.                                                                               |

Enums (defined locally — duplicated by design from `properties`):

- `ListingType` — `SALE` / `PURCHASE`
- `Typology` — `HOUSE` / `APARTMENT` / `LAND` / `RUIN`
- `PropertyStatus` — `DRAFT` / `ACTIVE` / `SOLD` / `RENTED` / `WITHDRAWN`

## Feature catalog

| Feature                           | Trigger                                         | Purpose                               |
| --------------------------------- | ----------------------------------------------- | ------------------------------------- |
| [GetProperty](#getproperty)       | `GET /api/v1/listings/properties/{property_id}` | Return one active property by ID      |
| [ListProperties](#listproperties) | `GET /api/v1/listings/properties`               | Filter and paginate active properties |

---

## Feature details

### GetProperty

Return a single active property. Returns 404 if not found or not active.

- **Inputs:** `property_id`
- **Output:** `ListedProperty`
- **Side effects:** none (read-only). The route handler generates pre-signed S3 download URLs for images at response time.
- **Source:** `src/listings/application/use_cases/get_property.py`

### ListProperties

Filter active properties by listing type, typology, district (substring on address), price range, with offset pagination. Used by the public property search.

- **Inputs:** `PropertyFilters` dataclass
  - `listing_type?` — `SALE` / `PURCHASE`
  - `typology?` — `HOUSE` / `APARTMENT` / `LAND` / `RUIN`
  - `min_price?`, `max_price?` — `Decimal`
  - `district?` — substring match on address
  - `limit` (1-100, default 20)
  - `offset` (default 0)
- **Output:** `(list[ListedProperty], int)` — items and total count
- **Side effects:** none. The route handler enriches images with pre-signed URLs.
- **Notes:** price filtering is applied post-query because prices are stored in a separate table.
- **Source:** `src/listings/application/use_cases/list_properties.py`

## Read-model pattern

`listings` reads the `properties`, `property_prices`, and `property_images` tables but defines its own SQLAlchemy models in `src/listings/adapters/database/models.py` (`ReadPropertyModel`, `ReadPropertyPriceModel`, `ReadPropertyImageModel`) with `__table_args__ = {"extend_existing": True}`. This avoids cross-context imports while keeping a single physical schema.

The route layer (`src/listings/adapters/api/routes/listings.py`) calls `DocumentStorage.get_download_url()` for each image to produce signed URLs at response time — image bytes are never proxied through the API.

## Container

`src/listings/container.py` wires `GetProperty` and `ListProperties`. Built in `src/shared/entrypoints/bootstrap.py::get_listing_container()` and stored on `app.state.listing_container`.

## Publishing a property

A property starts in `DRAFT` status and is invisible to the portal (the read endpoints filter `WHERE status = ACTIVE`). An agent publishes it via:

```
POST /api/v1/admin/properties/{property_id}/publish?organization_id={org_id}
```

- **Auth:** caller must be `OWNER` or `ADMIN` of the organization.
- **Preconditions** (all enforced at the domain level; a 422 response carries the list of missing codes):
  - `address` is non-empty
  - at least one `PropertyPrice`
  - at least one `PropertyOwner`
  - at least one `PropertyImage`
  - `status` is `DRAFT` or `WITHDRAWN` (re-publishing a `SOLD` / `RENTED` / `ACTIVE` row returns 422 with `cannot_publish_from_status:<current>`)

On success:

1. The `properties.status` column flips to `ACTIVE`.
2. `aggregate_version` is bumped (drives projector idempotency).
3. `PROPERTY_PUBLISHED.v1` is emitted with the standard `build_property_snapshot` payload — the same shape as `PROPERTY_CREATED.v1` / `PROPERTY_UPDATED.v1`, so the listings projector upserts the `property_listings` row via the same code path.
4. The property appears in the public `GET /api/v1/listings/properties` results on the next read.

Error responses:

| Code  | When                                                                                                                 |
| ----- | -------------------------------------------------------------------------------------------------------------------- |
| `401` | No / invalid auth token                                                                                              |
| `403` | Caller is a member but not `OWNER` / `ADMIN`                                                                         |
| `404` | Property id not found, or doesn't belong to `organization_id`                                                        |
| `422` | `{"message": "...", "reasons": ["missing_price", "missing_image", "cannot_publish_from_status:sold", ...]}`          |

**Source:** `src/properties/application/use_cases/publish_property.py`, route at `src/properties/adapters/api/routes/properties.py`.

## Running the listings events worker

The listings context has its own SQS worker that consumes carried-state property events and maintains the `property_listings` read-model. Run it locally with:

```bash
uv run python -m listings.entrypoints.events_worker
```

It consumes five SNS topics via a single `listings-events-queue`:

| Event type                                      | Handler                     | Effect                                                                                  |
| ----------------------------------------------- | --------------------------- | --------------------------------------------------------------------------------------- |
| `PROPERTY_CREATED.v1`                           | `handle_property_event`     | Insert a `property_listings` row from the carried-state snapshot.                       |
| `PROPERTY_UPDATED.v1`                           | `handle_property_event`     | Upsert (newer `aggregate_version` wins).                                                |
| `PROPERTY_DELETED.v1`                           | `handle_property_event`     | Delete the row (version-guarded).                                                       |
| `PROPERTY_PUBLISHED.v1`                         | `handle_property_event`     | Upsert with `status='active'` from the snapshot — same code path as CREATED / UPDATED.  |
| `PROPERTY_LISTING_NEEDS_ADDRESS_ENRICHMENT.v1`  | `handle_address_enrichment` | Call the LLM address parser and fill `parish` / `municipality` / `district`.            |

Worker uses the shared `SQSWorker` (ADR-008) with heartbeat-extended visibility so long LLM calls on enrichment don't trip visibility-timeout redelivery.

See the shared worker pattern in the root `README.md` → *Domain events* section.
