# Redis cache for property listing endpoints

**Status:** draft
**Owner:** Peter
**Created:** 2026-04-20

## Problem

Two read-heavy endpoints today hit Postgres on every request and return data that changes rarely:

1. **Public listings** — `GET /api/v1/listings/properties` (`src/listings/adapters/api/routes/listings.py:83`) + `GET /api/v1/listings/properties/{id}` (line 125). Every anonymous search / property view issues DB queries through `listings.ListProperties` / `GetProperty` against either the legacy `ReadPropertyModel` (mirroring `properties`) or — after the carried-state projection lands — the new `property_listings` read-model table.
2. **Admin property list** — `GET /api/v1/admin/properties?organization_id=X` (`src/properties/adapters/api/routes/properties.py:147`) + `GET /api/v1/admin/properties/{id}` (line 193). Every admin page load issues DB queries through `properties.ListProperties` / `GetProperty`.

Neither data set changes often relative to how often it's read (properties are created/edited by agents on a minute-scale; listings pages are refreshed by applicants on a second-scale). Caching these endpoints is free throughput + latency headroom.

Two infra realities that make this specifically easy now:
- The **carried-state event pipeline** just shipped — `PROPERTY_CREATED.v1` / `PROPERTY_UPDATED.v1` / `PROPERTY_DELETED.v1` already flow to the listings events worker. Event-driven cache invalidation hooks onto those handlers for free.
- The service runs against a **single Redis instance** already required by prod for session / rate-limit work (not yet deployed in this repo — this spec adds the docker-compose service).

## Goal

Add a Redis-backed cache to both endpoint pairs with **event-driven invalidation** on property lifecycle events + a **24-hour TTL backstop**, implemented via a `Cache` Protocol port (hexagonal) with `RedisCache` (prod) and `InMemoryCache` (tests) adapters. p95 DB queries on the two endpoints drop by the cache hit rate.

## Non-goals

- **No caching of write paths.** Every `POST` / `PATCH` / `DELETE` hits DB as today. Writes emit events; events invalidate caches.
- **No caching of the extraction / screening / booking / contract endpoints.** Only the two listing pairs scoped here. Other endpoints are either per-user (low hit rate) or already fast enough.
- **No CDN-layer caching.** This is application-layer Redis caching. A CDN is a separate infra PR.
- **No cache of aggregate Property objects across routes.** We cache the serialized response payload (or a close cousin — see §Approach) keyed per endpoint, not the domain aggregates themselves. Aggregate-level caching across the properties container would bleed write-side concerns into reads.
- **No Redis Cluster / Sentinel setup.** Single-instance Redis is enough at <1000 DAU. Cluster is a follow-up if we ever need horizontal scale.
- **No warming on boot.** Cache is populated lazily on first miss. Cold start is fine.
- **No cache for authenticated `/auth/me` / membership / subscription endpoints.** Those change when memberships change and are per-user; the complexity isn't worth the hit rate.

## Approach

### Cache port (clean architecture)

New Protocol in `src/shared/cache/` (new shared module — caching is cross-cutting infrastructure, not bounded-context domain):

```python
# src/shared/cache/ports.py
from typing import Protocol

class Cache(Protocol):
    async def get(self, key: str) -> bytes | None: ...
    async def set(self, key: str, value: bytes, *, ttl_seconds: int) -> None: ...
    async def delete(self, key: str) -> None: ...
    async def delete_pattern(self, pattern: str) -> int:
        """Delete every key matching the glob-style pattern. Returns count."""
```

Values are raw bytes (JSON-encoded payloads, not domain objects). The port is transport-agnostic — no Redis-specific types leak.

### Adapters

- **`src/shared/cache/adapters/redis_cache.py`** — `RedisCache` using `redis.asyncio.Redis`. Connection pool from a single `Redis.from_url(settings.redis_url)` instance created at bootstrap. `delete_pattern` uses `SCAN` with cursor iteration (never `KEYS` — O(N) blocks the server).
- **`src/shared/cache/adapters/inmemory_cache.py`** — `InMemoryCache`. Dict + per-key TTL tracked against `time.monotonic()`. `delete_pattern` uses `fnmatch`. Used by every unit test that touches a cached use case.

### Where caching lives (Q = "use-case level")

Two decorator-style wrappers at the use-case level — one per endpoint pair — NOT at the repository or HTTP layer. Use cases stay pure; cache is a decorator injected at container construction.

```
src/listings/application/use_cases/cached_list_properties.py
src/listings/application/use_cases/cached_get_property.py
src/properties/application/use_cases/cached_list_properties.py
src/properties/application/use_cases/cached_get_property.py
```

Each decorator:
1. Builds a cache key from its inputs (filters + org_id for admin, filters for public).
2. `cache.get(key)` → if hit, decode JSON → return domain objects or the pre-serialized response.
3. If miss, call the wrapped use case, serialize, `cache.set(key, payload, ttl_seconds=86400)`, return.

**Cached payload shape:** the domain-object list (or single object) serialized to JSON via the existing response-schema Pydantic models. This keeps the route handlers unchanged — they still receive domain-shaped data and run their existing `_property_response` mappers. The only cost is one JSON encode/decode round-trip per miss/hit, which is negligible vs. DB latency.

### Cache keys (Q = "per-organization" scoping)

| Endpoint | Key |
|---|---|
| `GET /api/v1/listings/properties?<filters>` | `listings:list:{filters_hash}` |
| `GET /api/v1/listings/properties/{id}` | `listings:property:{id}` |
| `GET /api/v1/admin/properties?organization_id={org}&<filters>` | `admin:properties:list:{org}:{filters_hash}` |
| `GET /api/v1/admin/properties/{id}` | `admin:properties:{org}:{id}` |

`filters_hash` = short stable hash (first 16 hex chars of `sha256(sorted_filter_repr)`). Uses a pure helper `shared.cache.keys.hash_filters(filters: dict) -> str` — unit-tested for stability.

### Event-driven invalidation (Q = "event-driven")

The listings events worker already subscribes to `PROPERTY_CREATED.v1` / `UPDATED.v1` / `DELETED.v1`. Add one more handler registration:

```python
# src/listings/entrypoints/events_worker.py
router.on(PROPERTY_CREATED_V1, handle_cache_invalidation)
router.on(PROPERTY_UPDATED_V1, handle_cache_invalidation)
router.on(PROPERTY_DELETED_V1, handle_cache_invalidation)
```

New handler at `src/shared/cache/handlers/property_cache_invalidation.py`:

```python
async def handle_cache_invalidation(event: DomainEvent, context: dict) -> None:
    cache = context["cache"]
    property_id = event.data["id"]
    org_id = event.data.get("organization_id")  # present on CREATED/UPDATED/DELETED

    # Public keys: any list result might include this property → nuke them all.
    # The public listings are shared across all visitors so the blast radius
    # is bounded (one org's change clears the whole listings list cache).
    await cache.delete_pattern("listings:list:*")
    await cache.delete(f"listings:property:{property_id}")

    # Admin keys: scoped to this org only.
    await cache.delete_pattern(f"admin:properties:list:{org_id}:*")
    await cache.delete(f"admin:properties:{org_id}:{property_id}")
```

This lives in `shared/cache/handlers/` rather than a context-specific workers/ directory because it's a cross-cutting concern — cache invalidation spans both `listings` and `properties` contexts.

**Hybrid TTL backstop:** every `set` uses a 24-hour TTL. If an invalidation event is ever lost (network flake, DLQ), entries self-heal within 24h. Combined with event invalidation, staleness is bounded by `min(time-since-last-event-published, 24h)`.

### Wiring at bootstrap

`src/shared/entrypoints/bootstrap.py` gains a module-level `_cache: Cache | None` and `get_cache()` factory that returns the single Redis-backed `Cache` instance (or a no-op fallback when `REDIS_URL` is unset — so local test runs that don't need caching keep working). Each container that owns a cacheable use case receives the cache via its existing constructor:

```python
_listing_container = ListingContainer(
    listing_repo=SqlAlchemyListingRepository(session),
    property_listing_repo=SqlAlchemyPropertyListingRepository(session),
    address_parser=address_parser,
    cache=await get_cache(),  # NEW
)
_property_container = PropertyContainer(
    ...,  # existing args
    cache=await get_cache(),  # NEW
)
```

Inside each container:

```python
class Container:
    def __init__(self, ..., cache: Cache | None = None):
        ...
        raw_list = ListProperties(listing_repo=...)
        self.list_properties = CachedListProperties(wrapped=raw_list, cache=cache) if cache else raw_list
        raw_get = GetProperty(listing_repo=...)
        self.get_property = CachedGetProperty(wrapped=raw_get, cache=cache) if cache else raw_get
```

Route handlers are unchanged — they call `container.list_properties.execute(...)` and get back either the cached path or the direct path.

### docker-compose + config

```yaml
# docker-compose.yml
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      retries: 5
```

New Settings:

```python
# src/shared/config.py
redis_url: str = "redis://localhost:6379/0"
cache_ttl_seconds: int = 86400  # 24h
cache_enabled: bool = True       # flag to disable cache in tests / local dev if desired
```

### Library choice (Q = "redis-py async")

Add to pyproject.toml:

```toml
"redis>=5.0",  # redis-py with native asyncio — import redis.asyncio as redis
```

## Affected files / surfaces

### New files

**Shared cache infrastructure:**
- `src/shared/cache/__init__.py`
- `src/shared/cache/ports.py` — `Cache(Protocol)` + `NoOpCache` fallback
- `src/shared/cache/keys.py` — `hash_filters(filters: dict) -> str` stable hash helper
- `src/shared/cache/adapters/__init__.py`
- `src/shared/cache/adapters/redis_cache.py` — `RedisCache` via `redis.asyncio`
- `src/shared/cache/adapters/inmemory_cache.py` — `InMemoryCache` test double
- `src/shared/cache/handlers/__init__.py`
- `src/shared/cache/handlers/property_cache_invalidation.py` — the event-driven invalidation handler

**Listings context:**
- `src/listings/application/use_cases/cached_list_properties.py` — decorator over `ListProperties`
- `src/listings/application/use_cases/cached_get_property.py` — decorator over `GetProperty`

**Properties context:**
- `src/properties/application/use_cases/cached_list_properties.py` — decorator over admin `ListProperties`
- `src/properties/application/use_cases/cached_get_property.py` — decorator over admin `GetProperty`

**Tests:**
- `tests/unit/shared/cache/test_inmemory_cache.py` — TTL expiry + `delete_pattern` glob semantics
- `tests/unit/shared/cache/test_keys.py` — filters hash stability (order-invariant, deterministic)
- `tests/unit/listings/test_cached_list_properties.py` — hit / miss / invalidation round-trip
- `tests/unit/listings/test_cached_get_property.py`
- `tests/unit/properties/test_cached_list_properties.py`
- `tests/unit/properties/test_cached_get_property.py`
- `tests/unit/shared/cache/test_property_cache_invalidation_handler.py` — event → correct keys deleted

### Updated files

- `src/shared/config.py` — `redis_url`, `cache_ttl_seconds`, `cache_enabled`.
- `src/shared/entrypoints/bootstrap.py` — `get_cache()` factory; pass `cache=` into `get_listing_container()` + `get_property_container()`.
- `src/listings/container.py` — accept `cache: Cache | None`; wrap `ListProperties` + `GetProperty` with their cached variants when a cache is provided.
- `src/properties/container.py` — same for the admin list / get pair.
- `src/listings/entrypoints/events_worker.py` — register `handle_cache_invalidation` on the three PROPERTY_* event types alongside the existing `handle_property_event`. Invalidation handler takes precedence; the projector runs next.
- `docker-compose.yml` — new `redis` service.
- `pyproject.toml` — `redis>=5.0` dependency.
- `README.md` — one section on Redis cache setup; new env var in the env vars table.
- `docs/features/README.md` — brief note on the cache layer + event-driven invalidation.

## Acceptance criteria

- [ ] `Cache` Protocol exists at `src/shared/cache/ports.py`; `RedisCache` + `InMemoryCache` + `NoOpCache` adapters all pass the same `tests/unit/shared/cache/` test fixtures (shared contract tests).
- [ ] `GET /api/v1/listings/properties?typology=apartment` twice in a row — second request shows a cache hit in logs and never touches the DB (verified by a repo-mock that raises on call).
- [ ] Creating a property via `POST /api/v1/admin/properties/` within the cache's TTL window **invalidates** both `listings:list:*` and `admin:properties:list:{org}:*` — a subsequent `GET` misses cache and re-populates (verified by reading `listings:list:*` keys from Redis before/after).
- [ ] Updating a property (PATCH owner / POST price / DELETE image) invalidates `admin:properties:{org}:{id}` and `listings:property:{id}` — subsequent single-property GETs re-read from DB.
- [ ] Deleting a property invalidates all relevant keys and serves 404s (not stale hits) on the next GET.
- [ ] `cache_enabled=False` → every cacheable endpoint bypasses the cache entirely (the container wires the raw use case, not the decorator). No Redis calls.
- [ ] `REDIS_URL` unset → bootstrap falls through to `NoOpCache`; endpoints keep working.
- [ ] `delete_pattern` uses `SCAN` (never `KEYS`). Verified by unit test that seeds 1000 keys and asserts only cursor-based iteration is used (intercept `Redis.execute_command`).
- [ ] `filters_hash` is **order-invariant**: `hash_filters({"a": 1, "b": 2}) == hash_filters({"b": 2, "a": 1})`. Unit test.
- [ ] 24h TTL is applied on every `set`. Unit test inspects the TTL arg.
- [ ] All existing tests still pass. `uv run pytest` → green. Ruff clean.
- [ ] Docker compose brings up Redis alongside Postgres + LocalStack; `redis-cli ping` responds `PONG` within 5s.
- [ ] README + docs/features/README updated.

## Open questions

1. **Serialization format in the cache** — JSON vs. msgpack vs. pickle.
   - **Preferred: JSON.** Human-readable in `redis-cli`, cross-language-safe (in case a future worker reads these keys), minor size penalty vs msgpack at this scale.
2. **What to cache: domain objects or response payloads?**
   - **Preferred: domain objects (as `dict`s produced by `asdict()` or Pydantic `.model_dump()`).** Route handlers run their existing mappers regardless. Response-payload caching would require including images URL generation in the cache entry, and those are presigned with short expiries — tricky. Cache the domain dicts; let the route regenerate signed URLs per request.
3. **Image presigned URLs** — these currently render per-request via `document_storage.get_download_url(s3_key)`. Caching the dict (not the rendered response) means URLs are regenerated per request; response size is unchanged but the DB hit is eliminated. Confirm this is acceptable (it almost certainly is — URL generation is a cheap HMAC).
4. **Background cleanup of the carried-state `property_listings` read model** — out of scope for this spec. If an event is ever lost and a property_listings row goes stale, a periodic reconciler is a future spec.
5. **Cache stampede** — if the cache expires or is invalidated and N concurrent requests arrive, all N miss and hit the DB. Mitigation (a single-flight lock via `SETNX`-based mutex) is a follow-up if we see it in practice. At <1k DAU, the probability is negligible.

## Out of scope follow-ups

- Warming the cache on boot.
- Redis Cluster / Sentinel for HA.
- Cache-stampede prevention via single-flight locks.
- Caching write-side reads (`GetProperty` from create-property flows, etc.).
- Moving to a CDN for public listings (application cache is the 80% solution).
- Cache observability (hit / miss / eviction metrics pushed to Logfire or equivalent).
- Cache key versioning for schema changes (if response shape changes, bump a version prefix to force cold misses — can add `v1:` prefixes now if we want to be defensive).
