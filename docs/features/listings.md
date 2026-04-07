# Listings

The `listings` bounded context exposes public, read-only property listings. It reads the same database tables as `properties` but defines its own ORM models to keep the boundary explicit. There is no authentication on these endpoints — they back the public property search portal.

**Source:** `src/listings/`

## Domain entities

| Entity | Description |
|--------|-------------|
| `ListedProperty` | Read-only view of a property. Includes characteristics, prices, images. **No owners** — owner data is private to `properties`. |
| `PropertyCharacteristics` | Frozen value object: area, bedrooms, bathrooms, year built, energy rating, etc. |
| `PropertyPrice` | Frozen value object: amount + listing type. |
| `PropertyImage` | Frozen value object: S3 key, filename, ordering. |

Enums (defined locally — duplicated by design from `properties`):
- `ListingType` — `SALE` / `PURCHASE`
- `Typology` — `HOUSE` / `APARTMENT` / `LAND` / `RUIN`
- `PropertyStatus` — `DRAFT` / `ACTIVE` / `SOLD` / `RENTED` / `WITHDRAWN`

## Feature catalog

| Feature | Trigger | Purpose |
|---------|---------|---------|
| [GetProperty](#getproperty) | `GET /api/v1/listings/properties/{property_id}` | Return one active property by ID |
| [ListProperties](#listproperties) | `GET /api/v1/listings/properties` | Filter and paginate active properties |

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
