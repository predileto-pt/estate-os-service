# Listings cursor pagination + Redis cache (two-mode)

**Status:** shipped
**Created:** 2026-05-11
**ADR:** [docs/adr/016-listings-cursor-pagination-and-page-cache.md](../../docs/adr/016-listings-cursor-pagination-and-page-cache.md)

## Problem

`GET /api/v1/listings/properties` paginates with offset/limit and runs **two queries per request** (`list_active` + `count_active`). Every infinite-scroll tick on the public portal hits the DB. Listings change rarely, so the same first 3–4 pages dominate read traffic with no cache absorbing it. Offset performance also degrades with depth.

The endpoint has two functionally distinct modes hidden behind the same URL:

- **List mode** (`?q` empty) — structured filters, ordered by `created_at DESC, id DESC`. Monotonic indexed sort key — keyset pagination works to any depth.
- **Search mode** (`?q` set) — Pinecone vector ranking. No native keyset; "next page" is implemented by enlarging `top_k` and slicing.

A uniform "cursor pagination" model papers over this difference and forces an awkward search-path implementation (per-page Pinecone calls, sort hacks for `list_by_ids` order preservation). The spec treats the two modes as architecturally distinct underneath, while keeping a single opaque cursor token on the wire.

## Goal

`GET /api/v1/listings/properties` returns cursor-paginated results from Redis-backed caches. List mode uses keyset + per-page cache; search mode uses a bounded cached `(parsed_query, ranked_ids)` tuple + per-page hydrate. No `COUNT(*)` on either path. ADR-016 is the architectural authority.

## Non-goals

- Admin endpoint `GET /api/v1/admin/listings/properties` and every other `OFFSET` surface — they stay as-is.
- Event-driven invalidation. v1 is TTL-only.
- Single-flight / cache-stampede protection.
- Hop-level caching of the LLM rewrite (now covered atomically alongside `ranked_ids`; the "hop-level" follow-up is no longer relevant).
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
    """sha256(_canonical_json(binding_inputs))[:16].

    Binds the cursor to the (q, listing_type, typology, min_price,
    max_price, parish, municipality, district, location) tuple that
    produced it. **Explicitly excludes `limit` and `offset`** — those
    are pagination concerns, not filter identity. Cursor must stay
    valid if the FE changes page size mid-scroll."""

def encode(cursor: ListCursor | SearchCursor) -> str: ...

def decode_token(token: str) -> ListCursor | SearchCursor:
    """Decodes the envelope and returns the typed cursor. Raises
    CursorVersionError (bad v), CursorDecodeError (corrupt b64/JSON,
    missing fields, unknown `k`). **Does not check fp** — that's
    the caller's job, after the kind check, so error precedence is
    version > invalid > kind > filter.

    Dispatch (illustrative):

        raw = json.loads(base64url_decode(token))
        if raw["v"] != CURSOR_SCHEMA_VERSION:
            raise CursorVersionError(raw["v"])
        if raw["k"] == "list":
            return ListCursor(
                fp=raw["fp"],
                created_at=datetime.fromisoformat(raw["c"]),
                id=UUID(raw["i"]),
            )
        if raw["k"] == "search":
            return SearchCursor(fp=raw["fp"], offset=int(raw["o"]))
        raise CursorDecodeError(f"unknown cursor kind: {raw['k']!r}")
    """

def validate_fp(cursor: ListCursor | SearchCursor, *, expected_fp: str) -> None:
    """Raises CursorFilterMismatchError if cursor.fp != expected_fp."""
```

Two-step decode is deliberate: the route checks cursor kind (list vs search) *between* `decode_token` and `validate_fp`, so a list cursor presented in search mode surfaces as `cursor_kind_mismatch` (mode changed — FE should drop cursor and retry) instead of `cursor_filter_mismatch` (filters changed — same recovery but misleading reason).

Encoded JSON payloads (what `encode` writes inside the base64url envelope):

```
ListCursor   → {"v":1,"k":"list",  "fp":"<16-hex>","c":"<iso-datetime>","i":"<uuid>"}
SearchCursor → {"v":1,"k":"search","fp":"<16-hex>","o":<int>}
```

Errors:

- `CursorVersionError` → 400 `cursor_unsupported_version`
- `CursorDecodeError` → 400 `cursor_invalid` (corrupt base64 / JSON / missing fields / unknown `k`)
- (kind mismatch handled in the route — see §6) → 400 `cursor_kind_mismatch`
- `CursorFilterMismatchError` → 400 `cursor_filter_mismatch`

### Canonicalization rules (used by `filter_fingerprint`)

Required so the same logical filter set produces the same hash across Python versions, library upgrades, and process boundaries:

- **JSON shape**: `json.dumps(d, sort_keys=True, separators=(",", ":"))`. Sorted keys, no whitespace.
- **`None` / missing**: omit keys whose value is `None` (do not emit `"parish": null`).
- **`Decimal`** (prices): `str(value.normalize())`. Strips trailing zeros so `Decimal("380000")` and `Decimal("380000.00")` hash identically.
- **`Enum`** (`ListingType`, `Typology`): use `value.value`, not `value.name` — `"sale"`, not `"SALE"`.
- **`UUID`**: not used in the fingerprint today, but if added later: `str(uuid)` (always lowercase, hyphenated).
- **`str`**: `.strip().lower()` for free-text location fields (parish/municipality/district) so case + whitespace differences from the FE don't fork the cache. The route already normalises `q` via `normalize_query`; no re-normalisation needed here.

A small `_canonicalize(obj) -> dict` helper applies these and is the single source of truth; `filter_fingerprint` is then `sha256(json.dumps(_canonicalize(...))).hexdigest()[:16]`.

Cache-key helper:

```python
def build_list_cache_key(*, fp: str, cursor: ListCursor | None, limit: int) -> str:
    """`listings:list:v1:{fp}:{cursor_part}:{limit}`.
    cursor_part = "head" for the first page, else "{iso}:{uuid}".
    `limit` is in the key — same fp + same cursor + different limit
    is a different cached page."""

def build_search_cache_key(*, fp: str) -> str:
    """`listings:search:v1:{fp}`. The cached value contains the full
    ranked list; `limit` and `offset` are applied at slice time, so
    they don't appear in the key."""
```

### 2. Cache ports

Two narrow ports — one per pagination mode. Asymmetric on purpose: list mode caches whole pages; search mode caches the search result envelope (parsed query + ranked ids) and slices at request time.

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

# src/listings/application/ports/search_result_cache.py (new)
# ParsedQuery lives at src/listings/domain/parsed_query.py (ADR-014).
@dataclass(frozen=True)
class CachedSearchResult:
    parsed: ParsedQuery
    ranked_ids: list[UUID]

class SearchResultCache(Protocol):
    async def get(self, key: str) -> CachedSearchResult | None: ...
    async def set(self, key: str, result: CachedSearchResult, ttl_seconds: int) -> None: ...
    async def invalidate_namespace(self, namespace: str) -> None: ...
```

`CachedSearchResult` carries `parsed` + `ranked_ids` together in a single atomic value. A cache hit means **no LLM call and no Pinecone call** for any page of that `(q, filters)` combination — and there's no TTL-drift recovery branch because there's only one TTL.

`ListingsPageCache` is consumed only by `ListProperties`. `SearchResultCache` is consumed only by `SearchListings`.

### 3. Cache adapters — three flavors per port

For each port:

- **Redis adapter** — `redis_page_cache.py`, `redis_search_result_cache.py`. Both consume a shared `redis.asyncio.Redis` client (one connection pool). Value codec is msgpack with primitive-dict helpers (`_listing_to_dict` / `_listing_from_dict` for the page cache; `_parsed_query_to_dict` / `_ranked_ids_to_dict` for the search cache). UUIDs → str, Decimals → str, datetimes → ISO, enums → value. **Adapters' `get` reconstructs typed values** from the primitive dicts (UUIDs from strings, datetimes from ISO, enums from values) so use cases always see domain types — the use-case-side `rows.sort(key=lambda r: order[r.id])` in §5.2 depends on UUID keys, not str keys. On any deserialization or connection error: `get` returns `None`, `set` is best-effort (warning log, no raise).
- **Null adapter** — `null_page_cache.py`, `null_search_result_cache.py`. Always-miss `get`, no-op `set` / `invalidate_namespace`. Wired when `LISTINGS_PAGE_CACHE_ENABLED=false`.
- **In-memory adapter** — `inmemory_page_cache.py`, `inmemory_search_result_cache.py`. Dict + monotonic-time TTL. Test doubles only.

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

SQLAlchemy impl (the row-value comparison is non-obvious — `tuple_` builds the composite expression; the right side must use the same Python types as the column models or the asyncpg driver will reject the comparison):

```python
from sqlalchemy import tuple_

query = select(PropertyListingModel).where(
    PropertyListingModel.status == PropertyStatus.ACTIVE,
    # ...other filter predicates...
)
if cursor is not None:
    query = query.where(
        tuple_(PropertyListingModel.created_at, PropertyListingModel.id)
        < tuple_(cursor.created_at, str(cursor.id))
    )
query = query.order_by(
    PropertyListingModel.created_at.desc(),
    PropertyListingModel.id.desc(),
).limit(limit + 1)
```

**asyncpg fallback:** SQLAlchemy's row-value `tuple_(...) < tuple_(...)` has historically been flaky over the asyncpg driver. If the implementation hits driver issues, expand to the logically-equivalent OR form (same plan, no row-value binding):

```python
from sqlalchemy import and_, or_
query = query.where(
    or_(
        PropertyListingModel.created_at < cursor.created_at,
        and_(
            PropertyListingModel.created_at == cursor.created_at,
            PropertyListingModel.id < str(cursor.id),
        ),
    )
)
```

The existing `idx_property_listings_pagination` (`status, created_at, id`) — created in migration `20260419_020000_n0o1p2q3r4s5` — covers both forms. **No migration needed.**

**`PropertyFilters` field treatment.** Change `limit` and `offset` to `int | None = None`. The cursor path leaves them unset (passes `limit` as a separate arg). The admin endpoint continues to set them explicitly and call the existing `list_active` / `count_active` methods. Document this on the dataclass.

### 5. Use case changes

#### 5.1 `ListProperties` — keyset + page cache

```python
class ListProperties:
    async def execute(
        self,
        *,
        fp: str,                       # computed by the route; not recomputed here
        filters: PropertyFilters,
        cursor: ListCursor | None,
        limit: int,
    ) -> CachedPage:
        key = build_list_cache_key(fp=fp, cursor=cursor, limit=limit)

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

#### 5.2 `SearchListings` — single search-result cache + use-case-side sort

```python
class SearchListings:
    async def execute(
        self,
        *,
        fp: str,                       # computed by the route; not recomputed here
        q: str,
        location: LocationFilter,
        filters: PropertyFilters,
        cursor: SearchCursor | None,
        limit: int,
    ) -> tuple[CachedPage, ParsedQuery]:
        key = build_search_cache_key(fp=fp)

        hit = await self._search_cache.get(key)
        if hit is None:
            parsed = await self._query_extractor.extract(q, location=location)
            ranked_ids = await self._vector_index.search(
                parsed=parsed,
                filters=filters,
                location=location,
                top_k=self._max_ranked_list_size,  # 200
            )
            hit = CachedSearchResult(parsed=parsed, ranked_ids=ranked_ids)
            await self._search_cache.set(key, hit, self._ttl)
            log.info("search_result_cache.miss", key_fp=key[-16:])
        else:
            log.info("search_result_cache.hit", key_fp=key[-16:])

        offset = cursor.offset if cursor else 0
        page_ids = hit.ranked_ids[offset : offset + limit]
        if not page_ids:
            return CachedPage(items=[], next_cursor=None), hit.parsed

        rows = await self._repo.list_by_ids(page_ids)
        order = {pid: i for i, pid in enumerate(page_ids)}
        rows.sort(key=lambda r: order[r.id])

        has_more = offset + limit < len(hit.ranked_ids)
        next_cursor = (
            encode(SearchCursor(fp=fp, offset=offset + limit))
            if has_more else None
        )
        return CachedPage(items=rows, next_cursor=next_cursor), hit.parsed
```

**Why no L2 page cache for search?** After the search-result cache hit, each page is a Redis GET + a `WHERE id IN (...)` hydrate. The DB query for 20 PK lookups is sub-millisecond. Adding L2 buys ~1ms latency and costs memory + invalidation surface. Skip for v1.

**Order preservation** is solved in the use case via `order = {pid: i ...}` + `rows.sort(key=...)`. No repo change. `list_by_ids` stays as-is.

**`parsed` is still returned to the route** so `_to_response_with_pois` can populate matched/unmatched POI buckets (ADR-014). It's pulled from the cached value on hit, so the LLM is never invoked twice for the same `(q, filters)` within a TTL window.

**Old `min(top_k, limit+offset)` clamp logic is removed entirely.** Under the new design the first Pinecone call always fetches `listings_search_ranked_list_size` (200) IDs; subsequent pages slice from cache. The clamp made sense when each page hit Pinecone with a custom `top_k`; it doesn't make sense now.

**Signature rename:** the existing route calls `SearchListings.execute(query=normalized_q, ...)`. The new keyword is `q=` (matches the route's `q` query param and the rest of this spec). Trivial substitution at the single callsite in `routes/listings.py`.

**Search-path cache-expiry invariant** (analog of the keyset "lost insert" on the list path): if the ranked-id-list cache expires mid-scroll, the next page request misses the cache, refetches Pinecone, and may receive a slightly different ranking. The cursor's `offset` then points into a list that's *almost* the same but not byte-identical — the user may see a small number of duplicated or skipped items at the page boundary where the expiry happened. Accepted v1 behavior; visible only when the underlying ranking actually changes within the TTL window (rare for a 90 s default).

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

    is_search_mode = (
        normalized_q is not None
        and getattr(container, "search_listings", None) is not None
    )

    # Each mode owns location in exactly one place: `filters` for
    # list, `location` for search. Building `filters` mode-aware
    # avoids double-counting parish/municipality/district in the
    # fingerprint and matches each downstream use case's actual
    # consumption (list reads location from filters; search reads it
    # from LocationFilter and ignores any location fields on filters).
    filters = PropertyFilters(
        listing_type=listing_type, typology=typology,
        min_price=min_price, max_price=max_price,
        parish=parish if not is_search_mode else None,
        municipality=municipality if not is_search_mode else None,
        district=district if not is_search_mode else None,
        # limit / offset omitted — cursor path uses `limit` arg directly
    )
    location = LocationFilter(
        parish=parish, municipality=municipality, district=district,
    ) if is_search_mode else None
    fp = filter_fingerprint(
        q=normalized_q if is_search_mode else None,
        filters=filters,
        location=location,
    )

    # Two-step decode: kind check sits between the envelope decode and
    # the fp validation, so error precedence is
    # version > invalid > kind > filter — see §1.
    decoded_cursor = None
    if cursor is not None:
        try:
            decoded_cursor = decode_token(cursor)
        except CursorVersionError:
            raise HTTPException(400, detail="cursor_unsupported_version")
        except CursorDecodeError:
            raise HTTPException(400, detail="cursor_invalid")

        expected_kind = SearchCursor if is_search_mode else ListCursor
        if not isinstance(decoded_cursor, expected_kind):
            raise HTTPException(400, detail="cursor_kind_mismatch")

        try:
            validate_fp(decoded_cursor, expected_fp=fp)
        except CursorFilterMismatchError:
            raise HTTPException(400, detail="cursor_filter_mismatch")

    requested_pois: tuple[PoiCategory, ...] = ()
    if not is_search_mode:
        page = await container.list_properties.execute(
            fp=fp, filters=filters, cursor=decoded_cursor, limit=limit,
        )
    else:
        page, parsed = await container.search_listings.execute(
            fp=fp, q=normalized_q, location=location, filters=filters,
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

**Edge case — search disabled mid-pagination.** If `LISTINGS_SEARCH_ENABLED` is toggled off between deploys, an FE paging through `?q=...&cursor=<SearchCursor>` will hit list mode and get `400 cursor_kind_mismatch`. The FE should treat any `cursor_kind_mismatch` response as "refresh from head" (drop cursor + retry without it). Document this contract in the FE-facing error description.

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

**Rename + remove logic** for `vector_index_top_k`:

- Rename setting: `vector_index_top_k` → `listings_search_ranked_list_size`, default `50` → `200`.
- Remove the `min(top_k, limit+offset)` clamp in `SearchListings` entirely. The new field is consumed exactly once per cache miss as the Pinecone `top_k`. Pagination beyond it returns `next_cursor: null` — that's the documented search-depth ceiling.

When `listings_page_cache_enabled=false`: container wires the Null adapters for both ports.

### 9. Container wiring — `src/listings/container.py`

```python
# Redis client lifetime == container lifetime. The container is
# constructed once at app startup and torn down on shutdown. One
# client shared between both cache adapters — they're stateless
# wrappers around the shared pool.
self._redis: aioredis.Redis | None = None
if settings.listings_page_cache_enabled:
    self._redis = aioredis.from_url(settings.redis_url, decode_responses=False)
    page_cache = RedisListingsPageCache(self._redis)
    search_cache = RedisSearchResultCache(self._redis)
else:
    page_cache = NullListingsPageCache()
    search_cache = NullSearchResultCache()

self.list_properties = ListProperties(
    repo=property_listing_repo,
    cache=page_cache,
    ttl_seconds=settings.listings_page_cache_ttl_seconds,
)

if settings.listings_search_enabled:
    self.search_listings = SearchListings(
        ...,
        search_cache=search_cache,
        ttl_seconds=settings.listings_page_cache_ttl_seconds,
        max_ranked_list_size=settings.listings_search_ranked_list_size,
    )

async def close(self) -> None:
    """Called by the FastAPI lifespan handler in `shared/main.py` on
    app shutdown. Drains the redis connection pool when the cache is
    enabled; no-op otherwise."""
    if self._redis is not None:
        await self._redis.aclose()
```

The lifespan handler in `src/shared/main.py` needs one new line:

```python
await app.state.listing_container.close()
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
- `src/listings/application/ports/search_result_cache.py`
- `src/listings/adapters/cache/__init__.py`
- `src/listings/adapters/cache/redis_page_cache.py`
- `src/listings/adapters/cache/redis_search_result_cache.py`
- `src/listings/adapters/cache/null_page_cache.py`
- `src/listings/adapters/cache/null_search_result_cache.py`
- `src/listings/adapters/inmemory/inmemory_page_cache.py`
- `src/listings/adapters/inmemory/inmemory_search_result_cache.py`
- `tests/unit/listings/pagination/test_cursor.py`
- `tests/unit/listings/cache/test_redis_page_cache.py`
- `tests/unit/listings/cache/test_redis_search_result_cache.py`
- `tests/unit/listings/cache/test_null_caches.py`
- `tests/integration/listings/test_keyset_pagination.py`
- `tests/integration/listings/test_search_result_cache.py`

**Modified**
- `src/listings/adapters/api/routes/listings.py` — cursor in, `total` out, kind-mismatch validation
- `src/listings/adapters/api/schemas.py` — `CursorPageResponse`
- `src/listings/application/use_cases/list_properties.py` — keyset + page cache
- `src/listings/application/use_cases/search_listings.py` — single search-result cache + use-case-side sort; remove `min(top_k, limit+offset)` clamp
- `src/listings/application/ports/repositories/property_listing_repository.py` — `list_active_keyset`
- `src/listings/adapters/database/property_listing_repository.py` — implement `list_active_keyset`
- `src/listings/domain/property_filters.py` (or wherever `PropertyFilters` lives) — `limit` and `offset` to `int | None = None`, document admin-only usage
- `src/listings/container.py` — wire both caches; add `async def close(self)` for the lifespan handler
- `src/shared/main.py` — call `await app.state.listing_container.close()` in the shutdown branch of the FastAPI lifespan
- `src/shared/config.py` — settings (incl. rename `vector_index_top_k` → `listings_search_ranked_list_size`, value 50 → 200)
- `.env.example` — add `REDIS_URL`, `LISTINGS_PAGE_CACHE_ENABLED`, `LISTINGS_PAGE_CACHE_TTL_SECONDS`, `LISTINGS_SEARCH_RANKED_LIST_SIZE`; remove `VECTOR_INDEX_TOP_K`
- `tests/unit/listings/test_list_properties_use_case.py` — update for the cursor/cache signature
- `tests/unit/listings/test_search_listings_use_case.py` — update for the cursor/cache signature; remove the `min(top_k, limit+offset)` clamp coverage
- `tests/integration/listings/test_listings_routes.py` (or whatever the existing route test file is named) — replace offset/limit assertions with cursor; add kind-mismatch + filter-mismatch + version-mismatch coverage
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
- [ ] **Cache key includes `limit`**: `limit=10` and `limit=20` requests at the same cursor position hit different cache keys (verified in unit test on `build_list_cache_key`).
- [ ] Documented behavior: rows inserted after the head request with `created_at` newer than visible rows do **not** appear on subsequent pages of the same cursor chain (accepted keyset-pagination invariant).

### Search mode (`?q` set)

- [ ] First request for a new `(q, filters)` runs LLM + Pinecone once and caches `CachedSearchResult(parsed, ranked_ids)` atomically.
- [ ] Second request for any page of the same `(q, filters)` within the TTL window does **not** call Pinecone **or** the LLM, and calls `repo.list_by_ids` **exactly once** for the requested page (verified by patching all three in integration test and asserting invocation counts of 0, 0, 1).
- [ ] Page `items` are returned in the cached ranked-list order (not DB scan order).
- [ ] Requesting `offset >= len(ranked_ids)` returns `{items: [], next_cursor: null}`.
- [ ] Bounded depth: pagination beyond `listings_search_ranked_list_size` results returns `next_cursor: null` — search depth ceiling.
- [ ] `parsed.nearby_pois` is populated on every response (hit or miss), so matched/unmatched POI buckets stay correct under cache hits.

### Cross-cutting

- [ ] Filter-mismatch cursor returns `400 cursor_filter_mismatch`.
- [ ] Unsupported-version cursor returns `400 cursor_unsupported_version`.
- [ ] Corrupt cursor returns `400 cursor_invalid`.
- [ ] Cursor whose `k` doesn't match the current request mode returns `400 cursor_kind_mismatch` — covering both `SearchCursor`-on-list and `ListCursor`-on-search.
- [ ] **Error precedence**: when both kind and fp mismatch (which happens whenever the mode flips, since list-fp ≠ search-fp), `cursor_kind_mismatch` is raised, *not* `cursor_filter_mismatch`. Verified by a unit test that constructs a list cursor with arbitrary fp and submits it to a search-mode request.
- [ ] **FE recovery contract** for `cursor_kind_mismatch`: documented as "drop cursor + retry without it" in the OpenAPI error description so the FE can branch cleanly when search gets toggled off mid-scroll.
- [ ] `filter_fingerprint` excludes `limit` and `offset` (verified by unit test: two `PropertyFilters` differing only in `limit`/`offset` produce the same fingerprint).
- [ ] With `LISTINGS_PAGE_CACHE_ENABLED=false`, both modes work end-to-end via Null adapters; every read goes to the DB / Pinecone.
- [ ] Redis down → both modes fall through to DB / Pinecone; warning logged, no 5xx.
- [ ] Cache events emit `key_fingerprint` (last 16 chars of the key) — never raw cursors, query strings, or filter contents.
- [ ] Admin endpoint `GET /api/v1/admin/listings/properties` is byte-for-byte unchanged.
- [ ] `docker compose up -d redis` brings up Redis; seeder + dev server work against it.
- [ ] `docs/features/listings.md` + README pagination section updated.

## Open questions

None blocking. One implementation-level choice during the work, flagged in §3:

- msgpack codec organization: keep `_listing_to_dict` co-located in `redis_page_cache.py` and `_parsed_query_to_dict` / `_ranked_ids_to_dict` in `redis_search_result_cache.py`, or hoist to a sibling `listing_codec.py` once any grows past ~60 LOC.

## Out of scope follow-ups

- Event-driven invalidation (ADR §6). With two cache namespaces, the listings worker subscribing to `PROPERTY_LISTING_UPDATED.v1` / `PROPERTY_LISTING_DELETED.v1` would need to invalidate both `listings:list:v1:*` and `listings:search:v1:*`. Coarse but cheap.
- Single-flight protection if cache-miss thundering herds materialize at production volume.
- L2 page cache for the search path if the per-page hydrate becomes a measurable bottleneck.
- Row-level hydrate cache for `list_by_ids` (would also benefit non-listing fan-outs).
- Cursor pagination for the admin endpoint and other `OFFSET` surfaces once the cursor module has stabilized.

## Commits

Each independently mergeable, and each leaves the build green. The use-case signature changes and the route flip are bundled into a single commit (#8) so there's no intermediate state where the route calls a stale signature.

1. `chore(listings): add redis to docker-compose + redis/msgpack deps`
2. `feat(listings): cursor value objects + filter fingerprint + codec`
3. `feat(listings): ListingsPageCache port + Null + InMemory adapters`
4. `feat(listings): SearchResultCache port + Null + InMemory adapters`
5. `feat(listings): RedisListingsPageCache + RedisSearchResultCache adapters`
6. `feat(listings): list_active_keyset on PropertyListingRepository`
7. `chore(listings): rename vector_index_top_k → listings_search_ranked_list_size (50 → 200); drop top_k clamp`
8. `feat(listings): cursor pagination + two-mode cache on GET /api/v1/listings/properties` — bundles `ListProperties` + `SearchListings` signature changes with the route flip (drops total, caps limit=20, wires both caches in the container); single fat commit because splitting it across the use-case rewrites and the route would leave the build red between them.
9. `docs(listings): update features doc + README for cursor + two-mode cache`
