# Listings cursor pagination + Redis cache (two-mode)

**Status:** draft
**Created:** 2026-05-11
**ADR:** [docs/adr/016-listings-cursor-pagination-and-page-cache.md](../../docs/adr/016-listings-cursor-pagination-and-page-cache.md)

## Problem

`GET /api/v1/listings/properties` paginates with offset/limit and runs **two queries per request** (`list_active` + `count_active`). Every infinite-scroll tick on the public portal hits the DB. Listings change rarely, so the same first 3–4 pages dominate read traffic with no cache absorbing it. Offset performance also degrades with depth.

The endpoint has two functionally distinct modes hidden behind the same URL:

- **List mode** (`?q` empty) — structured filters, ordered by `created_at DESC, id DESC`. Monotonic indexed sort key — keyset pagination works to any depth.
- **Search mode** (`?q` set) — Pinecone vector ranking. No native keyset; "next page" is implemented by enlarging `top_k` and slicing.

A uniform "cursor pagination" model papers over this difference and forces an awkward search-path implementation (per-page Pinecone calls, sort hacks for `list_by_ids` order preservation). The spec treats the two modes as architecturally distinct underneath, while keeping a single opaque cursor token on the wire.

## Goal

`GET /api/v1/listings/properties` returns cursor-paginated results from Redis-backed caches. List mode uses keyset + per-page cache; search mode uses a bounded cached ranked-id-list + per-page hydrate. No `COUNT(*)` on either path. ADR-016 is the architectural authority.

## Non-goals

- Admin endpoint `GET /api/v1/admin/listings/properties` and every other `OFFSET` surface — they stay as-is.
- Event-driven invalidation. v1 is TTL-only.
- Single-flight / cache-stampede protection.
- Hop-level caching of the LLM rewrite (deferred follow-up).
- Row-level hydrate cache for `list_by_ids`.
- Presigned image URL caching.

## Approach

### 1. Cursor utilities — `src/listings/domain/pagination/cursor.py` (new)

Two frozen dataclasses, common envelope:

```python
CURSOR_SCHEMA_VERSION = 1

@dataclass(frozen=True)
class ListCursor:
    fp: str
    created_at: datetime
    id: UUID

@dataclass(frozen=True)
class SearchCursor:
    fp: str
    offset: int

def filter_fingerprint(
    *,
    q: str | None,
    filters: PropertyFilters,
    location: LocationFilter | None,
) -> str:
    """sha256(canonical JSON of all binding inputs)[:16].
    Binds the cursor to the exact (q, filters, location) tuple that
    produced it."""

def encode(cursor: ListCursor | SearchCursor) -> str: ...
def decode(token: str, *, expected_fp: str) -> ListCursor | SearchCursor: ...
```

Token = base64url-encoded JSON `{v, k, fp, ...}` where `k ∈ {"list", "search"}` discriminates the payload. `decode` raises:

- `CursorVersionError` → 400 `cursor_unsupported_version`
- `CursorFilterMismatchError` → 400 `cursor_filter_mismatch`
- `CursorDecodeError` → 400 `cursor_invalid` (corrupt base64 / JSON / missing fields)

Plus a helper that the use cases call:

```python
def build_cache_key(*, kind: str, fp: str, suffix: str) -> str:
    """Returns `listings:{kind}:v1:{fp}:{suffix}`. `suffix` is `"head"`
    for the first page on the list path, the offset value on the
    search path, or the empty string for keys that have no
    sub-position (the L1 ranked-list cache)."""
```

### 2. Two cache ports

Listings has two distinct cache shapes; modelling them as one bag-of-methods port hides the asymmetry. Two narrow ports:

```python
# src/listings/application/ports/listings_page_cache.py (new)
@dataclass(frozen=True)
class CachedPage:
    items: list[PropertyListing]
    next_cursor: str | None

class ListingsPageCache(Protocol):
    async def get(self, key: str) -> CachedPage | None: ...
    async def set(self, key: str, page: CachedPage, ttl_seconds: int) -> None: ...
    async def invalidate_namespace(self, namespace: str) -> None: ...

# src/listings/application/ports/search_ranked_list_cache.py (new)
class SearchRankedListCache(Protocol):
    async def get(self, key: str) -> list[UUID] | None: ...
    async def set(self, key: str, ids: list[UUID], ttl_seconds: int) -> None: ...
    async def invalidate_namespace(self, namespace: str) -> None: ...
```

`ListingsPageCache` is consumed only by `ListProperties`. `SearchRankedListCache` is consumed only by `SearchListings`. (See §5.2 for why the search path doesn't get an L2 page cache in v1.)

### 3. Cache adapters — three flavors per port

For each port:

- **Redis adapter** — `src/listings/adapters/cache/redis_page_cache.py`, `redis_search_ranked_list_cache.py`. Both consume a shared `redis.asyncio.Redis` client (one connection pool). Value codec is msgpack with a primitive-dict helper (`_listing_to_dict`, `_listing_from_dict`) for `PropertyListing` (UUIDs → str, Decimals → str, datetimes → ISO, enums → value). On any deserialization or connection error: `get` returns `None`, `set` is best-effort (warning log, no raise).
- **Null adapter** — `src/listings/adapters/cache/null_page_cache.py`, `null_search_ranked_list_cache.py`. Always-miss `get`, no-op `set` / `invalidate_namespace`. Wired when `LISTINGS_PAGE_CACHE_ENABLED=false`.
- **In-memory adapter** — `src/listings/adapters/inmemory/inmemory_page_cache.py`, `inmemory_search_ranked_list_cache.py`. Dict + monotonic-time TTL. Test doubles only.

### 4. Repo change — `list_active_keyset`

Add one method to `PropertyListingRepository` (port + impl). The search path doesn't need a new repo method.

```python
async def list_active_keyset(
    self,
    *,
    filters: PropertyFilters,
    cursor: ListCursor | None,
    limit: int,
) -> tuple[list[PropertyListing], ListCursor | None]:
    """Keyset query ordered by (created_at DESC, id DESC). Fetches
    limit + 1 rows; the extra row indicates a `next_cursor` exists.
    Returns (page_items, next_cursor) where next_cursor is None at
    the tail."""
```

SQL:

```sql
WHERE status = 'active'
  AND <filters>
  AND (:cursor IS NULL OR (created_at, id) < (:cursor_created_at, :cursor_id))
ORDER BY created_at DESC, id DESC
LIMIT :limit + 1
```

The existing `idx_property_listings_pagination` (`status, created_at, id`) — created in migration `20260419_020000_n0o1p2q3r4s5` — already covers this query. No migration needed.

`PropertyFilters` keeps its `limit` / `offset` fields for the admin path (which still uses `list_active`). The cursor path passes `limit` as a separate argument and ignores any `offset` carried inside `filters`.

### 5. Use case changes

#### 5.1 `ListProperties` — keyset + L2 page cache

```python
class ListProperties:
    async def execute(
        self,
        *,
        filters: PropertyFilters,
        cursor: ListCursor | None,
        limit: int,
    ) -> CachedPage:
        fp = filter_fingerprint(q=None, filters=filters, location=None)
        suffix = "head" if cursor is None else f"{cursor.created_at.isoformat()}:{cursor.id}"
        key = build_cache_key(kind="list", fp=fp, suffix=suffix)

        hit = await self._cache.get(key)
        if hit is not None:
            log.info("listings_page_cache.hit", key_fp=key[-16:], kind="list")
            return hit

        items, next_cursor_obj = await self._repo.list_active_keyset(
            filters=filters, cursor=cursor, limit=limit
        )
        page = CachedPage(
            items=items,
            next_cursor=encode(next_cursor_obj) if next_cursor_obj else None,
        )
        await self._cache.set(key, page, self._ttl)
        log.info("listings_page_cache.miss", key_fp=key[-16:], kind="list")
        return page
```

No `total`. No `count_active` query.

#### 5.2 `SearchListings` — L1 ranked-id-list cache + use-case-side sort

```python
class SearchListings:
    async def execute(
        self,
        *,
        q: str,
        location: LocationFilter,
        filters: PropertyFilters,
        cursor: SearchCursor | None,
        limit: int,
    ) -> tuple[CachedPage, ParsedQuery]:
        fp = filter_fingerprint(q=q, filters=filters, location=location)
        ranked_key = build_cache_key(kind="search-ids", fp=fp, suffix="")

        ranked_ids = await self._search_ranked_list_cache.get(ranked_key)
        parsed: ParsedQuery
        if ranked_ids is None:
            parsed = await self._query_extractor.extract(q, location=location)
            ranked_ids = await self._vector_index.search(
                parsed=parsed,
                filters=filters,
                location=location,
                top_k=self._max_ranked_list_size,  # 200
            )
            await self._search_ranked_list_cache.set(
                ranked_key, ranked_ids, self._ttl
            )
            # Stash parsed under a sibling key so subsequent pages of
            # the same search don't re-run the LLM either. Same TTL.
            await self._parsed_query_cache.set(
                parsed_key(fp), parsed, self._ttl
            )
            log.info("search_ranked_list_cache.miss", key_fp=ranked_key[-16:])
        else:
            parsed = await self._parsed_query_cache.get(parsed_key(fp))
            if parsed is None:
                # Cold parsed-cache (TTL drift between the two keys).
                # Re-run the LLM rewrite to recover; reuse ranked_ids.
                parsed = await self._query_extractor.extract(q, location=location)
            log.info("search_ranked_list_cache.hit", key_fp=ranked_key[-16:])

        offset = cursor.offset if cursor else 0
        page_ids = ranked_ids[offset : offset + limit]
        if not page_ids:
            return CachedPage(items=[], next_cursor=None), parsed

        rows = await self._repo.list_by_ids(page_ids)
        order = {pid: i for i, pid in enumerate(page_ids)}
        rows.sort(key=lambda r: order[r.id])

        has_more = offset + limit < len(ranked_ids)
        next_cursor = (
            encode(SearchCursor(fp=fp, offset=offset + limit))
            if has_more else None
        )
        return CachedPage(items=rows, next_cursor=next_cursor), parsed
```

**Why no L2 page cache here?** After L1 (ranked-id list), each page is a Redis GET + a `WHERE id IN (...)` hydrate. The DB query for 20 PK lookups is sub-millisecond. Adding L2 buys ~1ms latency and costs memory + invalidation surface. Skip for v1.

**Order preservation** is solved in the use case itself, via `order = {pid: i ...}` + `rows.sort(key=...)`. No repo change. `list_by_ids` stays as-is.

**`parsed` is still returned to the route** so `_to_response_with_pois` can populate matched/unmatched POI buckets (ADR-014).

**`parsed_query_cache`** is a second `SearchRankedListCache`-shaped port (or — simpler — a third method pair on the same port). Implementation choice deferred; either works.

### 6. Route — `src/listings/adapters/api/routes/listings.py`

Public endpoint:

```python
@router.get("/properties", response_model=CursorPageResponse)
async def list_properties(
    request: Request,
    q: str | None = Query(None, max_length=2000),
    listing_type: ListingType | None = ...,
    typology: Typology | None = ...,
    min_price: Decimal | None = ...,
    max_price: Decimal | None = ...,
    parish: str | None = ...,
    municipality: str | None = ...,
    district: str | None = ...,
    cursor: str | None = Query(None, description="Opaque token from a prior response"),
    limit: int = Query(20, ge=1, le=20, description="Results per page (max 20)"),
):
    container = request.app.state.listing_container
    normalized_q = normalize_query(q)
    validate_location_for_search(normalized_q, parish, municipality, district)

    filters = PropertyFilters(...)  # no offset, no limit baked in for cursor path
    location = LocationFilter(parish=parish, municipality=municipality, district=district)
    fp = filter_fingerprint(q=normalized_q, filters=filters, location=location)

    decoded_cursor = None
    if cursor is not None:
        try:
            decoded_cursor = decode(cursor, expected_fp=fp)
        except CursorVersionError:
            raise HTTPException(400, detail="cursor_unsupported_version")
        except CursorFilterMismatchError:
            raise HTTPException(400, detail="cursor_filter_mismatch")
        except CursorDecodeError:
            raise HTTPException(400, detail="cursor_invalid")

    requested_pois: tuple[PoiCategory, ...] = ()
    if normalized_q is None or not getattr(container, "search_listings", None):
        # Discriminator type-check on the cursor.
        if decoded_cursor and not isinstance(decoded_cursor, ListCursor):
            raise HTTPException(400, detail="cursor_kind_mismatch")
        page = await container.list_properties.execute(
            filters=filters, cursor=decoded_cursor, limit=limit
        )
    else:
        if decoded_cursor and not isinstance(decoded_cursor, SearchCursor):
            raise HTTPException(400, detail="cursor_kind_mismatch")
        page, parsed = await container.search_listings.execute(
            q=normalized_q, location=location, filters=filters,
            cursor=decoded_cursor, limit=limit,
        )
        requested_pois = parsed.nearby_pois

    items = []
    for prop in page.items:
        image_urls = await _generate_image_urls(request, prop)
        items.append(_to_response_with_pois(prop, image_urls, requested_pois))

    return CursorPageResponse(items=items, next_cursor=page.next_cursor, limit=limit)
```

Admin endpoint stays byte-for-byte unchanged.

### 7. Response schema — `src/listings/adapters/api/schemas.py`

```python
class CursorPageResponse(BaseModel):
    items: list[ListedPropertyResponse]
    next_cursor: str | None
    limit: int
```

`PaginatedListingResponse` stays — admin still uses it.

### 8. Settings — `src/shared/config.py`

Add:

```python
redis_url: str = "redis://localhost:6379/0"
listings_page_cache_enabled: bool = False
listings_page_cache_ttl_seconds: int = 90
listings_search_ranked_list_size: int = 200
```

**Replace** `vector_index_top_k` with `listings_search_ranked_list_size` (default 200, was 50). The previous value was a per-page top_k; the new one is a per-(q, filters) top_k cached across pagination. Update `SearchListings`'s ceiling clamp (`min(top_k, limit+offset)` style logic at the use-case layer) to use the new name.

When `listings_page_cache_enabled=false`: container wires the Null adapters for both ports.

### 9. Container wiring — `src/listings/container.py`

```python
if settings.listings_page_cache_enabled:
    redis = aioredis.from_url(settings.redis_url, decode_responses=False)
    page_cache = RedisListingsPageCache(redis)
    ranked_list_cache = RedisSearchRankedListCache(redis)
else:
    page_cache = NullListingsPageCache()
    ranked_list_cache = NullSearchRankedListCache()

self.list_properties = ListProperties(
    repo=property_listing_repo,
    cache=page_cache,
    ttl_seconds=settings.listings_page_cache_ttl_seconds,
)

if settings.listings_search_enabled:
    self.search_listings = SearchListings(
        ...,
        search_ranked_list_cache=ranked_list_cache,
        parsed_query_cache=...,
        ttl_seconds=settings.listings_page_cache_ttl_seconds,
        max_ranked_list_size=settings.listings_search_ranked_list_size,
    )
```

### 10. `docker-compose.yml`

```yaml
redis:
  image: redis:7-alpine
  ports:
    - "6379:6379"
  command:
    [
      "redis-server",
      "--maxmemory", "256mb",
      "--maxmemory-policy", "allkeys-lru",
    ]
```

No volume.

### 11. Dependencies — `pyproject.toml`

- `redis[hiredis]>=5.0`
- `msgpack>=1.0`

## Affected files / surfaces

**New**
- `src/listings/domain/pagination/__init__.py`
- `src/listings/domain/pagination/cursor.py`
- `src/listings/application/ports/listings_page_cache.py`
- `src/listings/application/ports/search_ranked_list_cache.py`
- `src/listings/adapters/cache/__init__.py`
- `src/listings/adapters/cache/redis_page_cache.py`
- `src/listings/adapters/cache/redis_search_ranked_list_cache.py`
- `src/listings/adapters/cache/null_page_cache.py`
- `src/listings/adapters/cache/null_search_ranked_list_cache.py`
- `src/listings/adapters/inmemory/inmemory_page_cache.py`
- `src/listings/adapters/inmemory/inmemory_search_ranked_list_cache.py`
- `tests/unit/listings/pagination/test_cursor.py`
- `tests/unit/listings/cache/test_redis_page_cache.py`
- `tests/unit/listings/cache/test_redis_search_ranked_list_cache.py`
- `tests/unit/listings/cache/test_null_caches.py`
- `tests/integration/listings/test_keyset_pagination.py`
- `tests/integration/listings/test_search_cached_ranked_list.py`

**Modified**
- `src/listings/adapters/api/routes/listings.py` — cursor in, `total` out, kind-mismatch validation
- `src/listings/adapters/api/schemas.py` — `CursorPageResponse`
- `src/listings/application/use_cases/list_properties.py` — keyset + page cache
- `src/listings/application/use_cases/search_listings.py` — ranked-list cache + use-case-side sort
- `src/listings/application/ports/repositories/property_listing_repository.py` — `list_active_keyset`
- `src/listings/adapters/database/property_listing_repository.py` — implement `list_active_keyset`
- `src/listings/container.py` — wire both caches
- `src/shared/config.py` — settings (incl. rename `vector_index_top_k` → `listings_search_ranked_list_size`, value 50 → 200)
- `pyproject.toml`
- `docker-compose.yml`

**Docs**
- `docs/features/listings.md` — pagination shape + two-mode cache
- README — pagination section under listings

**No Alembic migration.** The required index already exists.

## Acceptance criteria

### List mode (`?q` empty)

- [ ] `GET /api/v1/listings/properties` accepts `?cursor=<token>&limit=N` with `1 ≤ limit ≤ 20`. `?offset=` is removed.
- [ ] Response shape: `{items, next_cursor, limit}`. `total` absent.
- [ ] Paging through ≥3 pages on a populated projection yields no duplicate or skipped rows; order matches `created_at DESC, id DESC`.
- [ ] Tail page returns `next_cursor: null`.
- [ ] Documented behavior: rows inserted after the head request with `created_at` newer than visible rows do **not** appear on subsequent pages of the same cursor chain (accepted keyset-pagination invariant).

### Search mode (`?q` set)

- [ ] First request for a new `(q, filters)` runs LLM + Pinecone once and caches the ranked-id-list.
- [ ] Second request for any page of the same `(q, filters)` within the TTL window does **not** call Pinecone or the LLM (verified by patching ports in integration test).
- [ ] Page `items` are returned in the cached ranked-list order (not DB scan order).
- [ ] Requesting `offset >= len(ranked_ids)` returns `{items: [], next_cursor: null}`.
- [ ] Bounded depth: pagination beyond `listings_search_ranked_list_size` results returns `next_cursor: null` — search depth ceiling.

### Cross-cutting

- [ ] Filter-mismatch cursor returns `400 cursor_filter_mismatch`.
- [ ] Unsupported-version cursor returns `400 cursor_unsupported_version`.
- [ ] Corrupt cursor returns `400 cursor_invalid`.
- [ ] Cursor whose `k` doesn't match the current request mode returns `400 cursor_kind_mismatch` (e.g. `SearchCursor` on a `?q`-empty request, or vice versa).
- [ ] With `LISTINGS_PAGE_CACHE_ENABLED=false`, both modes work end-to-end via Null adapters; every read goes to the DB / Pinecone.
- [ ] Redis down → both modes fall through to DB / Pinecone; warning logged, no 5xx.
- [ ] Cache events emit `key_fingerprint` (last 16 chars of the key) — never raw cursors, query strings, or filter contents.
- [ ] Admin endpoint `GET /api/v1/admin/listings/properties` is byte-for-byte unchanged.
- [ ] `docker compose up -d redis` brings up Redis; seeder + dev server work against it.
- [ ] `docs/features/listings.md` + README pagination section updated.

## Open questions

None blocking. Two implementation-level choices to make during the work, both flagged in §3 / §5.2:

- msgpack codec organization: keep `_listing_to_dict` co-located in the Redis adapter or hoist to a sibling `listing_codec.py` once it grows past ~60 LOC.
- `parsed_query_cache`: separate port vs. a third method pair on `SearchRankedListCache`. Same Redis adapter either way.

## Out of scope follow-ups

- Event-driven invalidation (ADR §6). With two cache namespaces, the listings worker subscribing to `PROPERTY_LISTING_UPDATED.v1` / `PROPERTY_LISTING_DELETED.v1` would need to invalidate both `listings:list:v1:*` and `listings:search-ids:v1:*`. Coarse but cheap.
- Single-flight protection if cache-miss thundering herds materialize at production volume.
- L2 page cache for the search path if the per-page hydrate becomes a measurable bottleneck.
- Row-level hydrate cache for `list_by_ids` (would also benefit non-listing fan-outs).
- Cursor pagination for the admin endpoint and other `OFFSET` surfaces once the cursor module has stabilized.

## Commits

Each independently mergeable:

1. `chore(listings): add redis to docker-compose + redis/msgpack deps`
2. `feat(listings): cursor value objects + filter fingerprint + codec`
3. `feat(listings): ListingsPageCache port + Null + InMemory adapters`
4. `feat(listings): SearchRankedListCache port + Null + InMemory adapters`
5. `feat(listings): RedisListingsPageCache + RedisSearchRankedListCache adapters`
6. `feat(listings): list_active_keyset on PropertyListingRepository`
7. `feat(listings): cursor pagination on ListProperties (keyset + L2 page cache)`
8. `feat(listings): ranked-list cache + use-case-side sort on SearchListings`
9. `feat(listings): cursor pagination on GET /api/v1/listings/properties (drops total, caps limit=20)`
10. `chore(listings): rename vector_index_top_k → listings_search_ranked_list_size (50 → 200)`
11. `docs(listings): update features doc + README for cursor + two-mode cache`
