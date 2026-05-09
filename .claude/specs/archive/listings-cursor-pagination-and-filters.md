# Cursor pagination + structured-location filters + filter-values endpoint on listings

**Status:** draft
**Owner:** Peter
**Created:** 2026-04-17

## Problem

`GET /api/v1/listings/properties` (`src/listings/adapters/api/routes/listings.py:83-116`) today:
- Uses **offset pagination** (`?limit=20&offset=0`) plus `SELECT COUNT(*)` for `total`. Unstable under inserts and gets expensive as the table grows. Infinite-scroll UX on the frontend also has no use for `total`.
- Supports only `listing_type`, `typology`, `min_price`, `max_price`, and `district` (free-text substring on the single `address` column at `src/properties/adapters/database/models.py`).
- Has **no** way to filter on the 10 `PropertyCharacteristics` fields — they're stored as JSONB so filter queries can't hit indexes even if we wrote them.
- Has **no** endpoint that tells the frontend which filter values actually exist in the data (so the filter UI can populate dropdowns with real districts/municipalities/parishes and sensible min/max ranges).

The upstream spec `carried-state-events-and-property-listings-projector.md` produces a `property_listings` read-model table with structured location columns (`parish`, `municipality`, `district`), denormalized characteristic columns (`num_of_bedrooms`, `num_of_bathrooms`, `area_in_m2`, `has_pool`, `has_garden`, `has_elevator`), a price snapshot (`min_price`), and a compound `(status, created_at, id)` index suitable for cursor pagination. This spec spends that infrastructure.

## Goal

`GET /api/v1/listings/properties` reads from `property_listings`, supports cursor pagination + all the filters the frontend's infinite-scroll list needs, and is paired with a `GET /api/v1/listings/filters` endpoint that returns the available filter values computed on demand.

## Non-goals

- Introducing the `property_listings` table, the projector, or the address-enrichment pipeline. That's `carried-state-events-and-property-listings-projector.md`.
- Keeping the old offset contract alongside cursor. **The offset response shape is removed in this change.** There is no dual contract and no deprecation window — the frontend consumer is internal and the cutover happens in the same release.
- Geospatial filtering (PostGIS bounding box / radius). Latitude/longitude are already on `property_listings` and available later.
- Full-text search on `description`.
- Admin paginated endpoints. `GET /api/v1/admin/properties` stays offset-paginated for now; this spec is strictly about the public listings context.
- Changing the frontend. This spec ships the backend contract; the frontend adopter is a separate piece of work.

## Depends on

- `event-bus-ports-and-fanout-foundation.md` — must ship first.
- `carried-state-events-and-property-listings-projector.md` — must ship first. `property_listings` must exist and be populated (the backfill CLI in that spec runs for all existing properties before this route is swapped).

## Approach

### Cursor pagination

Endpoint signature:

```
GET /api/v1/listings/properties?limit=20&cursor=<opaque>&<filters...>
→ { items: [...], next_cursor: "<opaque>" | null }
```

- `limit`: int, default 20, max 100.
- `cursor`: base64url-encoded JSON `{"created_at": "<iso>", "id": "<uuid>"}`. Absent on first request.
- Ordering: `WHERE status = 'active' AND <filters>` `ORDER BY created_at DESC, id DESC` `LIMIT limit + 1`. If `limit + 1` rows come back, the `(limit+1)`-th becomes `next_cursor`'s seed; otherwise `next_cursor = null`.
- Compound index `(status, created_at, id)` on `property_listings` (created by the upstream spec) supports this directly.
- Cursor decoding is strict: malformed / truncated cursors return 400 `{"detail": "Invalid cursor"}`. Opaqueness is encouraged (frontend should not parse), but it's not signed — anyone can forge one; the only risk is returning the wrong page, not an authorization bypass (listings are public).

### Filters

Every filter is a query param on `GET /api/v1/listings/properties`. All are optional. Combined with `AND`.

| Param | Type | Column on `property_listings` |
|---|---|---|
| `listing_type` | `sale` / `purchase` | `listing_type` |
| `typology` | `house` / `apartment` / `land` / `ruin` | `typology` |
| `district` | string (exact match, case-insensitive) | `district` |
| `municipality` | string (exact match, ci) | `municipality` |
| `parish` | string (exact match, ci) | `parish` |
| `min_price`, `max_price` | Decimal ≥ 0 | `min_price` |
| `min_bedrooms`, `max_bedrooms` | int ≥ 0 | `num_of_bedrooms` |
| `min_bathrooms`, `max_bathrooms` | int ≥ 0 | `num_of_bathrooms` |
| `min_area`, `max_area` | int ≥ 0 | `area_in_m2` |
| `has_pool`, `has_garden`, `has_elevator` | bool | respective boolean columns |

Status is **always** `status = 'active'` for this route — no status query param. Inactive properties are still kept in `property_listings` per the upstream spec, but don't surface here.

Properties with `NULL` for a queried location column (i.e. enrichment hasn't run or the LLM gave up) are excluded when the filter is set — they surface when no location filter is applied. Flag this behaviour explicitly in the API docstring.

### Filter-values endpoint

```
GET /api/v1/listings/filters
→ {
    "listing_types": ["sale", "purchase"],                  // static enum
    "typologies": ["house", "apartment", "land", "ruin"],   // static enum
    "districts": ["Viana do Castelo", "Porto", ...],        // DISTINCT from property_listings
    "municipalities": ["Ponte de Lima", ...],
    "parishes": ["Arca", ...],
    "price":    {"min": "<decimal-str>", "max": "<decimal-str>"},
    "bedrooms":  {"min": 0, "max": 6},
    "bathrooms": {"min": 1, "max": 4},
    "area_m2":   {"min": 30,  "max": 500}
  }
```

Computed on demand via a handful of cheap aggregations:

```sql
SELECT DISTINCT district FROM property_listings WHERE status='active' AND district IS NOT NULL ORDER BY district;
-- same for municipality, parish
SELECT MIN(num_of_bedrooms), MAX(num_of_bedrooms) FROM property_listings WHERE status='active';
-- same for bathrooms, area_in_m2, min_price
```

Five aggregation queries total. At current data volumes each is <10ms. If aggregations become a bottleneck we materialise into a `property_listing_filter_values` table refreshed by the projector — deferred follow-up, not in this spec.

Enum domains (`listing_types`, `typologies`) are static Python constants, not queries.

### Route rewiring

The listings context currently exposes two use cases built on the old read path:
- `list_properties` (`src/listings/application/use_cases/list_properties.py`) — consumes `PropertyFilters`, returns `(items, total)`.
- `get_property` (`src/listings/application/use_cases/get_property.py`) — single property.

Both are replaced in this spec with new use cases that query `property_listings` via the new `PropertyListingRepository` (introduced in the upstream spec):
- `ListPropertyListings` — takes the new `PropertyListingFilters` + `cursor` + `limit`, returns `(items, next_cursor)`.
- `GetPropertyListing` — single property by id.

The old `ListingRepository` port, its `InMemoryListingRepository` and database adapter at `src/listings/adapters/database/listing_repository.py`, and the old use cases are **deleted** in the same PR. The `ReadPropertyModel` / `ReadPropertyPriceModel` / `ReadPropertyImageModel` at `src/listings/adapters/database/models.py:37-113` are also deleted — nothing will reference them anymore. This is the explicit resolution of the "runs alongside vs. removed" tension that the review flagged.

### Response schema

`ListedPropertyResponse` (`src/listings/adapters/api/schemas.py`) gains `district`, `municipality`, `parish` (each `str | None`). The existing `prices: [...]` / `images: [...]` nested lists collapse to a simpler shape since `property_listings` only stores the denormalised projection:

```python
class ListedPropertyResponse(BaseModel):
    id: UUID
    organization_id: UUID
    address: str
    district: str | None
    municipality: str | None
    parish: str | None
    listing_type: ListingType
    typology: Typology
    description: str | None
    characteristics: PropertyCharacteristicsResponse | None   # sparse; only the 6 filterable fields + any extras worth showing
    min_price: Decimal | None
    first_image_url: str | None           # presigned from `first_image_s3_key`
    latitude: float | None
    longitude: float | None
    created_at: datetime
    updated_at: datetime
```

If the frontend needs the full owner / all-prices / all-images shape (it does, on the detail page), it should call `GET /api/v1/listings/properties/{id}` which can fan out to the write-side via a dedicated use case OR continue to return from the admin path. **Assumption to confirm:** the public listings context keeps returning only the denormalised view; admin callers (who need the full aggregate) use `GET /api/v1/admin/properties/{id}` which is already richer. If the public detail page truly needs the full shape we add a follow-up.

### Test strategy

**Unit**
- `tests/unit/test_cursor.py` — encode / decode round-trip; malformed cursor raises `InvalidCursorError`.
- `tests/unit/test_property_listing_filters.py` — the `PropertyListingFilters` value object validates bounds (`min_price >= 0`, `max_price >= min_price`, etc.).

**Integration** (uses the fixtures landed by the upstream spec — the LocalStack worker doesn't need to run for these tests; `property_listings` is seeded directly via the new `property_listing_repo` fixture):
- `tests/integration/test_listings.py`:
  - Seed 25 rows. Page 1 with `limit=10` returns 10 items + non-null cursor. Page 2 with that cursor returns next 10 + cursor. Page 3 returns 5 items + `null` cursor.
  - Each filter independently. Example: seed a row in "Viana do Castelo" and one in "Porto", filter `?district=Viana do Castelo`, assert only the first row. Ditto municipality, parish, bedrooms range, has_pool, price range.
  - Multi-filter: combine `listing_type=sale`, `min_bedrooms=2`, `has_pool=true`, `district=Viana do Castelo` and assert only rows satisfying all four come back.
  - Rows with `parish = NULL` are excluded when `?parish=...` is set, included when it isn't.
  - Inactive (`status != 'active'`) rows never appear.
  - Malformed cursor → 400.
- `tests/integration/test_filter_values.py`:
  - With no rows: all distinct-value arrays are empty, all ranges are `{"min": null, "max": null}`, enum domains are populated.
  - With seeded data: distinct values are sorted; ranges report correct min/max; enum domains unchanged.

LangChain + LocalStack are not involved in these tests — they exist in the upstream spec's test suite. This spec's tests seed `property_listings` directly and exercise only the query surface.

## Affected files / surfaces

**Listings context:**
- `src/listings/adapters/api/routes/listings.py` — full rewrite. New cursor-param handler, new filter params, new response shape. Old handler is removed.
- `src/listings/adapters/api/routes/filter_values.py` (new) — `GET /api/v1/listings/filters`.
- `src/listings/adapters/api/schemas.py` — new `ListedPropertyResponse` shape, new `CursorPage[ListedPropertyResponse]` wrapper, new `FilterValuesResponse`.
- `src/listings/application/use_cases/list_property_listings.py` (new) — cursor-paginated query.
- `src/listings/application/use_cases/get_property_listing.py` (new) — single-row lookup.
- `src/listings/application/use_cases/get_filter_values.py` (new).
- `src/listings/application/ports/repositories/property_listing_repository.py` — add `list_with_cursor(filters, cursor, limit)`, `get_filter_values()` methods to the port introduced in the upstream spec.
- `src/listings/adapters/database/property_listing_repository.py` — implement both.
- `src/listings/adapters/inmemory/inmemory_property_listing_repo.py` — implement both (cursor handled via sort-then-slice).
- `src/listings/application/ports/cursor.py` (new) — `encode_cursor(created_at, id) -> str`, `decode_cursor(str) -> tuple[datetime, UUID]`, `InvalidCursorError`.
- `src/listings/container.py` — register the three new use cases.

**Deletions (explicit resolution of the non-goal tension):**
- `src/listings/application/use_cases/list_properties.py`
- `src/listings/application/use_cases/get_property.py`
- `src/listings/application/ports/listing_repository.py` (old port)
- `src/listings/adapters/database/listing_repository.py` (old adapter)
- `src/listings/adapters/inmemory/inmemory_listing_repository.py` (if it exists)
- `src/listings/adapters/database/models.py` — remove `ReadPropertyModel`, `ReadPropertyPriceModel`, `ReadPropertyImageModel`. Keep `PropertyListingModel` (from upstream spec).

**Shared:**
- `src/shared/main.py` — register the new `filter_values.py` router alongside the existing listings router.
- `src/shared/api/middleware.py` — `/api/v1/listings/` prefix already bypasses auth (landed in commit `fded5a506c25`). Verify the new `/api/v1/listings/filters` path is still covered by that prefix match — yes, since the prefix is `/api/v1/listings/` (trailing slash) and `/filters` falls inside it.

**Tests:**
- Listed above.

**Docs:**
- Add a short API reference stub at `docs/api/listings.md` (if the conventional doc path exists in the repo; otherwise skip). Non-blocking.

## Acceptance criteria

- [ ] `GET /api/v1/listings/properties` returns `{items, next_cursor}`; ordered by `created_at DESC, id DESC`; paginates 25 rows across three requests with `limit=10` cleanly.
- [ ] Malformed `cursor` returns HTTP 400 with `{"detail": "Invalid cursor"}`.
- [ ] All 14 listed filter params apply correctly, individually and in combination.
- [ ] Rows with `NULL` in a queried location column are excluded when the corresponding filter is set.
- [ ] `GET /api/v1/listings/filters` returns the 9-key response shape above; aggregates reflect actual data in `property_listings`; empty-table case returns empty arrays and `{"min": null, "max": null}` ranges.
- [ ] The old offset-shaped response is gone. No route accepts `?offset=`.
- [ ] `src/listings/adapters/database/listing_repository.py` (old adapter), `src/listings/adapters/database/models.py:37-113` (`ReadProperty*Model` classes), and the old `list_properties` / `get_property` use cases are deleted.
- [ ] Unit + integration tests listed above all pass.
- [ ] Route is still under the public `PUBLIC_PREFIXES` match in `JWTAuthMiddleware` (no auth required).
- [ ] All existing tests pass. The pre-existing e2e `Container(...) missing portal_user_repo` errors are still out of scope.

## Open questions

- **Public detail-page response shape.** The simpler `ListedPropertyResponse` above drops the full `prices: [...]` / `images: [...]` lists. Does the public property-detail frontend actually need those? If yes, we either keep the richer shape on the detail endpoint only (adding a second fan-out query) or a follow-up spec extends `property_listings` with the full arrays. Confirm before implementation starts.
- **Case-insensitive exact match on location filters:** SQL `LOWER(district) = LOWER(:param)` works but doesn't hit the index. Add a `LOWER(district)` functional index if this turns out to be slow — measure before optimising.

## Out of scope follow-ups

- Materialised `property_listing_filter_values` table if the on-demand aggregations become a bottleneck.
- Geospatial filtering using `latitude` / `longitude`.
- Full-text search on `description`.
- Richer public detail-page endpoint (if the open question resolves to "yes, we need the full aggregate").
- Admin-side cursor pagination (the admin route at `/api/v1/admin/properties` stays offset-paginated).
