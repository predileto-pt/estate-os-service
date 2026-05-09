# Property listing address enrichment — country-aware searcher, no exposed street

**Status:** draft
**Owner:** Peter
**Created:** 2026-05-09

## Problem

Two related defects in the public-facing `property_listings` read-model:

1. **Privacy leak.** The table carries `address` (the raw free-text street address from the property aggregate). The public listings API exposes this to anonymous visitors, leaking the exact location of every listed property. Agents share *the listing*, not *the address*.
2. **`district` (and friends) can be null.** The async LLM enrichment handler accepts a parsed result with `district=null` and persists it. The schema permits null. Public listings render with broken or missing geographic context.

The fix is small and focused: remove the street address from the public read-model, add a structured location hierarchy that's required, and make the existing LLM enrichment refuse to return null.

## Goal

`property_listings` carries a structured location hierarchy keyed off the property's `country`, and **never** the raw street address. Behind a new `AddressSearcher` port the handler dispatches to the right per-country implementation: in v1 only `PortugalAddressSearcher` exists (fills `parish`/`municipality`/`district`, leaves country-specific others null). The searcher consumes the address text **and the extracted postal code** as input signals. If it can't produce its country's required fields, it raises — failure surfaces in Logfire, SQS redrives → DLQ.

The "never null" invariant is enforced at the **searcher level** (per-country), not at the database column level, so non-PT countries (later) don't need PT-only fields populated.

## Non-goals

- **No synchronous enrichment at publish.** Async LLM stays the entry point — same handler signature as today.
- **No reverse-geocoding via Google Geocoding API.** The current LLM-based parser is the chosen tool; sharper prompt is the entire fix on the parser side.
- **No changes to the property write side.** `Property.address` (full street address) stays unchanged on `properties`. The admin dashboard still shows it. Only the public read-model loses it.
- **No backfill of existing un-enriched rows.** Migration uses an empty-string placeholder for currently-null parish/municipality/district to satisfy the new `NOT NULL` constraint; the user re-runs enrichment manually for those rows. (One-shot ops job, out of scope here.)
- **No multi-country business logic in v1.** `country` defaults to `'Portugal'` server-side. The new nullable columns (`city`, `state`, `postal_code`, `region`) exist for forward-compat only — they're written by no one and read by no one until the platform expands.
- **No new column on `properties`.** Postal code is *extracted on the fly* in the event-snapshot builder (regex over `Property.address`); the property aggregate is untouched. The user's directive: "keep the properties untouched."
- **No frontend-coordination guidance in this spec.** The dashboard team is handling FE adjustments separately. Backend just guarantees the new API shape.
- **No `postal_code` in the public response.** PT postal codes are granular enough (one block) that exposing them defeats the privacy fix. Internal column only — written by the projector for forward-compat use cases (search filters, multi-country dispatch); never serialised on `/api/v1/listings/...`.
- **No `NOT NULL` schema constraint on `parish`/`municipality`/`district`.** With country-aware dispatch, future US listings will leave those null and fill `city`/`state` instead. Application invariant ("PT properties have non-null PT fields") lives in `PortugalAddressSearcher`, not in the schema.
- **No US implementation.** `UnitedStatesAddressSearcher` is mentioned for shape only — no class, no prompt, no tests. Dispatcher raises `NotImplementedError` for `country != 'Portugal'`. Lands when the platform expands.
- **No multi-country property write side.** The property aggregate doesn't gain a `country` field in v1; the handler hard-defaults to `'Portugal'` for dispatch. When `Property.country` exists, the dispatcher reads it from the event payload.

## Approach

### Schema changes (one migration)

`property_listings`:

| Change | Detail |
|---|---|
| **Drop** | `address` (the leak) |
| **Add (`NOT NULL` default `'Portugal'`)** | `country` — Postgres applies the default to existing rows in the same `ALTER TABLE`. |
| **Add (nullable, forward-scope)** | `city`, `state`, `postal_code`, `region` |
| **Stay nullable** | `parish`, `municipality`, `district` — see "Goal" rationale on country-aware dispatch. |

Migration order:
1. Add the five new columns (`country` with its server default; the rest nullable).
2. `DROP COLUMN address`.

No backfill, no `NOT NULL` flips. Existing rows with null parish/municipality/district stay as-is — agents re-enrich them via republish (out-of-scope follow-up). New PT writes are guaranteed non-null *by the searcher*, not the schema.

### Postal-code extraction at event-build time

`build_property_snapshot` (`src/properties/application/events/property_event.py`) regex-extracts the postal code from `Property.address` and adds it to the event payload:

```python
import re

_POSTAL_CODE_RE = re.compile(r"\b(\d{4}-\d{3})\b")  # Portuguese: XXXX-XXX

def build_property_snapshot(prop: Property) -> dict:
    match = _POSTAL_CODE_RE.search(prop.address)
    return {
        ...,
        "address": prop.address,
        "postal_code": match.group(1) if match else None,
        ...
    }
```

`postal_code` rides on every `PROPERTY_CREATED.v1` / `PROPERTY_UPDATED.v1` / `PROPERTY_PUBLISHED.v1`, and on the `PROPERTY_LISTING_NEEDS_ADDRESS_ENRICHMENT.v1` event the projector emits to the listings worker. No change to `Property` itself; nothing to migrate on the `properties` table.

When the regex doesn't match (`address` has no postal code), `postal_code` is `null` in the event payload — the LLM still receives the free-text address and is expected to handle it via the city-name path.

### `AddressSearcher` port + country-aware dispatch

The existing `AddressParser` port is renamed and reshaped to `AddressSearcher`. The new shape is country-explicit:

```python
# src/listings/application/ports/address_searcher.py

class ParsedAddress(BaseModel):
    """Universal location envelope. Each per-country implementation
    fills the fields its country uses; the rest are None.

    For Portugal: parish, municipality, district required; everything
    else None.
    For United States: city, state required; parish/municipality/district None.
    `country` is always present; `postal_code` is when extractable.
    """
    country: str
    parish: str | None = None
    municipality: str | None = None
    district: str | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None
    region: str | None = None


class AddressSearcher(Protocol):
    async def search(
        self,
        *,
        address: str,
        postal_code: str | None,
        country: str,
    ) -> ParsedAddress: ...
```

`PortugalAddressSearcher` (concrete, replaces `LangChainAddressParser`) implements `search(...)` with the LangChain + GPT pipeline. Its result invariant: **`parish`, `municipality`, `district` are non-null** and `country == "Portugal"`; if the LLM returns null on any required field, Pydantic ValidationError raises (still caught one frame up by the handler).

```python
# src/listings/adapters/ai/portugal_address_searcher.py
class PortugalAddressSearcher(AddressSearcher):
    async def search(self, *, address, postal_code, country) -> ParsedAddress:
        # country=='Portugal' guaranteed by dispatcher; assert defensively.
        assert country == "Portugal"
        # ... LangChain call (same shape as today; new prompt below)
        # Internal model uses non-optional parish/municipality/district to
        # force the LLM to fill them; raises on null.
```

`UnitedStatesAddressSearcher` is **not implemented in v1** — placeholder for future work. Stub returning `NotImplementedError` is acceptable; preferred is the file simply not existing yet, with the dispatcher's switch covering only PT.

#### Dispatcher

A small factory in the listings container:

```python
# src/listings/application/use_cases/select_address_searcher.py (or similar)

def select_address_searcher(
    country: str,
    *,
    portugal: AddressSearcher,
) -> AddressSearcher:
    if country == "Portugal":
        return portugal
    raise NotImplementedError(
        f"AddressSearcher not implemented for country={country}"
    )
```

The listings container holds `portugal_address_searcher` (concrete) at construction time; the dispatcher closes over it.

The handler reads `country` from the event payload (defaulting `"Portugal"` for backward-compat with events emitted before this spec) and calls the dispatcher:

```python
country = event.data.get("country") or "Portugal"
searcher = select_address_searcher(country, portugal=listings.portugal_searcher)
parsed = await searcher.search(
    address=event.data["address"],
    postal_code=event.data.get("postal_code"),
    country=country,
)
```

When `Property.country` lands later, `build_property_snapshot` adds it to the event payload — that's a one-line forward change with no v1 work.

#### Internal validation in `PortugalAddressSearcher`

LangChain's `with_structured_output` is given an internal model with non-optional PT fields:

```python
class _PortugalLLMResult(BaseModel):
    parish: str
    municipality: str
    district: str
```

The searcher converts that to the universal `ParsedAddress` (filling country-specific others as None). Pydantic on `_PortugalLLMResult` rejects null responses → `ValidationError` propagates up → `address_enrichment_handler.py:36-45` already handles it (increment `location_enrichment_attempts`, log via structlog → Logfire, raise → SQS redrives → DLQ).

The prompt (`langchain_address_parser.py`) is rewritten to surface the postal code as an explicit signal and make district inference explicit:

```
You parse Portuguese real-estate addresses into structured components:
parish (freguesia), municipality (concelho), district (distrito).

INPUT FORMAT
You receive two pieces of information from the user message:
  ADDRESS:     <free-text street address as the agent typed it>
  POSTAL CODE: <NNNN-NNN format, or "unknown" if it could not be
                extracted from the address>

The postal code (when known) is the most authoritative signal for
parish/municipality/district — use it to anchor your answer and use
the address text only to disambiguate.

OUTPUT
ALL THREE fields MUST be populated. NEVER return null.

Cities that are simultaneously municipality AND district names
(assign both fields the same value when the address or postal code
resolves to any of them):
  Lisboa, Porto, Coimbra, Aveiro, Braga, Évora, Faro, Beja,
  Castelo Branco, Guarda, Leiria, Portalegre, Santarém, Setúbal,
  Viana do Castelo, Vila Real, Viseu, Bragança.

Postal-code prefix → district (first digit):
  1xxx → Lisboa, 2xxx → Setúbal/Santarém/Lisboa region, 3xxx → Coimbra,
  4xxx → Porto, 5xxx → Vila Real/Bragança, 6xxx → Castelo Branco,
  7xxx → Évora/Beja, 8xxx → Faro, 9xxx → Madeira/Açores.

Examples:
- ADDRESS: "Arca, Ponte de Lima, Viana do Castelo" / POSTAL CODE: unknown
  → parish="Arca", municipality="Ponte de Lima",
    district="Viana do Castelo"
- ADDRESS: "Rua Augusta 1, Lisboa" / POSTAL CODE: 1100-001
  → parish="Santa Maria Maior", municipality="Lisboa",
    district="Lisboa"
- ADDRESS: "Rua A" / POSTAL CODE: 4000-001
  → parish="(best guess from postal-code area)", municipality="Porto",
    district="Porto"

If the address is genuinely unparseable AND the postal code is
"unknown" (no city, no postal code, no recognizable Portuguese place),
refuse — do not invent values that aren't supported by either signal.
```

`PortugalAddressSearcher.search` formats the user message as:
```
ADDRESS: {address}
POSTAL CODE: {postal_code or "unknown"}
```

Failure semantics stay the same as today (raise → DLQ → ops triages via Logfire). The behavior change is *what counts as failure*: the LLM returning null is now treated as failure, where before it was silently persisted.

### Repository + projector

`SqlAlchemyPropertyListingRepository` (`property_listing_repository.py`):
- `_to_domain` and `_to_row` mappings drop `address`, add `country` / `city` / `state` / `postal_code` / `region`.
- The async `update_location` method now writes ALL location fields (PT + US shape) from the searcher's `ParsedAddress` result. Each is nullable per the universal envelope; the projector preserves whatever the country-specific searcher filled.
- `upsert_from_event` defaults `country='Portugal'` for backward-compat with events that don't carry it.

The projector (`property_event_handler.py`) **forwards `postal_code` and `country`** from the upstream event into the `PROPERTY_LISTING_NEEDS_ADDRESS_ENRICHMENT.v1` event it emits:

```python
await _publish_listing_event(
    publisher,
    event_type=PROPERTY_LISTING_NEEDS_ADDRESS_ENRICHMENT_V1,
    data={
        "property_id": data["id"],
        "address": data["address"],
        "postal_code": data.get("postal_code"),  # NEW
        "country": data.get("country") or "Portugal",  # NEW (default for legacy events)
    },
    property_id=data["id"],
)
```

The projector does **not** populate `property_listings.postal_code` (or `city`/`state`/`region`) in v1 — those remain null until either (a) a US-shaped searcher writes city/state, or (b) a future v2 of this work uses postal_code internally for filter optimization. The column exists for forward-compat only.

`build_property_snapshot` is the one place upstream that gains the regex extraction (per §Postal-code extraction).

### `PropertyListingModel`

```python
# REMOVE
address: Mapped[str] = mapped_column(Text, nullable=False)

# UNCHANGED (stay nullable; per-country invariant enforced by searcher)
parish: Mapped[str | None] = mapped_column(Text, index=True)
municipality: Mapped[str | None] = mapped_column(Text, index=True)
district: Mapped[str | None] = mapped_column(Text, index=True)

# ADD
country: Mapped[str] = mapped_column(
    Text, nullable=False, server_default=text("'Portugal'"), index=True
)
city: Mapped[str | None] = mapped_column(Text)
state: Mapped[str | None] = mapped_column(Text)
postal_code: Mapped[str | None] = mapped_column(Text)
region: Mapped[str | None] = mapped_column(Text)
```

### Public API response (breaking change)

The public listings response no longer carries `address` or `postal_code`. Every place the API serialises a `property_listings` row needs updating:

- **`PublicPropertyResponse`** in `src/listings/adapters/api/schemas.py` — drop `address`. Add `country` (required), and `parish`, `municipality`, `district`, `city`, `state`, `region` (all optional, populated per the property's country). **`postal_code` is NOT exposed** — internal-only column used by the searcher / projector.
- **List response wrapper** (whatever `GET /api/v1/listings/properties` returns — pagination envelope or raw list) — propagates the same shape per item.
- **Single-item response** for `GET /api/v1/listings/properties/{id}` — same.
- **Route handlers / response builders** — drop `"address": row.address` from the dict assembly; add the structured fields *except* `postal_code`.
- **OpenAPI schema regenerates** automatically from Pydantic — no manual update.

Anywhere a route handler currently does `response["address"] = listing.address`, it has to either disappear or be replaced with the structured fields (`postal_code` excluded). Implementation walks the listings routes and removes every `address` and `postal_code` reference from the public response surface. Tests that today assert on `"address" in response` flip to asserting it's NOT in the response, and additionally assert `"postal_code" not in response`.

Frontend (out of scope): user is handling on a separate terminal.

### Admin response is unchanged

`/api/v1/admin/properties/...` reads from `properties` (write-side aggregate), not from `property_listings`. Agents continue to see `Property.address`. No change there.

### Cross-cutting: in-memory test doubles

- `InMemoryPropertyListingRepository` mirrors the schema change (drop `address`, add the new fields).
- `InMemoryAddressSearcher` (replaces `InMemoryAddressParser` at `src/listings/adapters/inmemory/inmemory_address_searcher.py`) — implements `search(...)` for `country=="Portugal"`. **Raises** when the test address doesn't yield non-null parish/municipality/district. For other countries, raises `NotImplementedError`. Tests that need parses to succeed must seed canonical addresses (`"Parish, Municipality, District"`) or stub the searcher.

## Affected files / surfaces

### New files
- `alembic/versions/<new>_property_listings_required_location.py`

### Updated files

**Schema / domain (listings):**
- `src/listings/adapters/database/property_listing_model.py` — column changes per §`PropertyListingModel`.
- `src/listings/application/ports/address_parser.py` — `ParsedAddress.parish/municipality/district` non-optional; `parse(...)` gains `postal_code` kwarg.

**Repository (listings):**
- `src/listings/adapters/database/property_listing_repository.py` — drop `address` references; read/write the new columns; default `country='Portugal'`.
- `src/listings/adapters/inmemory/inmemory_property_listing_repo.py` — same.

**LLM parser (listings):**
- `src/listings/adapters/ai/langchain_address_parser.py` — new prompt; accepts `postal_code` kwarg; structured output enforces non-null fields.
- `src/listings/adapters/inmemory/inmemory_address_parser.py` — raises when fields can't be synthesized; accepts `postal_code` kwarg (ignored in the no-LLM fake).

**Worker handlers (listings):**
- `src/listings/adapters/workers/property_event_handler.py` — forward `postal_code` into the `PROPERTY_LISTING_NEEDS_ADDRESS_ENRICHMENT.v1` payload.
- `src/listings/adapters/workers/address_enrichment_handler.py` — read `postal_code` from `event.data`; pass it to `address_parser.parse(...)`.

**API (listings — public-facing, breaking shape change):**
- `src/listings/adapters/api/schemas.py` — drop `address` from the public listing response models; add the structured location fields.
- `src/listings/adapters/api/routes/listings.py` — response-builder dicts drop `address`, add the new fields. Audit every route in this file to ensure no `address` leak remains.

**Event snapshot (properties — postal_code extraction only, no domain change):**
- `src/properties/application/events/property_event.py` — `build_property_snapshot` regex-extracts `postal_code` from `prop.address` and adds to the event payload.

**Tests:**
- `tests/database/test_migration.py` — bump revision; assert `address` column gone, `country` exists with default `'Portugal'`, parish/municipality/district are `NOT NULL`, the four new nullable columns exist.
- `tests/integration/test_listings.py` — the public listing response asserts `"address" not in body`; asserts the new structured fields are present.
- `tests/unit/listings/test_address_enrichment_handler.py` — `postal_code` from the event is passed through to the parser.
- `tests/unit/listings/test_langchain_address_parser.py` (new or extended) — prompt renders both `ADDRESS:` and `POSTAL CODE:` lines; LLM null responses raise ValidationError; postal-code-only inputs yield correct district.
- `tests/unit/properties/test_property_event.py` (or wherever `build_property_snapshot` is tested) — postal_code extraction: regex matches; missing → `null` in payload; non-PT format ignored.

## Acceptance criteria

- [ ] Migration `upgrade()` adds `country` (NOT NULL default `'Portugal'`), `city`, `state`, `postal_code`, `region` (all nullable). Backfills null parish/municipality/district to `''`. Adds `NOT NULL` on those three. Drops `address`. `downgrade()` reverses cleanly.
- [ ] `tests/database/test_migration.py` is bumped to the new revision and asserts:
  - `address` column does not exist on `property_listings`.
  - `country` exists with `column_default LIKE '%Portugal%'` and `is_nullable='NO'`.
  - `parish`, `municipality`, `district` are `is_nullable='NO'`.
  - `city`, `state`, `postal_code`, `region` exist and are nullable.
- [ ] `ParsedAddress` has non-optional `parish`, `municipality`, `district`. Pydantic raises ValidationError when the LLM returns null on any of them.
- [ ] `LangChainAddressParser` uses the new prompt; a test parametrized over typical PT addresses (`"Rua A, 1100-001"`, `"Av. da Liberdade 12, Lisboa"`, `"Arca, Ponte de Lima"`) asserts non-null outputs across all three fields. (LLM responses are mocked.)
- [ ] `address_enrichment_handler` re-raises on parse failure (existing behavior); structlog → Logfire emits the failure event with the offending address; SQS redrives until `maxReceiveCount=5` then DLQs.
- [ ] `SqlAlchemyPropertyListingRepository` and the in-memory variant: no `address` references; default `country='Portugal'` when not supplied.
- [ ] Public listings response no longer carries `address`. Carries `parish`, `municipality`, `district`, `country` (required) and `city`, `state`, `postal_code`, `region` (optional).
- [ ] Admin properties response is unchanged — `Property.address` still serialised on `/api/v1/admin/properties/...`.
- [ ] `build_property_snapshot` returns a dict with `postal_code` matching the PT format `XXXX-XXX` when extractable, `None` otherwise. Property events (`PROPERTY_CREATED.v1`, `PROPERTY_UPDATED.v1`, `PROPERTY_PUBLISHED.v1`) all carry it.
- [ ] `property_event_handler` forwards `postal_code` into the `PROPERTY_LISTING_NEEDS_ADDRESS_ENRICHMENT.v1` payload.
- [ ] `address_enrichment_handler` passes `postal_code` to `address_parser.parse(...)`.
- [ ] `LangChainAddressParser` user-message format includes both `ADDRESS:` and `POSTAL CODE:` lines (the latter set to `"unknown"` when null).
- [ ] All existing tests still pass. `uv run ruff check .` clean.

## Open questions

(None — both v1 questions resolved. In-memory parser raises on synthesis failure; frontend handled separately by the user.)

## Out of scope follow-ups

- Backfill of empty-string parish/municipality/district rows by re-emitting events / re-running enrichment.
- Multi-country business logic (uses of the new nullable columns).
- Removal of the `country` server default once a multi-country property exists.
- Listing search filters on `country` / `city` / `state`.
- LLM model bump (configurable via the existing `address_parser_model` env var — operational change, no code).

## Commits

```
fix(listings): drop address from public listings; require structured location

- property_listings drops `address`; adds country (NOT NULL default
  'Portugal'), city/state/postal_code/region (nullable, future-scope).
- parish/municipality/district transitioned to NOT NULL with an
  empty-string placeholder backfill for existing null rows.
- ParsedAddress.parish/municipality/district are non-optional;
  LangChain `with_structured_output` rejects null responses; existing
  handler re-raises so SQS redrives → DLQ → Logfire surfaces.
- LLM prompt rewritten: `ADDRESS:` + `POSTAL CODE:` two-line input;
  postal-code prefix table; city-is-also-district enumeration.
- `build_property_snapshot` regex-extracts the postal code from
  `Property.address` (no schema change to `properties`); event payload
  carries it; projector forwards it; enrichment handler passes it
  through to the LLM.
- Public listings response no longer carries the street address;
  carries the structured hierarchy. Admin response unchanged.

Privacy: stops leaking exact street addresses to anonymous visitors of
the public listings page.
```
