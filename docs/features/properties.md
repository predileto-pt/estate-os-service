# Properties

The `properties` bounded context is the largest in the service. It manages property records and their related entities (owners, prices, images, amenities), runs an AI extraction pipeline that turns uploaded documents into structured property data, and discovers nearby amenities via Google Places.

**Source:** `src/properties/`

## Domain entities

| Entity | Description |
|--------|-------------|
| `Property` | Aggregate root. Holds address, listing type, typology, status, characteristics, geolocation, and child collections (owners, prices, images). |
| `PropertyOwner` | Person with full identity (name, NIF, civil status, ID document, date of birth) and contact info (email, phone, verification flags). |
| `PropertyPrice` | Historical price entry by listing type. Multiple per property. |
| `PropertyImage` | S3-backed image with display order. |
| `PropertyAmenity` | Nearby place (one of 9 categories) discovered via Google Places. |
| `PropertyCharacteristics` | Frozen value object: bedrooms, bathrooms, area, year built, energy rating, etc. |
| `ExtractionJob` | Async job for parsing uploaded documents. Status: `PENDING` / `PROCESSING` / `COMPLETED` / `FAILED` / `RETRYING`. |
| `DocumentContent` | OCR cache: parsed text + classification per document, keyed by extraction job. |

Domain service: `domain/services/amenity_ranker.py` — brand-weighted ranking for amenities (boosts known PT brands like Continente, Pingo Doce, Lidl, Millennium, BCP).

## Events the context produces

Every event uses the shared `DomainEvent` envelope from `shared.events.base` with a versioned `event_type` string.

| Event type string | Transport | Consumed by |
|---|---|---|
| `PROPERTY_EXTRACTION_REQUESTED.v1` | Command (SQS → `property-extraction-queue`) | `properties.extraction_processor.handle_property_extraction_requested` |
| `BATCH_PROPERTY_EXTRACTION_REQUESTED.v1` | Command (same queue, event-type-keyed) | `properties.extraction_processor.handle_batch_property_extraction_requested` |
| `PROPERTY_CREATED.v1` | Domain event (SNS fan-out) | `properties.discovery_processor.handle_property_created` (via properties-events-queue) |

Constants live in `src/shared/events/types.py`. See [ADR-008](../adr/008-event-bus-ports-and-fanout.md) for transport semantics.

## Feature catalog

### Property CRUD

| Feature | Trigger | Purpose |
|---------|---------|---------|
| [CreateProperty](#createproperty) | `POST /api/v1/admin/properties` | Create a property in `DRAFT` status |
| [GetProperty](#getproperty) | `GET /api/v1/admin/properties/{property_id}` | Return property with owners, prices, images |
| [ListProperties](#listproperties) | `GET /api/v1/admin/properties` | List properties for an organization |
| [ListActiveProperties](#listactiveproperties) | `GET /api/v1/admin/properties/active` | List active properties (admin variant — public version is in `listings`) |
| [UpdatePropertyAddress](#updatepropertyaddress) | `PATCH /api/v1/admin/properties/{property_id}/address` | Replace the property's address (strips, rejects empty, no-op on unchanged value) |
| [PublishProperty](#publishproperty) | `POST /api/v1/admin/properties/{property_id}/publish` | Flip `DRAFT`/`WITHDRAWN` → `ACTIVE`; emit `PROPERTY_PUBLISHED.v1` |
| [DeleteProperty](#deleteproperty) | `DELETE /api/v1/admin/properties/{property_id}` | Hard-delete a property and cascade owners, prices, images |

### Property owners

| Feature | Trigger | Purpose |
|---------|---------|---------|
| [CreatePropertyOwner](#createpropertyowner) | `POST /api/v1/admin/property-owners` | Add an owner with full identity |
| [GetPropertyOwner](#getpropertyowner) | `GET /api/v1/admin/property-owners/{owner_id}` | Return one owner |
| [ListPropertyOwners](#listpropertyowners) | `GET /api/v1/admin/property-owners` | List a property's owners |
| [UpdatePropertyOwnerContact](#updatepropertyownercontact) | `PATCH /api/v1/admin/property-owners/{owner_id}/contact` | Update email/phone (resets verification flags) |
| [ExtractPropertyOwnerFromDocument](#extractpropertyownerfromdocument) | `POST /api/v1/admin/property-owners/extract-from-document` | Parse an ID document and create the owner |

### Images

| Feature | Trigger | Purpose |
|---------|---------|---------|
| [GenerateImageUploadUrls](#generateimageuploadurls) | `POST /api/v1/admin/property-images/presign` | Get pre-signed S3 URLs for image upload |
| [RecordPropertyImage](#recordpropertyimage) | `POST /api/v1/admin/property-images` | Save image metadata after client uploads to S3 |
| [DeletePropertyImage](#deletepropertyimage) | `DELETE /api/v1/admin/property-images/{image_id}` | Delete an image |
| [ReorderPropertyImages](#reorderpropertyimages) | `PUT /api/v1/admin/property-images/reorder` | Reorder all images for a property |

### Pricing

| Feature | Trigger | Purpose |
|---------|---------|---------|
| [CreatePropertyPrice](#createpropertyprice) | `POST /api/v1/admin/property-prices` | Record a price entry |
| [ListPropertyPrices](#listpropertyprices) | `GET /api/v1/admin/property-prices` | List a property's price history |

### Document extraction (single & batch)

| Feature | Trigger | Purpose |
|---------|---------|---------|
| [GenerateUploadUrls](#generateuploadurls) | `POST /api/v1/admin/extraction-jobs/presign` | Get pre-signed URLs for extraction documents |
| [SubmitPropertyExtraction](#submitpropertyextraction) | `POST /api/v1/admin/extraction-jobs` | Submit a single property document for extraction |
| [SubmitBatchPropertyExtraction](#submitbatchpropertyextraction) | `POST /api/v1/admin/extraction-jobs/batch` | Submit a batch (property + ID documents) |
| [GetExtractionJob](#getextractionjob) | `GET /api/v1/admin/extraction-jobs/{job_id}` | Return job status |
| [ListExtractionJobs](#listextractionjobs) | `GET /api/v1/admin/extraction-jobs` | List jobs for an organization |
| [RetryExtractionJob](#retryextractionjob) | `POST /api/v1/admin/extraction-jobs/{job_id}/retry` | Retry a failed job |
| [ProcessPropertyExtraction](#processpropertyextraction) | event: `PROPERTY_EXTRACTION_REQUESTED.v1` | Worker: OCR + extract → create Property |
| [ProcessBatchPropertyExtraction](#processbatchpropertyextraction) | event: `BATCH_PROPERTY_EXTRACTION_REQUESTED.v1` | Worker: OCR + classify + extract Property + Owners |

### Amenity discovery

| Feature | Trigger | Purpose |
|---------|---------|---------|
| [DiscoverPropertyAmenities](#discoverpropertyamenities) | `POST /api/v1/admin/property-amenities/discover` | Trigger Google Places discovery (async) |
| [GetPropertyAmenities](#getpropertyamenities) | `GET /api/v1/admin/property-amenities` | Return discovered amenities for a property |

### Property POIs

Manual entry surface for points of interest near a property. The POI table lives separately from `property_amenities` — it stores one row per POI (vs one row per category-summary) and includes a free-form `metadata` jsonb for provider extras and agent notes. The auto-discovery workflow that populates this catalog is described in **ADR-010** (`docs/adr/010-property-listing-enrichment-and-cost-scoring.md`); this entry covers only the agent-facing CRUD surface.

| Feature | Trigger | Purpose |
|---------|---------|---------|
| [ListPropertyPois](#listpropertypois) | `GET /api/v1/admin/properties/{id}/pois` | List a property's POIs |
| [ReplacePropertyPois](#replacepropertypois) | `POST /api/v1/admin/properties/{id}/pois` | Replace the entire catalog (empty list clears) |
| [UpdatePropertyPoi](#updatepropertypoi) | `PATCH /api/v1/admin/properties/{id}/pois/{poi_id}` | Edit one POI in place |
| [DeletePropertyPoi](#deletepropertypoi) | `DELETE /api/v1/admin/properties/{id}/pois/{poi_id}` | Remove one POI |

---

## Feature details

### CreateProperty

Create a property in `DRAFT` status. Optionally publishes `PROPERTY_CREATED.v1` if an `EventPublisher` is wired in the container.

- **Inputs:** `organization_id`, `address`, `listing_type`, `typology`, `description?`
- **Output:** `Property`
- **Events:** `PROPERTY_CREATED.v1` (optional, broadcast via SNS)
- **Source:** `src/properties/application/use_cases/create_property.py`

### GetProperty

Return a property by ID with all child collections loaded.

- **Inputs:** `property_id`
- **Output:** `Property`
- **Raises:** `PropertyNotFoundError`
- **Source:** `src/properties/application/use_cases/get_property.py`

### ListProperties

List all properties for an organization.

- **Inputs:** `organization_id`
- **Output:** `list[Property]`
- **Source:** `src/properties/application/use_cases/list_properties.py`

### ListActiveProperties

List properties with status `ACTIVE`. Used by admin tooling. The public listings version lives in the `listings` context.

- **Output:** `list[Property]`
- **Source:** `src/properties/application/use_cases/list_active_properties.py`

### UpdatePropertyAddress

Replace a property's `address`. The schema validator strips surrounding whitespace and rejects empty / whitespace-only inputs (422). The use case short-circuits on no-op — if the stripped new value matches the current address, it returns the existing aggregate without bumping `aggregate_version` or emitting an event. This avoids redundant projector traffic on idempotent retries. The domain method enforces the same non-empty invariant for non-HTTP callers.

- **Inputs:** `property_id`, `organization_id`, `address`
- **Output:** refreshed `Property`
- **Raises:** `PropertyNotFoundError` (cross-org / unknown id)
- **Events:** `PROPERTY_UPDATED.v1` (only when the value actually changes)
- **Source:** `src/properties/application/use_cases/update_property_address.py`

### PublishProperty

Flip a property from `DRAFT` or `WITHDRAWN` to `ACTIVE` and broadcast a distinct business event so downstream consumers (notifications, analytics, search indexers) can subscribe to the "went live" moment specifically — not every owner-detail tweak. The domain method enforces a publishability checklist (non-empty address, at least one price, owner, and image, and a publishable starting status); failures bubble as `PropertyNotPublishableError` with machine-readable reason codes.

The route gates on OWNER/ADMIN role; the use case itself is permission-agnostic.

- **Inputs:** `property_id`, `organization_id`
- **Output:** refreshed `Property` (status now `ACTIVE`, version bumped)
- **Raises:** `PropertyNotFoundError`, `PropertyNotPublishableError`
- **Events:** `PROPERTY_PUBLISHED.v1` (carried-state snapshot from `build_property_snapshot`)
- **Source:** `src/properties/application/use_cases/publish_property.py`

### DeleteProperty

Hard-delete a property and cascade owners, prices, images (including S3 objects), amenities, and extraction jobs. Restricted to OWNER/ADMIN at the route layer.

- **Inputs:** `property_id`, `organization_id`
- **Output:** none (204)
- **Raises:** `PropertyNotFoundError`
- **Events:** `PROPERTY_DELETED.v1` (minimal `{id, organization_id, aggregate_version}` payload)
- **Source:** `src/properties/application/use_cases/delete_property.py`

### CreatePropertyOwner

Add a property owner with full identity. NIF is validated as a 9-digit Portuguese tax ID in the domain model's `__post_init__`.

- **Inputs:** `property_id`, `full_name`, `civil_status`, `address`, `nif`, `document_type`, `document_id`, `issued_by`, `issuing_district?`, `date_of_birth`
- **Output:** `Property` (with new owner appended)
- **Source:** `src/properties/application/use_cases/create_property_owner.py`

### GetPropertyOwner

Return a single owner.

- **Inputs:** `property_id`, `owner_id`
- **Output:** `PropertyOwner`
- **Source:** `src/properties/application/use_cases/get_property_owner.py`

### ListPropertyOwners

List all owners of a property.

- **Inputs:** `property_id`
- **Output:** `list[PropertyOwner]`
- **Source:** `src/properties/application/use_cases/list_property_owners.py`

### UpdatePropertyOwnerContact

Update an owner's email or phone. Sets `email_verified` / `phone_verified` to false on change.

- **Inputs:** `property_id`, `owner_id`, `email?`, `phone_number?`
- **Output:** `Property`
- **Source:** `src/properties/application/use_cases/update_property_owner_contact.py`

### ExtractPropertyOwnerFromDocument

Parse an uploaded ID document (Cartão de Cidadão, passport, etc.) via Reducto OCR + OpenAI extraction and create the owner record. Synchronous — blocks the request.

- **Inputs:** `property_id`, `file_bytes`, `content_type`, `document_subtype` (default `cartao_cidadao`)
- **Output:** `Property`
- **Pipeline:** `DocumentParser` (Reducto) → `DocumentDataExtractor` (OpenAI)
- **Source:** `src/properties/application/use_cases/extract_property_owner_from_document.py`

### GenerateImageUploadUrls

Generate pre-signed S3 URLs for one or more images. The client uploads directly to S3, then calls `RecordPropertyImage` for each.

- **Inputs:** `property_id`, `files` (list of `{filename, content_type}`)
- **Output:** `list[PresignedImageFile]` with `image_id`, `s3_key`, `upload_url`
- **Limit:** 20 images per property
- **Source:** `src/properties/application/use_cases/generate_image_upload_urls.py`

### RecordPropertyImage

Save image metadata after the client confirms the S3 upload. Verifies the file exists in S3 before persisting.

- **Inputs:** `property_id`, `image_id`, `s3_key`, `filename`, `content_type`, `size_bytes`
- **Output:** `Property`
- **Side effects:** verifies S3 object exists, writes `property_images` row, auto-increments `display_order`
- **Source:** `src/properties/application/use_cases/record_property_image.py`

### DeletePropertyImage

Remove an image from a property.

- **Inputs:** `property_id`, `image_id`
- **Output:** `Property`
- **Source:** `src/properties/application/use_cases/delete_property_image.py`

### ReorderPropertyImages

Reorder all images for a property by passing the full ordered list of image IDs.

- **Inputs:** `property_id`, `image_ids` (must contain every existing image)
- **Output:** `Property`
- **Source:** `src/properties/application/use_cases/reorder_property_images.py`

### CreatePropertyPrice

Record a price entry. A property can have multiple prices over time.

- **Inputs:** `property_id`, `amount`, `listing_type`
- **Output:** `Property`
- **Source:** `src/properties/application/use_cases/create_property_price.py`

### ListPropertyPrices

Return the price history for a property.

- **Inputs:** `property_id`
- **Output:** `list[PropertyPrice]`
- **Source:** `src/properties/application/use_cases/list_property_prices.py`

### GenerateUploadUrls

Generate pre-signed S3 URLs for extraction documents. Returns a fresh `job_id` (UUID) — the client uses it on the next call.

- **Inputs:** `files` (list of `{filename, content_type}`)
- **Output:** `(job_id, list[PresignedFile])`
- **Limit:** 5 documents per job
- **Source:** `src/properties/application/use_cases/generate_upload_urls.py`

### SubmitPropertyExtraction

Submit a single property document. Verifies the S3 keys exist, creates an `ExtractionJob` in `PENDING`, publishes `PROPERTY_EXTRACTION_REQUESTED.v1` to the extraction command queue.

- **Inputs:** `job_id`, `user_id`, `organization_id`, `document_keys`, `listing_type`, `typology`
- **Output:** `ExtractionJob`
- **Events:** `PROPERTY_EXTRACTION_REQUESTED.v1`
- **Source:** `src/properties/application/use_cases/submit_property_extraction.py`

### SubmitBatchPropertyExtraction

Same as above but for mixed batches (property docs + multiple ID documents). Routes to a different worker that runs document classification.

- **Inputs:** `job_id`, `user_id`, `organization_id`, `document_keys`, `listing_type`, `typology`
- **Output:** `ExtractionJob`
- **Events:** `BATCH_PROPERTY_EXTRACTION_REQUESTED.v1`
- **Source:** `src/properties/application/use_cases/submit_batch_property_extraction.py`

### GetExtractionJob

Return job status, errors, and the resulting `property_id` if completed.

- **Inputs:** `job_id`
- **Output:** `ExtractionJob`
- **Source:** `src/properties/application/use_cases/get_extraction_job.py`

### ListExtractionJobs

List jobs for an organization.

- **Inputs:** `organization_id`
- **Output:** `list[ExtractionJob]`
- **Source:** `src/properties/application/use_cases/list_extraction_jobs.py`

### RetryExtractionJob

Resubmit a failed job. Validates that the current status is `FAILED`. Routes to single or batch worker based on document count.

- **Inputs:** `job_id`
- **Output:** `ExtractionJob` (status `RETRYING`)
- **Events:** `PROPERTY_EXTRACTION_REQUESTED.v1` or `BATCH_PROPERTY_EXTRACTION_REQUESTED.v1`
- **Source:** `src/properties/application/use_cases/retry_extraction_job.py`

### ProcessPropertyExtraction

**Worker.** Triggered by `PROPERTY_EXTRACTION_REQUESTED.v1`. Downloads docs from S3, runs Reducto OCR, calls OpenAI to extract structured property data, attempts geocoding, then writes a `Property` in `DRAFT` status. On success, publishes `PROPERTY_CREATED.v1` so amenity discovery can run.

- **Inputs:** `job_id`
- **Output:** `ExtractionJob` (`COMPLETED` or `FAILED`)
- **Pipeline:** `DocumentStorage.download` → `DocumentParser.parse_batch` (Reducto) → `PropertyExtractorService.extract` (OpenAI) → `extract_geolocation` (best-effort) → `PropertyRepository.save`
- **Events published:** `PROPERTY_CREATED.v1`
- **Source:** `src/properties/application/use_cases/process_property_extraction.py`
- **Worker entry:** `src/properties/adapters/workers/extraction_processor.py:handle_property_extraction_requested`

### ProcessBatchPropertyExtraction

**Worker.** Triggered by `BATCH_PROPERTY_EXTRACTION_REQUESTED.v1`. Adds document classification (property docs vs ID docs), routes ID docs through the owner extractor, deduplicates owners by NIF, creates the property and all owners in one go.

- **Inputs:** `job_id`
- **Output:** `ExtractionJob`
- **Pipeline:** S3 download (or `DocumentContent` cache on retry) → Reducto OCR → `DocumentClassifier` → split into property texts and ID docs → OpenAI property extraction + per-doc owner extraction → geocoding → dedup → save
- **Events published:** `PROPERTY_CREATED.v1`
- **Source:** `src/properties/application/use_cases/process_batch_property_extraction.py`

### DiscoverPropertyAmenities

Trigger amenity discovery for a property. Returns 202 immediately and publishes `PROPERTY_CREATED.v1` so the discovery worker picks it up.

- **Inputs:** `property_id`
- **Output:** 202 Accepted
- **Raises:** 422 if the property has no coordinates
- **Source:** `src/properties/adapters/api/routes/property_amenities.py` (publishes the event directly)

### GetPropertyAmenities

Return discovered amenities. The discovery worker fetches up to 9 categories (hospital, bank, grocery, school, laundry, coffee_shop, pharmacy, gym, restaurant) and stores the nearest place plus up to 5 top places per category.

- **Inputs:** `property_id`
- **Output:** `list[PropertyAmenity]`
- **Source:** `src/properties/application/use_cases/get_property_amenities.py`

### ListPropertyPois

Read the property's POI catalog. Pure read; no aggregate_version bump.

- **Inputs:** `property_id`, `organization_id`
- **Output:** `list[PropertyPoi]` ordered by `created_at desc`
- **Raises:** `PropertyNotFoundError` (404) on cross-org or unknown id
- **Source:** `src/properties/application/use_cases/list_property_pois.py`

### ReplacePropertyPois

Replace the entire POI catalog for one property in a single call. Every persisted row is flagged `manually_edited=true` so the future enrichment workflow won't re-discover categories the agent has touched. Empty list clears the catalog. Bumps `aggregate_version`.

- **Inputs:** `property_id`, `organization_id`, `pois: list[PoiInput]`
- **Output:** `list[PropertyPoi]` (the persisted rows with their new ids and timestamps)
- **Raises:** `PropertyNotFoundError`
- **Source:** `src/properties/application/use_cases/replace_property_pois.py`

### UpdatePropertyPoi

PATCH semantics on a single POI row. Sets `manually_edited=true` on success. Cross-property defense: 404 if `poi_id` exists but belongs to a different property. Bumps `aggregate_version`.

- **Inputs:** `property_id`, `organization_id`, `poi_id`, `patch: PoiPatch`
- **Output:** updated `PropertyPoi`
- **Raises:** `PropertyNotFoundError` (cross-org, missing property, missing/cross-property POI)
- **Source:** `src/properties/application/use_cases/update_property_poi.py`

### DeletePropertyPoi

Remove one POI. Same cross-org + cross-property defense as `UpdatePropertyPoi`. Missing POI raises `PropertyNotFoundError` (not idempotent — matches the `delete_property` precedent). Bumps `aggregate_version`.

- **Inputs:** `property_id`, `organization_id`, `poi_id`
- **Output:** none (204)
- **Raises:** `PropertyNotFoundError`
- **Source:** `src/properties/application/use_cases/delete_property_poi.py`

## Workers

All three properties workers run on the shared `src/shared/events/worker.py:EventBusWorker` (ADR-008). Handlers take `(event: DomainEvent, container) -> None`.

| Worker | CLI | Queue / Topic | Handlers |
|---|---|---|---|
| `extraction_processor.py` | `python -m properties.entrypoints.worker --queue extraction` | `property-extraction-queue` (SQS command) | `handle_property_extraction_requested` (for `PROPERTY_EXTRACTION_REQUESTED.v1`) + `handle_batch_property_extraction_requested` (for `BATCH_PROPERTY_EXTRACTION_REQUESTED.v1`) |
| `discovery_processor.py` | `python -m properties.entrypoints.events_worker` | `properties-events-queue` (subscribed to `domain-events-PROPERTY_CREATED-v1` SNS topic) | `handle_property_created` |

The discovery worker runs up to 5 Google Places queries concurrently and uses `domain/services/amenity_ranker.py` to boost known Portuguese brands.

## End-to-end flows

### Single document extraction

```
client                 API                          extraction worker            discovery worker
  │                     │                                    │                           │
  ├─ POST /presign ────►│                                    │                           │
  │◄── job_id, urls ────┤                                    │                           │
  ├─ PUT to S3 ─────────┼──► S3                               │                           │
  ├─ POST /jobs ───────►│                                    │                           │
  │                     ├── ExtractionJob saved              │                           │
  │                     ├── CommandPublisher.send(PROPERTY_EXTRACTION_REQUESTED.v1) ────►│
  │◄── 202 (job_id) ────┤                                    │                           │
  │                     │                                    ├── download from S3        │
  │                     │                                    ├── Reducto OCR             │
  │                     │                                    ├── OpenAI extract          │
  │                     │                                    ├── geocode                 │
  │                     │                                    ├── save Property           │
  │                     │                                    ├── EventPublisher.publish(PROPERTY_CREATED.v1) ──►
  │                     │                                    │                           ├── Google Places
  │                     │                                    │                           ├── rank + dedup
  │                     │                                    │                           ├── save amenities
```

### Batch extraction

Same shape, but the worker also runs document classification and creates `PropertyOwner` rows for each ID document, deduped by NIF. On retry, the worker reuses cached `DocumentContent` rows to skip re-running OCR.

## Container

`src/properties/container.py` wires 24+ use cases. The container has optional dependencies: extraction-related use cases are only created if the document storage, parser, extractor, and event bus are provided. The bootstrap module (`src/shared/entrypoints/bootstrap.py::get_property_container()`) supplies all of them in production.
