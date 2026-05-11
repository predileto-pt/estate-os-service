# ADR-016: Cursor pagination + Redis page cache for the listings read path

**Date:** 2026-05-11
**Status:** Accepted — ready for implementation. Resolved questions captured in §7.

## Scope

This ADR covers a single endpoint: **`GET /api/v1/listings/properties`** (the public portal listings read path that the listings semantic-search work — ADR-013 / ADR-014 — landed on). Both variants of that endpoint are in scope:

- structured-filter mode (no `q`)
- semantic-search mode (`q` set)

Explicitly **out of scope**: the org-scoped admin endpoint `GET /api/v1/admin/listings/properties`. It continues to use offset/limit and is not cached. Same for every other `OFFSET`-based listing in the codebase (organizations, jobs, etc.) — those stay untouched.

## Context

`GET /api/v1/listings/properties` runs `ListProperties.execute(filters)` (or `SearchListings.execute(...)` when `q` is set), which fires **two queries per request** against the `property_listings` projection: a paginated `list_active` (or the search hydrate) + a `count_active` for the `total`. The ordering on the non-search path is `created_at DESC, id DESC` — stable, deterministic, indexable.

The FE wants infinite scroll on this endpoint. That changes two things:

1. **Pagination shape.** Offset/limit works but degrades the further you scroll — `OFFSET 1000` still scans 1000 rows. With a stable composite sort key (`created_at, id`) we can do keyset / cursor pagination instead, which is O(log n) per page regardless of position.
2. **Read pressure.** Even with cursor pagination, every scroll fires a request → DB. Listings change rarely (events drip in from the projector); the same first 3–4 pages dominate traffic. A cache layer in front of the repo would absorb that.

The semantic-search variant (`?q=…`, routed to `SearchListings`, ADR-013/014) is on the same URL. It's a different ranking shape (vector-ranked, not time-ordered), so the cursor envelope and the cache key namespace need a discriminator — but the route handler still sees one endpoint.

### Constraints worth naming up front

- **Hexagonal.** Caches are outbound infrastructure. They must live behind a port and be swappable for an in-memory test double — same pattern as repositories, event publishers, vector indexes.
- **Eventual consistency tolerated.** Listings are not transactional. A page cached for 60–120 s is fine; the projector + LLM enrichment already operate with multi-second lag.
- **No new top-level context.** This is plumbing inside `listings/`, not a new bounded context.

## Decision

### 1. Switch the public listings read path to cursor pagination

Replace `?offset=N&limit=N` with `?cursor=<token>&limit=N` on `GET /api/v1/listings/properties`. Drop `total` from its response (it required the second query and is meaningless for an infinite scroll). The admin sibling endpoint keeps its current shape.

`limit` is **capped at 20** (default 20). Down from today's 100 — infinite-scroll FE asks for one tick at a time, and a tighter cap keeps cache values small enough that msgpack-encoded pages comfortably fit Redis's per-key budget. Requests with `limit > 20` are 422'd at the schema layer.

New response shape:

```jsonc
{
  "items": [/* ListedPropertyResponse[] */],
  "next_cursor": "eyJ2IjoxLC..." | null,   // null when there are no more pages
  "limit": 20
}
```

Cursor token is an **opaque base64url-encoded JSON** value with a stable internal shape:

```jsonc
{
  "v": 1,                          // schema version — bump on incompatible change
  "k": "list" | "search",          // discriminator (matches the two variants of this endpoint)
  "fp": "<sha256(filters)[:16]>",  // filter fingerprint — see §5
  "c": "2026-05-11T08:30:00Z",     // last-item created_at (ISO) — `list` only
  "i": "af0bae64-c0f7-451a-8a1d-56d9b2867758"  // last-item id (tiebreaker) — `list` only
}
```

The handler validates `fp` against the current request's filter fingerprint. Mismatch → 400 `cursor_filter_mismatch`. This prevents accidental "same cursor, different filters" misuse and lets us cheaply reject cursors from a prior schema version (`v != 1`).

For the search path (`k == "search"`), the cursor carries `vector_score` and the originating `parsed_query_hash` instead of `c`/`i` — same envelope, different payload. The discriminator is what lets a single handler route to the right paginator.

### 2. Keyset query at the repo layer

Replace the offset clause in `PropertyListingRepository.list_active` with a tuple comparison:

```sql
WHERE status = 'active'
  AND (filters...)
  AND (created_at, id) < (:cursor_created_at, :cursor_id)
ORDER BY created_at DESC, id DESC
LIMIT :limit + 1
```

We fetch `limit + 1` rows; if we got the extra one, we drop it from the page and use the **last item kept** to mint `next_cursor`. The composite `(created_at, id)` comparison is supported by a single index (`idx_property_listings_created_at_id` — needs to exist or be added in this migration's prereqs).

No `count(*)` query. That's the read-pressure win even before the cache.

### 3. Page cache as an outbound port

Introduce a new port in the listings application layer:

```python
# src/listings/application/ports/listings_page_cache.py

@dataclass(frozen=True)
class CachedPage:
    items: list[PropertyListing]
    next_cursor: str | None

class ListingsPageCache(Protocol):
    async def get(self, key: str) -> CachedPage | None: ...
    async def set(self, key: str, page: CachedPage, ttl_seconds: int) -> None: ...
    async def invalidate_namespace(self, namespace: str) -> None: ...
```

Outbound adapters:

- `RedisListingsPageCache` — `listings/adapters/cache/redis_page_cache.py`. Uses `redis.asyncio`. Values are msgpack-encoded `PropertyListing` snapshots (same shape as the projection row), not JSON, so we don't burn CPU on Decimal/UUID coercion on every read.
- `InMemoryListingsPageCache` — `listings/adapters/inmemory/inmemory_page_cache.py`. Dict + monotonic-time expiry. Used in unit tests.

The container wires whichever the env flag selects (mirrors `listings_embedding_enabled` / `listings_search_enabled` style).

### 4. Where the cache call lives

The use case talks to the cache directly:

```python
class ListProperties:
    def __init__(self, repo, cache, ttl_seconds):
        self._repo = repo
        self._cache = cache
        self._ttl = ttl_seconds

    async def execute(self, filters, cursor) -> CachedPage:
        key = build_cache_key(kind="list", filters=filters, cursor=cursor)
        hit = await self._cache.get(key)
        if hit is not None:
            return hit
        page = await self._repo.list_keyset(filters, cursor)
        await self._cache.set(key, page, self._ttl)
        return page
```

Not a decorator. Rationale: only one strategy in v1, and a decorator obscures the cache-hit/miss event surface that we want for telemetry. If we add a second caching strategy later (e.g. row-level hydrate cache for the search path), we'll revisit — but YAGNI for now.

### 5. Cache key construction

```
listings:page:v1:{kind}:{filter_fingerprint}:{cursor_fingerprint}
```

- `kind` ∈ {`list`, `search:<parsed_query_hash>`}
- `filter_fingerprint` = `sha256(canonical_filter_json)[:16]` — same `fp` baked into the cursor
- `cursor_fingerprint` = the cursor's `(c, i)` joined, or `head` for the first page

The `v1` segment lets us flush the whole namespace on key-shape changes without touching individual keys.

### 6. Invalidation strategy

**v1: TTL only.** Default 90 s; configurable via `LISTINGS_PAGE_CACHE_TTL_SECONDS`. Rationale: projector + enrichment already produce multi-second staleness; a 90 s window on top of that is invisible to users and removes the need for a write-path subscriber in v1.

**v2 (not in this ADR's scope, but designed-for):** event-driven invalidation via the listings worker. The same worker that consumes `PROPERTY_LISTING_UPDATED.v1` / `PROPERTY_LISTING_DELETED.v1` would call `cache.invalidate_namespace("listings:page:v1:*")` — coarse but cheap. The port's `invalidate_namespace` method is in v1's signature precisely so adding this in v2 doesn't change shape.

### 7. Decisions resolved during review

- **Q1 — Hard-cut, no deprecation period.** Replace `?offset=` with `?cursor=` in the same release; no compat shim. Pre-1.0, single FE we control.
- **Q2 — Cache the search path in v1.** Both `?q`-set and `?q`-empty variants of `GET /api/v1/listings/properties` go through the cache. Search keys use `search:<parsed_query_hash>` as their discriminator (final hydrated page only). Hop-level caching of the LLM-rewrite / Pinecone steps is a follow-up.
- **Q3 — `limit` capped at 20** (default 20). See §1.
- **Q4 — Redis: no persistence, `--maxmemory 256mb --maxmemory-policy allkeys-lru`.** Cache is reproducible from the DB; production tunes its own values.

### 8. Infra changes

`docker-compose.yml` gains a Redis service:

```yaml
redis:
  image: redis:7-alpine
  ports:
    - "6379:6379"
  command: ["redis-server", "--maxmemory", "256mb", "--maxmemory-policy", "allkeys-lru"]
```

`Settings` (in `src/shared/config.py`):

```python
redis_url: str = "redis://localhost:6379/0"
listings_page_cache_enabled: bool = False
listings_page_cache_ttl_seconds: int = 90
```

Off-by-default flag, matching the prior pattern. When off, the container wires an `InMemoryListingsPageCache` that always misses + immediately evicts — i.e. caching becomes a no-op, but the call sites stay unchanged. (Alternative: wire a `NullListingsPageCache`. Either is fine; pick whichever is cleaner once we start the implementation.)

### 9. Failure modes

| Failure | Behavior |
|---|---|
| Redis down (connect / timeout) | Log warning, fall through to DB. Cache `set` after the DB read is best-effort (log on failure, don't raise). |
| Corrupt msgpack on `get` | Log warning, delete key, treat as miss. |
| Cursor schema bump (`v != 1`) | Return 400 `cursor_unsupported_version`; FE drops state and refetches from head. |
| Cursor filter mismatch | Return 400 `cursor_filter_mismatch`. |
| Stale data inside TTL | Bounded by `listings_page_cache_ttl_seconds`. Acceptable for v1; v2 adds event-driven invalidation. |

### 10. Telemetry

Three structured-log events at the use-case layer:

- `listings_page_cache.hit` — `key_fingerprint`, `kind`, `limit`, `items`
- `listings_page_cache.miss` — `key_fingerprint`, `kind`, `db_query_ms`
- `listings_page_cache.error` — `key_fingerprint`, `error`

`key_fingerprint` is the cache key's last 16 chars, never the raw cursor. That gives us hit-rate by `kind` without leaking filter contents into logs.

### 11. Out of scope (explicitly deferred)

- The admin endpoint `GET /api/v1/admin/listings/properties`. Stays on offset/limit, uncached.
- Every other `OFFSET`-paginated surface in the codebase (organizations listings, jobs queues, etc.).
- Distributed-lock thundering-herd protection (single-flight on cache miss). The expected read volume + 90 s TTL makes a herd recoverable. Worth revisiting once we have traffic numbers.
- Row-level hydrate cache for the search path (`list_by_ids`).
- Multi-region Redis / read replicas.
- Presigned image URL caching — these have their own ~1 h signature window; cache invalidation here is coupled to S3 credential rotation, not listings mutations.

## Consequences

**Wins**
- Half the DB queries per page (no `COUNT`).
- DB pressure further reduced by Redis once the flag is on.
- Cursor scrolling stays O(log n) at any depth.
- Cache is a port → tests use the in-memory adapter, no Redis in CI.

**Costs / risks**
- New piece of infra (Redis) to run locally and in prod.
- Cursor tokens are now part of the API contract — schema-versioned via `v`, but bumping it forces FE to handle the 400.
- Staleness window (90 s default) on the public listing path. Acceptable; documented.

## Follow-ups
- Event-driven invalidation (v2; see §6).
- Single-flight / cache-stampede protection if read volume warrants.
- Hop-level caching for the search pipeline.
- Possibly: extend cursor pagination to the admin endpoint and other `OFFSET`-paginated surfaces once the public endpoint's cursor utility module has proven itself.
