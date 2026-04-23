# Predileto Core API

Centralized backend service for the Predileto platform, handling user/company management, subscriptions, and notifications. Built with FastAPI and a hexagonal (ports & adapters) architecture.

## Tech Stack

- **Python 3.13** (managed with [uv](https://docs.astral.sh/uv/))
- **FastAPI** (async)
- **Supabase** (PostgreSQL + Auth)
- **Resend** (transactional email)
- **SQS** (event queue, LocalStack for local dev)
- **structlog** (structured logging)
- **pytest** (unit + integration tests with in-memory adapters)

## Prerequisites

- [uv](https://docs.astral.sh/uv/) (Python package manager)
- [Docker](https://www.docker.com/) (for LocalStack)
- PostgreSQL (Supabase-hosted or local)

## Setup

### 1. Install dependencies

```bash
uv sync --extra dev
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env` with your values:

| Variable | Description |
|----------|-------------|
| `SUPABASE_URL` | Supabase API URL (default: `http://127.0.0.1:54321`) |
| `SUPABASE_SERVICE_ROLE_KEY` | Supabase service role key |
| `SUPABASE_JWT_SECRET` | JWT secret for token verification |
| `DATABASE_URL` | PostgreSQL connection for Alembic (`postgresql+asyncpg://...`) |
| `RESEND_API_KEY` | [Resend](https://resend.com) API key |
| `AWS_ENDPOINT_URL` | LocalStack endpoint (default: `http://localhost:4566`) |
| `SNS_DOMAIN_EVENTS_TOPIC_ARN_PREFIX` | SNS topic ARN prefix for domain events (ADR-008 fan-out). Publisher resolves topic ARNs as `${prefix}${event_type.replace('.', '-')}` |
| `SQS_CUSTOMERS_EVENTS_QUEUE_URL` / `_DLQ_URL` | Per-context domain-event queue for customers (subscribed to `APPLICANT_SCREENED.v1` SNS topic) + DLQ |
| `SQS_BOOKINGS_EVENTS_QUEUE_URL` / `_DLQ_URL` | Per-context queue for bookings + DLQ |
| `SQS_PROPERTIES_EVENTS_QUEUE_URL` / `_DLQ_URL` | Per-context queue for properties + DLQ |
| `SQS_PROPERTY_EXTRACTION_QUEUE_URL` / `_DLQ_URL` | Command queue for property extraction + DLQ |
| `SQS_APPLICANT_EXTRACTION_QUEUE_URL` / `_DLQ_URL` | Command queue for applicant document extraction + DLQ |
| `SQS_APPLICANT_SCREENING_QUEUE_URL` / `_DLQ_URL` | Command queue for applicant screening + DLQ |
| `GOOGLE_MAPS_API_KEY` | Google Maps API key (Places API enabled) |
| `APP_URL` | Frontend base URL (e.g. `http://localhost:4000`) — used to build Stripe Checkout success / cancel + Customer Portal return URLs |
| `STRIPE_API_KEY` | Stripe secret key (sandbox: `sk_test_...`, prod: `sk_live_...`) |
| `STRIPE_WEBHOOK_SECRET` | Signing secret for `/api/v1/billing/webhooks/stripe` (`whsec_...`) |
| `STRIPE_PRICE_PRO_MONTHLY` / `_YEARLY` | Stripe `price_*` IDs for the Pro plan |
| `STRIPE_PRICE_ENTERPRISE_MONTHLY` / `_YEARLY` | Stripe `price_*` IDs for the Enterprise plan |
| `STRIPE_TRIAL_PERIOD_DAYS` | Free-trial length passed to Checkout (default `7`) |
| `CORS_ORIGINS` | Comma-separated allowed origins |

### 3. Run database migrations

```bash
uv run alembic upgrade head
```

Other useful Alembic commands:

```bash
# Check current migration status
uv run alembic current

# View migration history
uv run alembic history

# Create a new migration after editing SQLAlchemy models
uv run alembic revision --autogenerate -m "description"

# Rollback one migration
uv run alembic downgrade -1

# Stamp an existing database as up-to-date (no DDL)
uv run alembic stamp head
```

Schema is defined in SQLAlchemy models across bounded contexts: `src/customers/adapters/database/models.py`, `src/properties/adapters/database/models.py`, `src/screening/adapters/database/models.py`, and `src/bookings/adapters/database/models.py`.

**Adopting on an existing database:** If the database already has the schema (e.g. production), stamp it as current without executing any DDL:

```bash
DATABASE_URL=postgresql+asyncpg://... uv run alembic stamp head
```

### 4. Start LocalStack (for SQS/S3)

```bash
docker compose up -d
```

### 5. Run the server

```bash
uv run uvicorn shared.main:app --reload --port 8000
```

The API is available at `http://localhost:8000`. Interactive docs at `http://localhost:8000/docs`.

## Running Tests

```bash
uv run pytest -v
```

Tests use in-memory adapters (no database or external services required). The test suite includes:

- **Unit tests** — value object validation, domain model construction
- **Integration tests** — full HTTP request/response cycle via httpx `AsyncClient`

## API Endpoints

All endpoints are prefixed with `/api/v1`. Authenticated endpoints require a Supabase JWT in the `Authorization: Bearer <token>` header.

### Public

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Readiness check |
| `GET` | `/subscriptions/plans` | List available plans |

### Auth

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/auth/register` | Create user + company (post-signup) |
| `GET` | `/auth/me` | Get current user with company |

### Users

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/users/me` | Get user profile with company |
| `PATCH` | `/users/me` | Update name and/or phone |

### Companies

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/companies/{id}` | Get company (own company only) |
| `PATCH` | `/companies/{id}` | Update company details |

### Billing

Stripe Checkout + Customer Portal. OWNER / ADMIN role required for mutations. Webhook is signature-authed and bypasses JWT. See [Stripe Billing Setup](#stripe-billing-setup) for Stripe dashboard configuration and [docs/features/billing.md](docs/features/billing.md) for the lifecycle.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/admin/billing/plans` | List available plans (`freemium`, `pro`, `enterprise`) — no auth inside the admin scope |
| `GET` | `/admin/billing/subscription` | Get current organization's subscription (plan, status, period, `stripe_customer_id`) |
| `POST` | `/admin/billing/checkout` | Start a Stripe Checkout session. Body: `{plan, cadence}`. Returns `{url, session_id}` |
| `POST` | `/admin/billing/portal` | Open the Stripe Customer Portal for cancel / change plan / update card / invoices |
| `POST` | `/billing/webhooks/stripe` | Stripe webhook ingress. Signature-verified via `Stripe-Signature` header |

### Notifications

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/notifications` | List notifications (paginated) |
| `PATCH` | `/notifications/read` | Mark notifications as read |
| `POST` | `/notifications` | Create notification |

### Email

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/email/send` | Send email via Resend |

### Properties

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/properties` | Create property (draft status) |
| `GET` | `/properties` | List properties by organization |
| `GET` | `/properties/summary` | Lightweight properties list |
| `GET` | `/properties/{id}` | Get property with owners, prices, images |

### Property Owners

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/property-owners` | Add owner to property |
| `POST` | `/property-owners/extract-from-document` | Extract owner from ID document |
| `GET` | `/property-owners` | List owners for property |
| `GET` | `/property-owners/{id}` | Get single owner |
| `PATCH` | `/property-owners/{id}/contact` | Update email/phone |

### Property Prices

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/property-prices` | Add price to property |
| `GET` | `/property-prices` | List prices for property |

### Property Images

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/property-images/presign` | Generate presigned S3 upload URLs |
| `POST` | `/property-images` | Record image metadata after upload |
| `DELETE` | `/property-images/{id}` | Delete image |
| `PUT` | `/property-images/reorder` | Reorder images by display order |

### Property Amenities

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/property-amenities` | List discovered amenities for a property |
| `POST` | `/property-amenities/discover` | Trigger amenity discovery (returns 202) |

### Extraction Jobs

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/extraction-jobs/presign` | Presign S3 URLs for documents |
| `POST` | `/extraction-jobs` | Submit single extraction job |
| `POST` | `/extraction-jobs/batch` | Submit batch extraction (1–5 docs) |
| `POST` | `/extraction-jobs/{id}/retry` | Retry failed job |
| `GET` | `/extraction-jobs` | List jobs by organization |
| `GET` | `/extraction-jobs/{id}` | Get job status |

### Applicant Screening (Admin — `/api/v1/admin`)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/applicants` | List applicants for organization |
| `GET` | `/applicants/{id}` | Get applicant detail with screening report |
| `POST` | `/intake-form-requests` | Create intake form request |
| `GET` | `/intake-form-requests` | List intake form requests |
| `GET` | `/intake-form-requests/{id}` | Get intake form request |

### Applicant Screening (Portal — `/api/v1/portal`)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/submissions/uploads/presign` | Get presigned S3 URLs for document uploads |
| `POST` | `/submissions` | Submit applicant documents for screening |
| `GET` | `/submissions/{applicant_id}/status` | Check screening status |

### Property Listings (Public — `/api/v1/listings`)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/properties` | List active properties with filtering and pagination |
| `GET` | `/properties/{id}` | Get single active property detail |

Query parameters for listing: `listing_type`, `typology`, `min_price`, `max_price`, `district`, `limit`, `offset`.

### Booking Management (Admin — `/api/v1/admin`)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/slots` | Create a visit time slot for a property |
| `GET` | `/slots` | List slots (filter by `property_id` or agent) |
| `GET` | `/slots/{id}` | Get slot details |
| `DELETE` | `/slots/{id}` | Cancel a slot (cascades to booking if booked) |
| `GET` | `/bookings` | List bookings for organization |
| `GET` | `/bookings/{id}` | Get booking details |
| `DELETE` | `/bookings/{id}` | Cancel a booking (agent cancellation) |
| `POST` | `/booking-invitations` | Generate signed booking invitation link |

### Booking Management (Portal — `/api/v1/portal`)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/properties/{id}/slots` | List available slots for a property (future only) |
| `POST` | `/bookings` | Create a booking (requires booking invitation token) |
| `GET` | `/bookings/status` | List applicant's bookings |

## Architecture

```
src/organizations/
├── domain/           # Entities, value objects, events, exceptions (no dependencies)
├── application/
│   ├── ports/        # Abstract interfaces (repository ABCs, services)
│   └── use_cases/    # Business logic orchestration
├── adapters/
│   ├── api/          # Inbound: FastAPI routes, schemas, middleware
│   ├── database/     # SQLAlchemy models (schema source of truth)
│   ├── persistence/  # Outbound: Supabase repository implementations
│   ├── email/        # Outbound: Resend email service
│   ├── workers/      # SQS event processors
│   └── inmemory/     # Test doubles for all ports
├── entrypoints/
│   ├── lambda_handler.py  # FastAPI → AWS Lambda adapter (Mangum)
│   └── worker.py     # CLI entrypoint: python -m organizations.entrypoints.worker
├── container.py      # Dependency injection wiring
```

Identity follows the same hexagonal structure — a smaller tree, owning just `User` + its ports + adapters + container.

### Bounded Contexts

The service hosts seven independent bounded contexts, each following hexagonal architecture:

| Context | Package | Entities | Persistence |
|---------|---------|----------|-------------|
| **Identity** | `src/identity/` | `User` (Supabase-backed; no organization FK — tenancy is in memberships) | Supabase PostgREST + SQLAlchemy |
| **Organizations** | `src/organizations/` | `Organization`, `Membership`, `Invitation`, `Subscription`, `Notification` | Supabase PostgREST + SQLAlchemy |
| **Property Management** | `src/properties/` | Property, PropertyOwner, PropertyImage, PropertyAmenity, ExtractionJob, DocumentContent | Supabase PostgREST |
| **Applicant Screening** | `src/screening/` | Applicant, Document, ExtractedData, ScreeningReport, Submission, IntakeFormRequest | SQLAlchemy + Alembic |
| **Properties Listing** | `src/listings/` | ListedProperty (read-only view of properties data) | SQLAlchemy (read-only) |
| **Booking Management** | `src/bookings/` | Slot, Booking, BookingApplicant | SQLAlchemy + Alembic |
| **Contract Intelligence** | `src/contract_intelligence/` | SourceDocument, TemplateVersion, GeneratedContract | SQLAlchemy + Alembic |

Cross-context dependency rule: **organizations depends on identity** via two callable Protocols (`UserLookupById`, `RegisterUserPort`) injected at construction. No other cross-context dependencies — everything else is loose coupling through the shared event bus (ADR-008).

All are wired in `shared/main.py` via `create_app()` and bootstrapped in `shared/entrypoints/bootstrap.py`. `IdentityMiddleware` populates `request.state.{user, memberships}` from identity + organizations on every authenticated request; admin routes enforce membership via `require_org_member` with zero additional DB hits.

Shared infrastructure lives in `src/shared/` — config, middleware, database Base, app factory, bootstrap, S3 storage, and Lambda handler.

### Property Management

#### Domain Values

- **ListingType**: `sale`, `purchase`
- **Typology**: `house`, `apartment`, `land`, `ruin`
- **PropertyStatus**: `draft`, `active`, `sold`, `rented`, `withdrawn`
- **DocumentType** (owner ID docs): `cartao_cidadao`, `passport`, `visto_residencia`, `titulo_residencia`
- **AmenityCategory**: `hospital`, `bank`, `grocery`, `school`, `laundry`, `coffee_shop`, `pharmacy`, `gym`, `restaurant`

#### Property Extraction Flow

Two async extraction flows, both following: presign → upload → submit → SQS → process.

1. **Single extraction** (`POST /api/v1/extraction-jobs`): One property document → parse with Reducto → extract property + owners from text.
2. **Batch extraction** (`POST /api/v1/extraction-jobs/batch`): 1–5 mixed documents → parse all with Reducto (single OCR pass) → persist parsed text in `document_contents` → classify from text → extract property data from property docs → extract owner data from ID docs with subtype-specific prompts → merge owners by NIF (ID extraction wins) → create Property + PropertyOwners.

All document processing follows a **parse-first** approach: documents are OCR'd once via Reducto, and all downstream steps (classification, property extraction, ID extraction) operate on the parsed text — no re-OCR or vision API calls.

`listing_type` and `typology` are **user inputs** provided at submission time, not extracted from documents. They are stored on the ExtractionJob and used when creating the Property.

#### Property Image Flow

Images are managed separately from property creation, following: presign → upload → record.

1. **Presign** (`POST /api/v1/property-images/presign`): Generate presigned S3 upload URLs. S3 key: `properties/{property_id}/images/{image_id}.{ext}`.
2. **Upload**: Frontend uploads directly to S3 using presigned URLs.
3. **Record** (`POST /api/v1/property-images`): Record image metadata after upload. Verifies file exists in S3. Max 20 images per property.
4. **Reorder** (`PUT /api/v1/property-images/reorder`): Update `display_order` for all images.
5. **Delete** (`DELETE /api/v1/property-images/{image_id}`): Remove metadata only (S3 cleanup via lifecycle policy).

Images with presigned download URLs are returned inline in `PropertyResponse`.

#### Ports & Adapters

| Port | Purpose | Production Adapter |
|------|---------|-------------------|
| `PropertyRepository` | CRUD for properties, owners, images | `SupabasePropertyRepository` |
| `ExtractionJobRepository` | CRUD for extraction jobs | `SupabaseExtractionJobRepository` |
| `DocumentContentRepository` | Persist parsed document text + classification | `SupabaseDocumentContentRepository` |
| `DocumentParser` | OCR / document parsing | `ReductoDocumentParser` |
| `PropertyExtractorService` | AI property extraction from text | `ReductoOpenAIPropertyExtractor` |
| `DocumentDataExtractor` | AI owner data from ID doc text | `OpenAIIdDocumentExtractor` |
| `DocumentClassifier` | AI document classification from text | `OpenAITextDocumentClassifier` |
| `DocumentStorage` | S3 file upload/download/presigned URLs | `S3DocumentStorage` |
| `CommandPublisher` | SQS point-to-point command publishing | `SQSCommandPublisher` |
| `EventPublisher` | Cross-context domain event broadcast (SNS fan-out) | `SNSEventPublisher` |
| `PlacesService` | Nearby amenity discovery | `GooglePlacesService` |
| `PropertyAmenityRepository` | CRUD for property amenities | `SupabasePropertyAmenityRepository` |

### Dependency Injection

Each bounded context has its own `container.py` that wires use cases with their port implementations. For tests, `conftest.py` builds both containers using in-memory adapters — no external services needed. Test HTTP client uses `httpx.AsyncClient` with `ASGITransport`.

### Auth Flow

1. Dashboard handles Supabase signup/login and obtains a JWT
2. Requests to core-api include the JWT as `Authorization: Bearer <token>`
3. Middleware decodes the JWT using `SUPABASE_JWT_SECRET`, extracts the `sub` claim
4. The `sub` is used to look up the `User` record by `supabase_user_id`
5. Public endpoints (`/health`, `/subscriptions/plans`) skip auth

## Docker

Build and run the API in a container:

```bash
docker build -t core-api .
docker run -p 8000:8000 --env-file .env core-api
```

## Running Locally

### Prerequisites

- [uv](https://docs.astral.sh/uv/) (Python)
- [Node.js 22](https://nodejs.org/) (frontend)
- [Docker](https://www.docker.com/) (LocalStack + Postgres)
- Supabase project (local via `supabase start` or hosted)

### 1. Start infrastructure

```bash
docker compose up -d
```

LocalStack creates these SQS queues:

| Queue | Purpose |
|-------|---------|
| SNS topic per `.v1` event type | **Domain events** (`domain-events-PROPERTY_CREATED-v1`, `domain-events-APPLICANT_SCREENED-v1`, …). Publisher is `SNSEventPublisher`. |
| `customers-events-queue` / `bookings-events-queue` / `properties-events-queue` | **Per-context domain-event consumers.** Each SQS queue subscribes to the SNS topics the context cares about. Each has its own DLQ with `maxReceiveCount=5`. |
| `property-extraction-queue` / `applicant-extraction-queue` / `applicant-screening-queue` | **Command queues** — point-to-point work sent via `SQSCommandPublisher`. Each has its own DLQ. |
| `contract-ingestion-queue` / `contract-analysis-queue` | Contract-intelligence command queues (+ DLQs). |
| `domain-events` (legacy) | Kept during cutover per ADR-008 §Rollout; drained + deleted one week post-cutover. |

Domain events flow through **SNS fan-out** — one SNS topic per `.v1` event type, each context SQS queue subscribed to the topics it handles. Handler isolation is per-queue: a poison message in one context's queue only affects that context. Commands stay on dedicated SQS queues — point-to-point, one consumer per queue, independent scaling (extraction is I/O bound on Reducto, screening is LLM bound on OpenAI). See [ADR-008](docs/adr/008-event-bus-ports-and-fanout.md) for the full architecture.

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env — set SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, SUPABASE_JWT_SECRET, DATABASE_URL
```

Key SQS / SNS env vars:

| Variable | Local Value |
|----------|-------------|
| `SNS_DOMAIN_EVENTS_TOPIC_ARN_PREFIX` | `arn:aws:sns:us-east-1:000000000000:domain-events-` |
| `SQS_CUSTOMERS_EVENTS_QUEUE_URL` | `http://localhost:4566/000000000000/customers-events-queue` |
| `SQS_BOOKINGS_EVENTS_QUEUE_URL` | `http://localhost:4566/000000000000/bookings-events-queue` |
| `SQS_PROPERTIES_EVENTS_QUEUE_URL` | `http://localhost:4566/000000000000/properties-events-queue` |
| `SQS_PROPERTY_EXTRACTION_QUEUE_URL` | `http://localhost:4566/000000000000/property-extraction-queue` |
| `SQS_APPLICANT_EXTRACTION_QUEUE_URL` | `http://localhost:4566/000000000000/applicant-extraction-queue` |
| `SQS_APPLICANT_SCREENING_QUEUE_URL` | `http://localhost:4566/000000000000/applicant-screening-queue` |
| `AWS_ENDPOINT_URL` | `http://localhost:4566` |
| `AWS_ACCESS_KEY_ID` | `test` |
| `AWS_SECRET_ACCESS_KEY` | `test` |

### 3. Run database migrations

```bash
uv run alembic upgrade head
```

### 4. Start all services

Use separate terminals or a process manager like [overmind](https://github.com/DarthSim/overmind)/[foreman](https://github.com/ddollar/foreman):

```bash
# Terminal 1 — API server
uv run uvicorn shared.main:app --reload --port 8000

# Terminal 2 — Per-context domain-event workers (one terminal per context).
#   customers  → APPLICANT_SCREENED.v1 (send screening-complete email)
#   bookings   → APPLICANT_SCREENED.v1 (create booking applicant)
#   properties → PROPERTY_CREATED.v1  (discover amenities)
#   listings   → PROPERTY_{CREATED,UPDATED,DELETED,PUBLISHED}.v1 + address enrichment
uv run python -m customers.entrypoints.worker --queue events
uv run python -m bookings.entrypoints.events_worker
uv run python -m properties.entrypoints.events_worker
uv run python -m listings.entrypoints.events_worker

# Terminal 3 — Property extraction worker
uv run python -m properties.entrypoints.worker --queue extraction

# Terminal 4 — Applicant extraction worker
uv run python -m screening.entrypoints.worker --queue extraction

# Terminal 5 — Applicant screening worker
uv run python -m screening.entrypoints.worker --queue screening

# Terminal 6 — Contract ingestion worker (Reducto OCR pipeline)
uv run python -m contract_intelligence.entrypoints.worker --queue ingestion

# Terminal 7 — Contract analysis worker (LLM section classification)
uv run python -m contract_intelligence.entrypoints.worker --queue analysis

# Terminal 8 — Agencies dashboard
cd ../estate-os && npm run dev

# Terminal 7 — Applicant intake form
cd ../applicants-intake-form && npm run dev
```

### 5. End-to-end test

1. Open the agencies dashboard at `http://localhost:4000`
2. Navigate to **Intake Forms** and create a new request
3. Open the applicant link (or go to `http://localhost:5173/<form-request-id>`)
4. Submit the intake form with documents
5. Watch the extraction → screening pipeline process the documents
6. The domain events worker picks up `APPLICANT_SCREENED` and:
   - Sends a notification email (customers handler)
   - Creates a booking-context applicant (bookings handler)
7. Refresh the dashboard — the new applicant appears in the **Applicants** list

### Manually publishing a test event

To test the per-context domain-event workers without running the full pipeline, publish to an SNS topic — the message fans out to every subscribed context queue:

```bash
aws --endpoint-url=http://localhost:4566 sns publish \
  --topic-arn arn:aws:sns:us-east-1:000000000000:domain-events-APPLICANT_SCREENED-v1 \
  --message '{
    "event_type": "APPLICANT_SCREENED.v1",
    "event_id": "test-event-001",
    "occurred_at": "2026-04-18T12:00:00Z",
    "data": {
      "applicant_id": "00000000-0000-0000-0000-000000000001",
      "form_request_id": "<a-real-intake-form-request-id>",
      "organization_id": "<agency-org-uuid>",
      "name": "João Silva",
      "email": "joao@example.com",
      "date_of_birth": "1990-05-15",
      "listing_type": "ARRENDAMENTO",
      "monthly_rent": 850.0,
      "has_id_document": true,
      "has_proof_of_income": true,
      "documents": [],
      "screening": {
        "risk_level": "LOW",
        "identity_verified": true,
        "income_verified": true,
        "dti_ratio": 0.28,
        "justification": "All checks passed.",
        "average_monthly_income": 3000.0
      },
      "screened_at": "2026-04-18T12:00:00Z"
    }
  }'
```

Both the `customers` and `bookings` context queues are subscribed to this topic, so both workers will receive and process the event independently (per-handler DLQ isolation — ADR-008). The canonical envelope is `{event_type, event_id, occurred_at, data: {...}}` and every event type string ends with `.v1`.

## Workers

### Domain Events Worker

The unified domain events worker polls the single `domain-events` queue and routes events to handlers registered from all bounded contexts. One event can trigger multiple handlers.

```bash
uv run python -m shared.entrypoints.events_worker
```

| Event | Handlers |
|-------|----------|
| `APPLICANT_SCREENED` | customers (send notification email), bookings (create booking applicant) |
| `PROPERTY_CREATED` | properties (discover nearby amenities via Google Places API) |

In production, deploy as a Lambda function: `shared.entrypoints.lambda_events.handler`.

#### Event Envelope Format

All domain events follow the same structure:

```json
{
  "event_type": "APPLICANT_SCREENED",
  "event_id": "uuid",
  "occurred_at": "2026-03-30T12:00:00+00:00",
  "data": { ... }
}
```

Event types are defined in `src/shared/events/types.py`. Handlers are registered in `src/shared/entrypoints/events_worker.py:_build_router()`.

### Property Extraction Worker

Processes property document extraction jobs from the `property-extraction-queue` task queue.

```bash
uv run python -m properties.entrypoints.worker --queue extraction
```

Retry a failed job:

```bash
# CLI
uv run python -m properties.entrypoints.worker --retry-job <job_id>

# API
curl -X POST http://localhost:8000/api/v1/extraction-jobs/<job_id>/retry \
  -H "Authorization: Bearer <token>"
```

### Applicant Extraction + Screening Workers

Process applicant document extraction and LLM screening from their respective task queues.

```bash
# Extraction (Reducto OCR)
uv run python -m screening.entrypoints.worker --queue extraction

# Screening (LangGraph 4-node pipeline)
uv run python -m screening.entrypoints.worker --queue screening
```

In production, deploy as Lambda functions: `screening.entrypoints.lambda_extraction.handler` and `screening.entrypoints.lambda_screening.handler`.

### Contract Ingestion + Analysis Workers

Process contract document ingestion (Reducto OCR pipeline) and LLM section analysis from their respective task queues. These workers include a heartbeat mechanism that extends SQS message visibility during long-running Reducto/LLM calls.

```bash
# Ingestion (Reducto parse + extract pipeline)
uv run python -m contract_intelligence.entrypoints.worker --queue ingestion

# Analysis (LLM section classification via LangChain/OpenAI)
uv run python -m contract_intelligence.entrypoints.worker --queue analysis

# Dead-letter queue (marks failed documents)
uv run python -m contract_intelligence.entrypoints.worker --queue dlq
```

In production, deploy as Lambda functions: `contract_intelligence.entrypoints.lambda_ingestion.handler` and `contract_intelligence.entrypoints.lambda_analysis.handler`.

### Property Discovery (via Domain Events)

Property discovery no longer has its own worker or queue. When a property is created, a `PROPERTY_CREATED` domain event is published and the domain events worker handles it automatically.

To trigger discovery manually for an existing property:

```bash
curl -X POST "http://localhost:8000/api/v1/property-amenities/discover?property_id=<uuid>&organization_id=<uuid>" \
  -H "Authorization: Bearer <token>"
```

This publishes a `PROPERTY_CREATED` event to the domain events queue. Returns `202 Accepted`.

Discovery searches within a **5 km radius** for hospitals, banks, schools, pharmacies, gyms, restaurants, laundries, coffee shops, and Portuguese grocery chains. Properties without coordinates are skipped. Discovery is idempotent.

## Applicant Screening

The applicant screening context handles the full document-based screening pipeline for property applicants. It receives document uploads (ID + proof of income), extracts data via Reducto OCR, and runs an LLM-based assessment via a LangGraph pipeline.

### Processing Pipeline

1. **Intake Form Request** — agency creates a request via the admin API, generating a unique link for the applicant
2. **Submission** — applicant uploads documents via presigned S3 URLs, system creates applicant record and publishes extraction messages to SQS
3. **Extraction** (SQS worker/Lambda) — calls Reducto API to extract text from documents
4. **Screening** (SQS worker/Lambda) — runs a 4-node LangGraph pipeline: verify identity → verify income → assess affordability → generate report
5. **Event** — publishes `APPLICANT_SCREENED` domain event to the unified domain events queue, where the events worker routes it to bookings (create applicant) and customers (send notification)

### NIF Encryption

Portuguese Tax IDs (NIFs) are encrypted at rest using RSA (OAEP/SHA-256) and use HMAC-SHA256 blind indexing for lookups without decryption. Keys are base64-encoded PEM strings in env vars (`ENCRYPTION_PUBLIC_KEY`, `ENCRYPTION_PRIVATE_KEY`, `ENCRYPTION_HMAC_KEY`).

### Environment Variables

| Variable | Description |
|----------|-------------|
| `SQS_APPLICANT_EXTRACTION_QUEUE_URL` | SQS queue for extraction jobs |
| `SQS_APPLICANT_SCREENING_QUEUE_URL` | SQS queue for screening assessment |
| `ENCRYPTION_PUBLIC_KEY` | RSA public key (base64 PEM) |
| `ENCRYPTION_PRIVATE_KEY` | RSA private key (base64 PEM) |
| `ENCRYPTION_HMAC_KEY` | HMAC key (base64) |
| `REDUCTO_API_KEY` | Reducto OCR API key |
| `OPENAI_API_KEY` | OpenAI API key (for LangGraph pipeline) |
| `MAX_APPLICANT_DOCUMENTS` | Max documents per submission (default: 5) |

## Booking Management

The booking management context allows agency staff to create visit time slots for properties and approved applicants to book visits.

### How It Works

```
Agency (admin)                     Applicant (portal)
     │                                    │
     │  1. Create slots for property      │
     │  POST /api/v1/admin/slots          │
     │                                    │
     │  2. Generate booking invitation    │
     │  POST /api/v1/admin/booking-invitations
     │  → returns signed token + URL      │
     │                                    │
     │  3. Share link with applicant ─────►│
     │                                    │
     │                                    │  4. View available slots
     │                                    │  GET /api/v1/portal/properties/{id}/slots
     │                                    │
     │                                    │  5. Book a slot
     │                                    │  POST /api/v1/portal/bookings
     │                                    │  (uses booking token, not JWT)
     │                                    │
     │  6. View bookings                  │
     │  GET /api/v1/admin/bookings        │
     │                                    │
     │  7. Cancel slot or booking         │
     │  DELETE /api/v1/admin/slots/{id}   │
     │  DELETE /api/v1/admin/bookings/{id}│
```

### Domain Models

**Slot** — a time window when a property can be visited.

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Primary key |
| `property_id` | UUID | Property being visited |
| `agent_user_id` | UUID | Supabase user ID of the agent who created it |
| `organization_id` | UUID | Organization scope |
| `start_time` | datetime | Visit start |
| `end_time` | datetime | Visit end (must be after start) |
| `status` | string | `available` → `booked` → `cancelled` |

**Booking** — a confirmed visit by an applicant.

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Primary key |
| `slot_id` | UUID | The booked slot (unique — one booking per slot) |
| `applicant_id` | UUID | Booking-context applicant |
| `property_id` | UUID | Denormalized from slot |
| `organization_id` | UUID | Denormalized from slot |
| `status` | string | `confirmed`, `cancelled_by_applicant`, `cancelled_by_agent` |
| `notes` | string | Optional notes from applicant |

**BookingApplicant** — local projection of screened applicants (created from `APPLICANT_SCREENED` SQS events). Only LOW and MEDIUM risk applicants are accepted; HIGH risk is rejected.

### Key Patterns

- **Optimistic locking** prevents double-booking: `UPDATE booking_slots SET status='booked' WHERE id=? AND status='available'` — if the slot was already booked by another request, the update affects 0 rows and the booking is rejected with 409 Conflict
- **Booking invitation tokens** — HS256-signed JWTs containing `applicant_id`, `property_id`, `organization_id`, and `email`. Valid for 7 days. Used for `POST /api/v1/portal/bookings` instead of Supabase JWT
- **Cascade cancellation** — cancelling a booked slot automatically cancels the linked booking and releases the slot
- **Organization scoping** — slot creation verifies the property belongs to the agent's organization (cross-context check via `property_container.get_property`)

### Event Handling

The `APPLICANT_SCREENED` domain event is handled by the unified domain events worker (not a booking-specific consumer). The handler at `bookings.adapters.events.handlers.handle_applicant_screened` creates booking-context applicant records from the screening pipeline output.

### Environment Variables

| Variable | Description |
|----------|-------------|
| `BOOKING_TOKEN_SECRET` | HS256 secret for signing booking invitation tokens |
| `BOOKING_LINK_URL` | Base URL for booking links (default: `https://portal.predileto.com/book`) |

### Database Tables

All tables are prefixed with `booking_` to avoid collision with other contexts:

- `booking_applicants` — local applicant projection (external_id unique, risk_level)
- `booking_slots` — visit time slots (CHECK: end > start, CHECK: status enum)
- `booking_bookings` — confirmed visits (UNIQUE slot_id, FK to slots + applicants)

## Stripe Billing Setup

The `billing` bounded context (`src/billing/`) integrates Stripe-hosted Checkout and Customer Portal. This section lists exactly what to create in the Stripe Dashboard — sandbox for local dev, prod for production. The same steps apply in both modes; only the keys and the webhook endpoint URL differ. See [docs/features/billing.md](docs/features/billing.md) for the subscription lifecycle and [docs/runbooks/stripe-sandbox-setup.md](docs/runbooks/stripe-sandbox-setup.md) for the full operator runbook.

### 1. Create Products + recurring Prices

Create **two products**, each with **two recurring prices** (monthly + yearly). Prices below are the Portuguese launch tier — adjust as needed before creating them in live mode.

| Product | Price nickname | Amount | Billing cycle | Currency | `env` variable |
|---------|---------------|--------|---------------|----------|-----------------|
| **Pro** | `pro_monthly` | €29.00 | monthly | EUR | `STRIPE_PRICE_PRO_MONTHLY` |
| **Pro** | `pro_yearly` | €290.00 | yearly | EUR | `STRIPE_PRICE_PRO_YEARLY` |
| **Enterprise** | `enterprise_monthly` | €99.00 | monthly | EUR | `STRIPE_PRICE_ENTERPRISE_MONTHLY` |
| **Enterprise** | `enterprise_yearly` | €990.00 | yearly | EUR | `STRIPE_PRICE_ENTERPRISE_YEARLY` |

Freemium is **not** a Stripe product — it's the default seeded plan for every new Organization and has no Stripe objects.

Copy the four `price_*` IDs from the Dashboard into the matching env vars. Also copy the secret key (`sk_test_...` in sandbox, `sk_live_...` in prod) into `STRIPE_API_KEY`.

### 2. Configure the webhook endpoint

The webhook route is `POST /api/v1/billing/webhooks/stripe`. It's whitelisted in `JWTAuthMiddleware.PUBLIC_PREFIXES` and authenticates solely via the `Stripe-Signature` header — invalid signatures are rejected with 400, and replayed `event.id`s are a no-op (idempotency guarded by the `stripe_webhook_events` table inside `HandleStripeWebhookEvent`).

The setup is different in sandbox vs. prod:

#### Sandbox (local dev)

**Do not create a webhook endpoint in the Dashboard.** The Stripe CLI does it for you on the fly and tunnels every test-mode event straight to `localhost`:

```bash
stripe listen \
  --forward-to http://localhost:8000/api/v1/billing/webhooks/stripe \
  --events checkout.session.completed,customer.subscription.created,customer.subscription.updated,customer.subscription.deleted,invoice.paid,invoice.payment_failed
```

On first run the CLI prints a signing secret (`whsec_...`) to the terminal — paste that into `STRIPE_WEBHOOK_SECRET`. Keep `stripe listen` running in a separate shell while you exercise the flow; stop it when you're done (the ephemeral endpoint disappears automatically).

If you skip `--events`, the CLI forwards every test-mode event and our handler logs-and-ignores the ones it doesn't care about — functionally the same, just noisier.

#### Prod (or any persistent staging / test endpoint)

Create a webhook endpoint in the Dashboard → **Developers → Webhooks → Add endpoint**:

- **URL:** `https://<your-api-host>/api/v1/billing/webhooks/stripe`
- **Events to subscribe to:** exactly these six
  - `checkout.session.completed`
  - `customer.subscription.created`
  - `customer.subscription.updated`
  - `customer.subscription.deleted`
  - `invoice.paid`
  - `invoice.payment_failed`

After saving, copy the signing secret (`whsec_...`) shown on the endpoint's page into `STRIPE_WEBHOOK_SECRET`. This secret is stable across restarts; rotate via the Dashboard if it leaks.

### 3. Configure the Customer Portal

In the Dashboard → **Settings → Billing → Customer portal**, enable:

- **Cancel subscription** — customer-initiated cancellation
- **Switch plan** — allow switching between all four of the prices you created above
- **Update payment method** — card on file
- **Invoice history** — lets customers download PDFs

Set the **default return URL** to `${APP_URL}/dashboard/settings/subscriptions` (Portal sessions fall back to this when our code doesn't pass an explicit `return_url`; we do pass one per request from `billing_portal_return_url`, so this is belt-and-suspenders).

### 4. Fill in the env

Add to `.env` (see `.env.example` for the full block):

```bash
APP_URL=http://localhost:4000
STRIPE_API_KEY=sk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_PRICE_PRO_MONTHLY=price_...
STRIPE_PRICE_PRO_YEARLY=price_...
STRIPE_PRICE_ENTERPRISE_MONTHLY=price_...
STRIPE_PRICE_ENTERPRISE_YEARLY=price_...
STRIPE_TRIAL_PERIOD_DAYS=7
```

### 5. Verify end-to-end

With the server running (`uv run uvicorn shared.main:app --reload --port 8000`) and `stripe listen` forwarding locally:

1. Register a fresh admin account (`POST /api/v1/admin/auth/register`) — verify a `freemium` row appears in the `subscriptions` table.
2. Hit `POST /api/v1/admin/billing/checkout` with `{"plan": "pro", "cadence": "monthly"}` — follow the returned URL and pay with test card `4242 4242 4242 4242`, any future expiry, any CVC.
3. After checkout, the webhook should flip the row to `status=trialing, plan=pro, type=stripe` and populate `stripe_customer_id` + `stripe_subscription_id`.
4. Hit `POST /api/v1/admin/billing/portal` — the returned URL opens the Customer Portal for that customer.

Prod checklist: switch to live-mode keys, create products + prices in live mode, register the webhook at the prod URL (Dashboard, not CLI), and confirm the signing secret matches `STRIPE_WEBHOOK_SECRET`.

### 6. Dev helpers — replay events and simulate time

#### Resend a specific event

If a webhook failed (bad handler, bad DB state, anything), Stripe keeps the event for 30 days and you can replay it:

```bash
stripe events list --limit 10                # find the evt_... id
stripe events resend evt_1abcXYZ123          # replays through `stripe listen` → your backend
```

`resend` defaults to test mode. Use `--live` if you ever need to resend a live event (rare).

#### Fabricate a synthetic event

Quick smoke-test of the webhook plumbing without completing a full checkout:

```bash
stripe trigger customer.subscription.created
```

Caveat: the synthetic customer doesn't match any `stripe_customer_id` in our DB, so `HandleStripeWebhookEvent._on_subscription_upsert` logs `stripe_webhook.subscription_no_local_row` and exits early. Signature verification + routing are exercised; business logic isn't. For real end-to-end use the checkout flow in step 5.

#### Simulate time passing — Stripe Test Clocks

[Test Clocks](https://stripe.com/docs/billing/testing/test-clocks) let you fast-forward a simulated clock so billing events (trial ending, renewals, dunning) fire in seconds instead of days. Test mode only; clocks don't exist in live.

**Important gotcha:** a clock must be attached **at customer-creation time**. Our `StartCheckoutSession` creates customers without clocks, so the subscription created by our real app flow can't be advanced on a clock after the fact. Use clocks against **a separate, CLI-created customer** to learn or demo the event sequence; keep real end-to-end verification on the `4242` card flow.

```bash
# 1. Create a clock frozen at "now". Note the clock_test_... id.
CLOCK=$(stripe test_helpers test_clocks create \
  --frozen-time $(date +%s) \
  --name "trial-conversion-sim" \
  | grep '"id":' | head -1 | awk -F'"' '{print $4}')

# 2. Create a customer attached to that clock, with a default test card.
CUSTOMER=$(stripe customers create \
  --email="sim@test.local" \
  --test-clock="$CLOCK" \
  | grep '"id":' | head -1 | awk -F'"' '{print $4}')
stripe payment_methods attach pm_card_visa --customer="$CUSTOMER"
stripe customers update "$CUSTOMER" \
  -d "invoice_settings[default_payment_method]=pm_card_visa"

# 3. Create a subscription with a 7-day trial on one of our Pro prices.
stripe subscriptions create \
  --customer="$CUSTOMER" \
  -d "items[0][price]=$STRIPE_PRICE_PRO_MONTHLY" \
  --trial-period-days=7
# → `customer.subscription.created` fires (status=trialing)

# 4. Advance 8 days — past the trial end.
stripe test_helpers test_clocks advance "$CLOCK" \
  --frozen-time $(($(date +%s) + 8*86400))
# → customer.subscription.updated (trialing → active)
# → invoice.created → invoice.finalized → invoice.paid

# 5. Advance another 30 days — next billing cycle renews.
stripe test_helpers test_clocks advance "$CLOCK" \
  --frozen-time $(($(date +%s) + 38*86400))
# → invoice.created → invoice.paid (renewal)

# Cleanup when done.
stripe test_helpers test_clocks delete "$CLOCK"
```

Advances are async. The clock transitions `ready → advancing → ready`; events fire during the `advancing` window. Poll with `stripe test_helpers test_clocks retrieve "$CLOCK"` if you need to wait for the transition to complete before the next step.

**Simulating payment failure** — replace the payment method in step 2:

```bash
stripe payment_methods attach pm_card_chargeCustomerFail --customer="$CUSTOMER"
stripe customers update "$CUSTOMER" \
  -d "invoice_settings[default_payment_method]=pm_card_chargeCustomerFail"
```

Then advance past the trial → `invoice.payment_failed` fires → `HandleStripeWebhookEvent._on_invoice_payment_failed` flips `status=past_due` (only if the customer's `stripe_customer_id` matches a local row — see the gotcha above).

Useful references:

- [`stripe test_helpers test_clocks list`](https://stripe.com/docs/api/test_clocks/list) — see active clocks
- Stripe [test-mode card numbers](https://stripe.com/docs/testing) — `4242` (success), `chargeCustomerFail` (always declines), others for 3DS / insufficient funds / specific errors

**Shortcut script:** the raw CLI commands above are wrapped in `scripts/stripe-clock.sh` for everyday use:

```bash
scripts/stripe-clock.sh setup alice@test.local $STRIPE_PRICE_PRO_MONTHLY 7
# → creates clock + customer + card + trialing subscription in one shot

scripts/stripe-clock.sh status clock_test_xxx        # show current state
scripts/stripe-clock.sh end-trial clock_test_xxx     # jump past trial_end + 60s
scripts/stripe-clock.sh renew clock_test_xxx         # +30d (next billing cycle)
scripts/stripe-clock.sh advance clock_test_xxx +12h  # +Nd / +Nh / +Nm / unix_ts
scripts/stripe-clock.sh list                         # all clocks in the account
scripts/stripe-clock.sh cleanup clock_test_xxx       # delete clock + attached objects
```

Every mutating subcommand polls the clock until it transitions back to `ready` and prints the event types that fired, so you can eyeball whether your backend got the expected webhooks.

**Hijacking an existing app user with a clock:**

Clocks must be attached at customer-creation time, so the customers our real `/upgrade` flow creates can never be time-advanced directly. To exercise `HandleStripeWebhookEvent` against real local data, create a clock-attached Stripe customer/subscription and then point a local admin's `subscriptions` row at it:

```bash
# 1. Register a fresh test admin in the app (normal signup flow).
# 2. Create the clock setup (new Stripe customer, new subscription with trial).
scripts/stripe-clock.sh setup alice@test.local "$STRIPE_PRICE_PRO_MONTHLY" 7
# → prints clock=..., customer=..., subscription=sub_test_CLOCK

# 3. Hijack — patches alice@test.local's local subscription row to point
#    at the clock's customer/subscription. Needs DATABASE_URL exported.
set -a; source .env; set +a
scripts/stripe-clock.sh hijack sub_test_CLOCK alice@test.local

# 4. Advance — webhooks from the clock now match alice's local row.
scripts/stripe-clock.sh end-trial clock_test_xxx

# 5. Observe — backend logs show the webhook processing, DB row flips.

# 6. Rollback — restores alice's row to freemium/active/manual.
scripts/stripe-clock.sh hijack-rollback alice@test.local
scripts/stripe-clock.sh cleanup clock_test_xxx
```

`hijack` resolves the target org by walking `users.email → memberships.user_id → subscriptions.organization_id`, so the admin must already be registered. If the UPDATE affects 0 rows the script prints a diagnostic SELECT you can run to list known admins.

Requires `psql` on `$PATH` and `DATABASE_URL` exported (source your `.env` with `set -a; source .env; set +a`). The SQL goes directly to the database — PostgREST is bypassed for this dev-only operation.

## Contract Intelligence

Ingests existing lease and sale contracts, extracts their structure via Reducto OCR, classifies each section with an LLM, and produces versioned templates that can be filled from CRM records to generate new contracts.

### Domain Workflow

1. **Upload** — a source contract (PDF or DOCX) is uploaded to S3. An ingestion event is published to SQS.
2. **Parse** — the ingestion worker calls Reducto to OCR and split the document into sections (chunks with titles, page ranges, and text content).
3. **Analyze** — on successful parsing, an analysis event is published. The analysis worker classifies each section (static / parameterized / conditional / generative), assigns a risk level, recommends a rendering strategy, and maps field + condition references.
4. **Review** — a human inspects, accepts, corrects, or rejects each section and analysis result.
5. **Template** — the approved results are compiled into a versioned template with Jinja render slots, field bindings, conditions, and party slots.
6. **Generate** — a template version is combined with CRM data to render a contract and produce a downloadable PDF.

### Ingestion Pipeline

```
Upload (POST /api/v1/admin/contracts/source-documents)
  → Read bytes, compute SHA-256 hash (dedup check)
  → Store PDF in S3
  → Create SourceDocument (status=uploaded)
  → Publish to SQS ingestion queue
          ↓
Ingestion Worker (polls SQS)
  → Fetch document from DB
  → Dev: download from LocalStack S3, upload to Reducto
  → Prod: generate S3 presigned URL for Reducto
  → Call Reducto Parse (OCR + layout analysis)
  → Create SourceParseRun (status=succeeded)
  → Create SourceSection rows (from parsed chunks)
  → Update document (status=parsed)
  → Publish to SQS analysis queue
          ↓
Analysis Worker (polls SQS)
  → Load document + sections from DB
  → Call LLM with structured output schema
  → Classify each section (type, risk, strategy)
  → Map field & condition references
  → Create SourceSectionAnalysis + references
  → Update document (status=analyzed)
```

### Status Transitions

```
SourceDocument:  UPLOADED → PARSED → ANALYZED  (or FAILED at any step)
Parse/Analysis:  PENDING → RUNNING → SUCCEEDED | FAILED
Review:          PENDING → ACCEPTED | CORRECTED | REJECTED
Template:        DRAFT ↔ REVIEW → APPROVED → DEPRECATED → ARCHIVED
Generated:       DRAFT → GENERATED → REVIEWED → SIGNED → ARCHIVED
```

### Re-queue a Failed Document

If ingestion or analysis fails, the document stays in its current status (`uploaded` or `parsed`). To retry, re-send the SQS message:

```bash
# Re-queue for ingestion (document must be in "uploaded" status)
aws --endpoint-url=http://localhost:4566 sqs send-message \
  --queue-url http://localhost:4566/000000000000/contract-ingestion-queue \
  --message-body '{"document_id": "<source-document-uuid>"}'

# Re-queue for analysis (document must be in "parsed" status)
aws --endpoint-url=http://localhost:4566 sqs send-message \
  --queue-url http://localhost:4566/000000000000/contract-analysis-queue \
  --message-body '{"document_id": "<source-document-uuid>"}'
```

### Worker Resilience

Both ingestion and analysis workers extend SQS message visibility via a background **heartbeat** task while processing. This prevents re-delivery during long-running Reducto/LLM calls.

| Setting | Default | Description |
|---------|---------|-------------|
| `CONTRACT_HEARTBEAT_INTERVAL` | 60s | Seconds between visibility extensions |
| `CONTRACT_HEARTBEAT_EXTENSION` | 120s | Seconds to extend visibility by each time |

### Environment Variables

| Variable | Description |
|----------|-------------|
| `SQS_CONTRACT_INGESTION_QUEUE_URL` | SQS queue for document parsing |
| `SQS_CONTRACT_ANALYSIS_QUEUE_URL` | SQS queue for LLM section analysis |
| `SQS_CONTRACT_INGESTION_DLQ_URL` | Dead-letter queue for failed ingestion |
| `SQS_CONTRACT_ANALYSIS_DLQ_URL` | Dead-letter queue for failed analysis |
| `CONTRACT_S3_BUCKET_NAME` | S3 bucket for contract documents (default: `contract-intelligence-documents`) |
| `REDUCTO_API_KEY` | Reducto API key for OCR |
| `OPENAI_API_KEY` | OpenAI API key for LLM section analysis |

### Database Tables

All 18 tables are prefixed with `contract_`:

**Source document aggregate:** `contract_source_documents`, `contract_source_parse_runs`, `contract_source_sections`, `contract_source_extraction_runs`, `contract_source_field_evidence`, `contract_source_section_analysis_runs`, `contract_source_section_analyses`, `contract_source_section_analysis_references`

**Template aggregate:** `contract_templates`, `contract_template_versions`, `contract_template_sections`, `contract_template_field_bindings`, `contract_template_conditions`, `contract_template_party_slots`

**Generated contract aggregate:** `contract_generated_contracts`, `contract_generated_contract_parties`, `contract_generated_contract_sections`, `contract_generated_contract_artifacts`

## Linting

```bash
uv run ruff check .
uv run ruff format .
```
