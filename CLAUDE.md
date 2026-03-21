# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
uv sync --extra dev

# Run the server
uv run uvicorn shared.main:app --reload --port 8000

# Run all tests
uv run pytest -v

# Run a single test file
uv run pytest tests/unit/test_domain_models.py -v

# Run a single test by name
uv run pytest -k "test_name" -v

# Lint and format
uv run ruff check .
uv run ruff format .

# Database migrations (Alembic)
uv run alembic upgrade head           # apply all migrations
uv run alembic revision --autogenerate -m "description"  # generate from model diff
uv run alembic current                # check current revision
uv run alembic downgrade -1           # rollback one migration
uv run alembic stamp head             # mark DB as up-to-date without DDL

# Start LocalStack (SQS/S3)
docker compose up -d
```

## Architecture

Hexagonal (ports & adapters) architecture with three layers:

- **Domain** (`domain/`) — Pure business logic with no external dependencies. Contains entities, value objects (frozen dataclasses), domain events, and domain exceptions.
- **Application** (`application/`) — Orchestration layer. **Ports** define abstract interfaces (repository ABCs, service protocols). **Use cases** are individual classes with an async `execute()` method.
- **Adapters** (`adapters/`) — Concrete implementations. Inbound: FastAPI routes and middleware. Outbound: Supabase repositories, Resend email, SQS event bus, OpenAI document extraction. Test doubles: in-memory implementations in `adapters/inmemory/`.

## Shared Infrastructure

Shared infrastructure lives in `src/shared/` — config, middleware, database Base, app factory, bootstrap, and Lambda handler. Both bounded contexts import from `shared/` but never from each other.

| Module | Purpose |
|--------|---------|
| `shared/config.py` | Settings, `setup_logging()` |
| `shared/main.py` | `create_app()` FastAPI factory |
| `shared/api/dependencies.py` | `get_supabase_user_id()`, `get_current_user()` |
| `shared/api/middleware.py` | JWT auth + request logging middleware |
| `shared/database/models.py` | SQLAlchemy `Base` (DeclarativeBase) |
| `shared/database/engine.py` | `build_async_engine()` |
| `shared/entrypoints/bootstrap.py` | Production container wiring |
| `shared/entrypoints/lambda_handler.py` | Mangum Lambda handler |

## Two Bounded Contexts

The service hosts two independent bounded contexts, each following the same hexagonal structure:

| Context | Package | Container | Entities |
|---------|---------|-----------|----------|
| **Customer Management** | `src/customer_management/` | `Container` on `app.state.container` | User, Company, Subscription, Notification |
| **Property Management** | `src/property_management/` | `Container` on `app.state.property_container` | Property, PropertyOwner, PropertyImage, ExtractionJob, PropertyCharacteristics, DocumentContent |

Both are wired in `shared/main.py` via `create_app(container, property_container)` and bootstrapped for production in `shared/entrypoints/bootstrap.py`. Routes access use cases through `request.app.state.container.<use_case>` or `request.app.state.property_container.<use_case>`. Neither context imports from the other.

### Property Management — Key Domain Values

- **ListingType**: `sale`, `purchase`
- **Typology**: `house`, `apartment`, `land`, `ruin`
- **PropertyStatus**: `draft`, `active`, `sold`, `rented`, `withdrawn`
- **DocumentType** (owner ID docs): `cartao_cidadao`, `passport`, `visto_residencia`, `titulo_residencia`

### Property Extraction Flow

Two async extraction flows, both following: presign → upload → submit → SQS → process.

1. **Single extraction** (`POST /api/v1/extraction-jobs`): One property document → parse with Reducto → extract property + owners from text.
2. **Batch extraction** (`POST /api/v1/extraction-jobs/batch`): 1–5 mixed documents → parse all with Reducto (single OCR pass) → persist parsed text in `document_contents` → classify from text → extract property data from property docs → extract owner data from ID docs with subtype-specific prompts → merge owners by NIF (ID extraction wins) → create Property + PropertyOwners.

All document processing follows a **parse-first** approach: documents are OCR'd once via Reducto, and all downstream steps (classification, property extraction, ID extraction) operate on the parsed text — no re-OCR or vision API calls.

`listing_type` and `typology` are **user inputs** provided at submission time, not extracted from documents. They are stored on the ExtractionJob and used when creating the Property.

### Property Image Flow

Images are managed separately from property creation, following: presign → upload → record.

1. **Presign** (`POST /api/v1/property-images/presign`): Generate presigned S3 upload URLs. S3 key: `properties/{property_id}/images/{image_id}.{ext}`.
2. **Upload**: Frontend uploads directly to S3 using presigned URLs.
3. **Record** (`POST /api/v1/property-images`): Record image metadata after upload. Verifies file exists in S3. Max 20 images per property.
4. **Reorder** (`PUT /api/v1/property-images/reorder`): Update `display_order` for all images.
5. **Delete** (`DELETE /api/v1/property-images/{image_id}`): Remove metadata only (S3 cleanup via lifecycle policy).

Images with presigned download URLs are returned inline in `PropertyResponse` (via `get_download_url` on `DocumentStorage`).

### Property Management Ports

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
| `EventBus` | SQS event publishing | `SQSEventBus` |

## Dependency Injection

Each bounded context has its own `container.py` that wires use cases with their port implementations. For tests, `conftest.py` builds both containers using in-memory adapters — no external services needed. Test HTTP client uses `httpx.AsyncClient` with `ASGITransport`.

## Auth Flow

JWT-based via Supabase. `JWTAuthMiddleware` extracts the `sub` claim (Supabase user ID) from the Bearer token and stores it in `request.state.supabase_user_id`. Public endpoints (`/health`, `/subscriptions/plans`, docs) skip auth. All routes are prefixed with `/api/v1`.

## Deployment

The app runs as an AWS Lambda behind API Gateway using Mangum (`shared/entrypoints/lambda_handler.py`), or as a standard uvicorn server for local development.

## Key Conventions

- **Async everywhere**: all repositories, services, use cases, and route handlers are async.
- **Ruff**: linter and formatter, 100-char line length, Python 3.13 target.
- **pytest-asyncio**: `asyncio_mode = "auto"` — async tests don't need the `@pytest.mark.asyncio` decorator.
- **Domain exceptions** raised by use cases are caught in routes and mapped to HTTP status codes.
- **Route response mapping**: helper functions in route files (e.g., `_user_response()`) convert domain models to Pydantic response dicts.

## Database

Supabase (PostgreSQL) with schema managed by SQLAlchemy + Alembic. Models in `adapters/database/models.py` (in each bounded context) are the schema source of truth. Migrations in `alembic/versions/`. Row-level security and triggers are managed via raw SQL in migrations.
