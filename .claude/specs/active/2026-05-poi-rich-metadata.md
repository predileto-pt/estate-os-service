# POI rich metadata: address, images, reviews

**Status:** in-progress (sharpened from review, ready to implement)
**Owner:** Peter
**Created:** 2026-05-09

## Problem

The POI auto-discovery workflow (ADR-010 stage 1+2, shipped as `/admin/properties/{id}/enrich`) produces rows with only the bare-minimum fields a proximity ranker needs: name, distance, lat/lng, place_id. The Admin Dashboard wants more:

1. **Inline address** — agents reading the POI list want a full address per row, not just a name + distance.
2. **Images** — agents want to see what the place looks like when reviewing nearby amenities (and eventually for buyer-facing materials).
3. **Reviews** — Google reviews/ratings per POI, where appropriate.

None of this is available from the **Nearby Search** endpoint we currently call (`google_places_service.py:13`); it requires a follow-up **Place Details** call per ranked POI.

There's also a sensitivity dimension: reviews on schools, hospitals, kindergartens, and police stations risk surfacing content that's irrelevant or inappropriate in a real-estate listing context. Images are universally fine.

## Goal

Extend the `property_pois` schema with three new fields (`address`, `image_urls`, `reviews`), plumb a Place Details fetch step into the enrichment workflow, and surface the data on `PropertyPoiResponse` (no other response model changes — `EnrichPropertyResponse` stays `{job_id, status, property_id}`). Fail-silent on metadata fetch errors — POI rows must persist successfully even if Place Details is unreachable for some or all of them.

## Non-goals

- **No removal of the existing `metadata` JSONB column.** It stays for provider-specific extras and agent notes.
- **No rich review filtering / moderation.** We store what Google returns (truncated to 5) and the frontend renders it as-is.
- **No image upload / S3 mirroring.** We store resolved Google CDN URLs (option A from the call); we do **not** download and re-host.
- **No cost-of-life metadata.** Separate ADR-010 slice.
- **No multi-provider abstraction beyond the existing `PlacesService` port.** Place Details is added as a method on the existing port; OSM/other providers can implement it later.
- **No retries on Place Details failures.** Per-POI fail-silent — if a fetch fails, that POI gets `address=None`, `image_urls=[]`, `reviews=None`. The user re-runs `/enrich` to retry. SQS-level retry on the parent workflow is unchanged.
- **No backfill.** Existing POI rows have empty images/reviews/address until next `/enrich` run.

## Approach

### Schema changes (migration)

`property_pois` table gains three columns:

| col | type | notes |
|---|---|---|
| `address` | text nullable | Google's `formatted_address` (e.g. `"R. Áurea 100, 1100-063 Lisboa, Portugal"`); null if Place Details fetch failed or returned no address. |
| `image_urls` | jsonb (array of strings), `NOT NULL`, default `'[]'::jsonb` | Up to 5 resolved Google CDN URLs (`lh3.googleusercontent.com/...`). Empty array conflates "Google has no photos" with "fetch failed" — acceptable for v1 (frontend renders both the same). If product later wants the distinction, switch to `list[str] \| None`. |
| `reviews` | jsonb nullable | Array of up to 5 review objects: `[{"author_name": str, "rating": int, "text": str, "time": int (unix), "language": str?}]`. Null when the category is on the blacklist OR the fetch failed OR Google returned no reviews. **Distinct from `[]`** which would mean "fetched but empty". Easier UX guard. |

No new indexes — these columns aren't query targets, just per-row payload.

### Domain changes

`PropertyPoi` (`src/properties/domain/models/property_poi.py`) gains:

```python
address: str | None = None
image_urls: list[str] = field(default_factory=list)
reviews: list[dict] | None = None
```

### Place Details: new port method

Extend `PlacesService` (`src/properties/application/ports/places_service.py`) with a second method:

```python
@abstractmethod
async def get_place_details(self, place_id: str) -> PlaceDetails | None:
    """Fetch rich metadata for a place. Returns None on any failure
    (HTTP error, missing place_id, API quota exhausted) — caller treats
    None as 'no metadata available'.
    """
```

New value object `PlaceDetails` (lives next to `NearbyPlace`):

```python
@dataclass(frozen=True)
class PlaceDetails:
    place_id: str
    formatted_address: str | None
    image_urls: list[str]              # already resolved (CDN), at most 5
    reviews: list[dict] | None         # raw Google review objects, at most 5
```

### Google adapter changes

`GooglePlacesService.get_place_details` adds:

1. **Place Details call** — `GET https://maps.googleapis.com/maps/api/place/details/json?place_id=X&fields=formatted_address,photos,reviews&key=...`. The `fields` param is critical for billing — without it, Google bills for the full atmosphere SKU including data we don't use.
2. **Photo resolution** — for each `photo_reference` in the response (up to 5), construct the Photos API URL (`https://maps.googleapis.com/maps/api/place/photo?maxwidth=800&photoreference=...&key=...`), then issue an `httpx.AsyncClient(follow_redirects=False).get(url)` and read the `Location` header from the resulting 302. We do **not** follow the redirect (which would download the actual photo bytes); we just want the resolved CDN URL.
3. **Review trim** — keep only `author_name`, `rating`, `text`, `time`, `language` from each review (drop user IDs and profile photo URLs). Hard-cap at 5.

Failure mode for this adapter:
- HTTP error / non-200: return `None`.
- Photo redirect fails: skip that photo (keep going); empty `image_urls=[]` if all fail.
- Reviews missing: `reviews=None` (vs `[]`).

The whole thing is wrapped in a top-level `try/except` that returns `None` on any unhandled exception — the workflow caller treats `None` as "no metadata".

**Concurrency.** The Place Details + photo-resolution work is per-POI HTTP I/O. We fan out via `gather_with_concurrency` (already in use in `enrich_property.py:38`) with the same `PLACES_CONCURRENCY_LIMIT = 5` to avoid hammering Google.

### Reviews blacklist

A constant in `enrich_property.py`:

```python
REVIEWS_BLACKLIST: frozenset[PoiCategory] = frozenset({
    PoiCategory.HOSPITAL,
    PoiCategory.SCHOOL,
    PoiCategory.KINDERGARTEN,
    PoiCategory.POLICE_STATION,
})
```

For blacklisted categories, the enrichment step **still fetches Place Details for address + images** but discards the reviews payload before persisting. (Cheaper than skipping Place Details entirely — we still want the address.) The `fields` param sent to Google for blacklisted categories drops `reviews` so we don't pay for the atmosphere SKU on those:

```python
fields = "formatted_address,photos"
if category not in REVIEWS_BLACKLIST:
    fields += ",reviews"
```

### Workflow integration

The new step runs immediately after `bump_aggregate_version` (line ~244 of `enrich_property.py`), inside the existing `_run` method. Two-phase enrichment:

1. **Phase 1 (existing)** — discover, rank, compose, persist basic POIs. This phase's correctness is unchanged; users always get the basic POI list back.
2. **Phase 2 (new)** — for each persisted POI with a `place_id`, fan out a `get_place_details` call. For each result, update that POI row with `address`, `image_urls`, `reviews`. Per-POI fail-silent: if `get_place_details` returns None, leave the row's metadata fields at their defaults (null/[]/null).

Fan-out uses `gather_with_concurrency(5, ...)`. Total wall time: ~90 calls / 5 concurrency = ~18 sequential Google round trips ≈ 5–15s on top of existing enrichment. Combined Phase 1 + Phase 2 wall time stays comfortably under the worker's heartbeat envelope (`heartbeat_interval=60, heartbeat_extension=120` per `src/properties/entrypoints/worker.py:106-107`) — visibility extends every 60s by 120s, so a 30–60s enrichment never trips redelivery.

**Fail-silent invariant.** No metadata-fetch error path raises out of `_enrich_metadata`. Per-POI exceptions are caught and logged inside `_one`; the outer `gather_with_concurrency` therefore sees no exceptions to propagate. Phase 1's success is independent of Phase 2.

```python
# After bump_aggregate_version on line 243:
await self._enrich_metadata(persisted)  # fail-silent inside; doesn't raise
```

`_enrich_metadata` implementation sketch:

```python
async def _enrich_metadata(self, pois: list[PropertyPoi]) -> None:
    targets = [p for p in pois if p.place_id]
    if not targets:
        return

    async def _one(poi: PropertyPoi) -> None:
        try:
            details = await self.places_service.get_place_details(poi.place_id)
            if details is None:
                return
            reviews = details.reviews
            if poi.category in REVIEWS_BLACKLIST:
                reviews = None
            await self.property_poi_repo.update_place_details(
                poi_id=poi.id,
                address=details.formatted_address,
                image_urls=details.image_urls,
                reviews=reviews,
            )
        except Exception:
            log.exception(
                "enrich_property.metadata_fetch_failed",
                poi_id=str(poi.id),
                place_id=poi.place_id,
            )

    await gather_with_concurrency(PLACES_CONCURRENCY_LIMIT, *(_one(p) for p in targets))
```

**Idempotency.** Phase 2 runs every `/enrich` call. Re-runs overwrite the metadata fields with fresh values — same idempotency story as Phase 1's `replace_for_property`.

### Repository: new `update_place_details` method

`PropertyPoiRepository` port gains:

```python
@abstractmethod
async def update_place_details(
    self,
    *,
    poi_id: UUID,
    address: str | None,
    image_urls: list[str],
    reviews: list[dict] | None,
) -> None: ...
```

**Naming note.** Called `update_place_details` (not `update_metadata`) to avoid collision with the existing `metadata` JSONB column on `PropertyPoi`, which holds agent notes / provider extras and has nothing to do with the new fields.

Why a dedicated method (vs reusing `update`): the existing `update` accepts a full `PropertyPoi` aggregate and updates *every* mutable field. For Phase 2 we only want to touch the three new place-details columns — narrower surface, less risk of clobbering ranking-time fields if something else changes them between Phase 1 and Phase 2 runs.

Implementations:
- **Supabase** — single UPDATE: `update({"address": ..., "image_urls": ..., "reviews": ...}).eq("id", poi_id)`.
- **In-memory** — patch the corresponding dict entries.

### API response schema

`PropertyPoiBase` (`src/properties/adapters/api/schemas.py:261`) gains:

```python
address: str | None = None
image_urls: list[str] = Field(default_factory=list, max_length=5)
reviews: list[dict] | None = None
```

Three places this propagates to the response:
- `PropertyPoiResponse` (inherits from `PropertyPoiBase`).
- `CreatePropertyPoiRequest` (manual-entry POIs) — **decision: accept the three new fields**. Agents creating a manual POI can attach images / reviews / address if they want. This matches the existing free-form `metadata: dict` pattern. No URL or schema validation on the values in v1 — agent-mediated trust. (Future v2 may add `HttpUrl` validation for `image_urls` and a Pydantic schema for `reviews`.)
- `UpdatePropertyPoiRequest` (PATCH semantics) — same: optional `address`, `image_urls`, `reviews`. PATCH `reviews=[{"author_name": ..., "rating": 5, "text": ...}]` round-trips verbatim. No body schema check on review dicts in v1.

The list/get/replace POI routes (`property_pois.py`) need no logic change — they read from the repo, the repo returns the updated domain model, the response model picks up the new fields.

### Manual-entry interaction

Manually-entered POIs go through `replace_property_pois` and `create_poi` paths. They don't have a `place_id`, so `_enrich_metadata` skips them (`if p.place_id` filter). Agents can manually fill `address` / `image_urls` / `reviews` via the existing PATCH route if they want. No conflict.

### Tests

#### Unit
- New `PlaceDetails` dataclass: trivial.
- `GooglePlacesService.get_place_details` happy path + each failure mode (HTTP fail, missing photos, missing reviews, photo redirect 404). Mock `httpx.AsyncClient`.
- `EnrichProperty._enrich_metadata`:
  - All POIs get metadata: every row updated with `address`, `image_urls`, `reviews`.
  - One POI's `get_place_details` returns None: that row's metadata stays defaults; others succeed.
  - One POI's `get_place_details` raises: same — silent log, others succeed.
  - Blacklisted categories (`HOSPITAL`, `SCHOOL`, `KINDERGARTEN`, `POLICE_STATION`): `reviews` is `None` even when Google returned reviews; `address` and `image_urls` populate normally.
- `update_metadata` in-memory repo: patches only the three columns; other fields untouched.

#### Integration
- `POST /admin/properties/{id}/enrich` happy path: response unchanged (still 202 + job_id), but assert via repo state that POI rows have the new fields populated.
- Manual POI replace: response carries the new fields with defaults (`null` / `[]` / `null`).
- PATCH POI with `address` / `image_urls` / `reviews`: round-trips correctly.

#### Database
- Migration upgrade adds the three columns; downgrade removes them.
- `image_urls` defaults to `'[]'::jsonb`, `reviews` defaults to `NULL`, `address` defaults to `NULL`.

## Affected files / surfaces

### New files
- `alembic/versions/<new>_add_poi_rich_metadata.py` — migration.
- `tests/unit/properties/test_get_place_details.py` — adapter + use-case unit tests for the metadata phase.

### Updated files
- `src/properties/domain/models/property_poi.py` — three new fields on the dataclass.
- `src/properties/domain/models/nearby_place.py` (or new file) — `PlaceDetails` value object. Keeping `nearby_place.py` since both are place-shaped value objects.
- `src/properties/application/ports/places_service.py` — `get_place_details` abstract method.
- `src/properties/application/ports/repositories/property_poi_repository.py` — `update_metadata` abstract method.
- `src/properties/adapters/places/google_places_service.py` — `get_place_details` impl + photo redirect resolution.
- `src/properties/adapters/inmemory/inmemory_places_service.py` — extend with a `set_place_details(place_id, details)` seeder + `get_place_details` impl that returns from the dict.
- `src/properties/adapters/persistence/supabase_property_poi_repo.py` — read/write the three new columns; new `update_place_details` method.
- `src/properties/adapters/inmemory/inmemory_property_poi_repo.py` — same.
- `src/properties/adapters/database/models.py` — three new columns on `PropertyPoiModel`.
- `src/properties/application/use_cases/enrich_property.py` — `_enrich_metadata` step + `REVIEWS_BLACKLIST`.
- `src/properties/adapters/api/schemas.py` — three new fields on `PropertyPoiBase` + opt-in fields on `UpdatePropertyPoiRequest`.
- `tests/integration/test_property_pois.py` — assertions on the new fields' presence in responses.
- `tests/database/test_migration.py` — bump revision id; assert new columns exist on `property_pois`.

## Acceptance criteria

- [ ] Migration `upgrade()` adds `address` (text nullable), `image_urls` (jsonb NOT NULL default `'[]'::jsonb`), `reviews` (jsonb nullable) to `property_pois`. `downgrade()` reverses cleanly.
- [ ] `tests/database/test_migration.py` passes — revision is the new head, the three new columns exist with correct types/nullability, and `image_urls` defaults to `'[]'::jsonb` (asserted via `pg_attrdef`).
- [ ] `PropertyPoi` dataclass has the three new fields with correct defaults.
- [ ] `PlaceDetails` value object exists alongside `NearbyPlace`.
- [ ] `PlacesService.get_place_details` is implemented in `GooglePlacesService` (real Google call) and `InMemoryPlacesService` (test seeding).
- [ ] `GooglePlacesService.get_place_details` requests **only** `formatted_address,photos` for blacklisted categories and `formatted_address,photos,reviews` for non-blacklisted ones.
- [ ] Cost-aware filter is verified at the wire level: a unit test with mocked `httpx.AsyncClient` asserts the outbound URL's `fields=` query param does not contain `reviews` when the category is blacklisted.
- [ ] `GooglePlacesService.get_place_details` returns `None` (not raises) on HTTP error, malformed response, or any unhandled exception.
- [ ] Photo redirect resolution returns the `Location` header URL; failures skip the photo without aborting. Verified by a unit test that mocks three photos where photo #2's redirect 404s — the result has two URLs (photo #1 and #3), not three.
- [ ] `image_urls` is hard-capped at 5 per POI.
- [ ] `reviews` is hard-capped at 5 per POI; trimmed to `{author_name, rating, text, time, language?}`.
- [ ] `EnrichProperty._enrich_metadata` runs after `bump_aggregate_version`, fans out via `gather_with_concurrency(5, ...)`, fail-silent per POI.
- [ ] Blacklisted categories (`HOSPITAL`, `SCHOOL`, `KINDERGARTEN`, `POLICE_STATION`) have `reviews=None` after enrichment regardless of what Google returned. Address + images populate normally.
- [ ] Manually-entered POIs (no `place_id`) are skipped by `_enrich_metadata`.
- [ ] `update_metadata` repo method only touches the three columns — other fields unchanged.
- [ ] `PropertyPoiResponse` exposes `address`, `image_urls`, `reviews`.
- [ ] PATCH `/properties/{id}/pois/{poi_id}` accepts and persists the three new fields.
- [ ] `POST /admin/properties/{id}/enrich` happy-path integration test: ranked POIs end up with `address`, `image_urls`, `reviews` (or `None` if blacklisted) populated; non-Google POIs end up with defaults.
- [ ] `GET /admin/properties/{id}/pois?organization_id=X` integration test: response body carries the three new fields populated for the ranked POIs.
- [ ] `CREATE /admin/properties/{id}/pois?organization_id=X` accepts a manual POI body containing `address`, `image_urls`, `reviews` and round-trips them in the response.
- [ ] All existing tests still pass. `uv run ruff check .` clean.

## Open questions

1. **`image_urls` width.** Google's `maxwidth` param caps the photo dimensions. Default 800px — reasonable for a dashboard thumbnail. If product wants larger (e.g. for a future hero card), we'll either add a server-side resize step or store multiple widths. Out-of-scope for v1; flag if the dashboard needs different.
2. **CDN URL longevity.** Google doesn't formally guarantee `lh3.googleusercontent.com` URL stability. Empirically they're stable for months+, but a stale URL would render as a broken image. Mitigation strategies for later: re-enrich on demand (cheap), or move to Option B (`photo_reference` + backend proxy) if breakage gets reported.
3. **Review locale.** Google returns reviews in mixed locales. We store `language` per review; the frontend can filter or translate. No backend filtering in v1.
4. **Place Details cost cap.** ~90 Place Details + photo-resolution calls per `/enrich`. Acceptable today. If we ever 10x property count, revisit (e.g. by caching `PlaceDetails` by `place_id` for some TTL).
5. **Frontend null-vs-empty contract on `reviews`.** We baked in three states (`null` = blacklisted/failed, `[]` = fetched empty, `[...]` = present). The dashboard has to be aware. If product would rather render `null` and `[]` identically, we simplify to `reviews: list[dict]` (NOT NULL, default `'[]'::jsonb`) and lose the signal. Frontend lead to confirm before this ships.

## Out of scope follow-ups

- Per-photo size variants (small/medium/large).
- Photo proxy / S3 mirror for permanence.
- Review translation pipeline.
- Per-POI cost rollups for Place Details usage (analogous to ADR-011's `generation_cost_entries`).
- Replacing the manually-edited `metadata` JSONB with structured columns (separate concern).

## Commits

Single feature commit when everything's green:

```
feat(properties): POI rich metadata — address, images, reviews

- New address (text), image_urls (jsonb), reviews (jsonb) columns on
  property_pois.
- PlacesService.get_place_details + Google adapter implementation:
  Place Details call (filtered fields), photo redirect resolution,
  fail-silent.
- EnrichProperty Phase 2: post-persist metadata fan-out, per-POI
  fail-silent, reviews blacklist for HOSPITAL/SCHOOL/KINDERGARTEN/
  POLICE_STATION.
- PropertyPoiResponse + PATCH route surface the new fields.

Cost note: ~90 extra Place Details + photo-resolution calls per
/enrich. Mitigation deferred until usage demands it.
```
