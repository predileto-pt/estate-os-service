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
| `SQS_QUEUE_URL` | SQS queue URL for domain events |
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

Schema is defined in SQLAlchemy models at `src/customer_management/adapters/database/models.py` and `src/property_management/adapters/database/models.py`.

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
uv run uvicorn customer_management.main:app --reload --port 8000
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

### Subscriptions

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/subscriptions/current` | Get current company subscription |
| `POST` | `/subscriptions` | Create subscription |
| `PATCH` | `/subscriptions/{id}` | Update subscription metadata |

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

## Architecture

```
src/customer_management/
├── domain/           # Entities, value objects, events, exceptions (no dependencies)
├── application/
│   ├── ports/        # Abstract interfaces (repository ABCs, services)
│   └── use_cases/    # Business logic orchestration
├── adapters/
│   ├── api/          # Inbound: FastAPI routes, schemas, middleware
│   ├── database/     # SQLAlchemy models and async engine (schema source of truth)
│   ├── persistence/  # Outbound: Supabase repository implementations
│   ├── email/        # Outbound: Resend email service
│   ├── queue/        # Outbound: SQS event bus + consumer
│   ├── workers/      # SQS polling workers (local dev) + event processor
│   └── inmemory/     # Test doubles for all ports
├── entrypoints/
│   ├── bootstrap.py  # DI wiring for workers/lambdas (Supabase client + repos)
│   ├── lambda_events.py  # AWS Lambda handler for SQS events
│   └── worker.py     # CLI entrypoint: python -m customer_management.entrypoints.worker
├── config.py         # Pydantic Settings + structlog setup
├── container.py      # Dependency injection wiring
└── main.py           # FastAPI app factory
```

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

## Running the Intake Form Flow Locally

The intake form flow spans three services. When an applicant submits the form, the screening service processes their documents and publishes an `APPLICANT_SCREENED` event to SQS. The core-api events worker consumes that event and creates an applicant row that the agencies-dashboard reads.

```
agencies-dashboard          applicants-screening-service         core-api
      │                              │                              │
      │  create intake form request  │                              │
      ├──────────────────────────────┼──────────────────────────────►│ (Supabase)
      │                              │                              │
      │  applicant submits form      │                              │
      ├─────────────────────────────►│                              │
      │                              │ screen & publish event       │
      │                              ├──────── SQS ────────────────►│
      │                              │   APPLICANT_SCREENED         │ events worker
      │                              │                              │ creates applicant
      │  dashboard reads applicants  │                              │
      ├──────────────────────────────┼──────────────────────────────►│ (Supabase)
```

### Prerequisites

- [uv](https://docs.astral.sh/uv/) (Python)
- [Node.js 22](https://nodejs.org/) (frontend)
- [Docker](https://www.docker.com/) (LocalStack + Postgres)
- Supabase project (local via `supabase start` or hosted)

### 1. Start infrastructure

Each service has its own `docker-compose.yml`. Start both:

```bash
# Terminal 1 — screening service infra (Postgres + LocalStack with S3/SQS queues)
cd applicants-screening-service
docker compose up -d

# Terminal 2 — core-api infra (LocalStack with SQS queues)
cd core-api
docker compose up -d
```

The screening service LocalStack creates: `document-extraction-queue`, `screening-assessment-queue`, `screening-events-queue`.
The core-api LocalStack creates: `core-api-events`, `screening-events-queue`.

> **Note:** If running both on the same machine, they share port 4566. Either run only the screening service's docker-compose (it creates all needed queues), or change the core-api LocalStack to a different port.
>
> Simplest approach — use a single LocalStack instance. Start only the screening service's docker-compose, then create the extra core-api queue manually:
>
> ```bash
> cd applicants-screening-service
> docker compose up -d
> aws --endpoint-url=http://localhost:4566 sqs create-queue --queue-name core-api-events
> ```

### 2. Configure environment

```bash
# Screening service
cd applicants-screening-service
cp .env.example .env
# Edit .env — set DATABASE_URL, OPENAI_API_KEY, REDUCTO_API_KEY, encryption keys

# Core API
cd core-api
cp .env.example .env
# Edit .env — set SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, SUPABASE_JWT_SECRET
```

Key env vars for the events flow:

| Service | Variable | Value |
|---------|----------|-------|
| screening | `SQS_EVENTS_QUEUE_URL` | `http://localhost:4566/000000000000/screening-events-queue` |
| core-api | `SQS_EVENTS_QUEUE_URL` | `http://localhost:4566/000000000000/screening-events-queue` |
| both | `AWS_ENDPOINT_URL` | `http://localhost:4566` |
| both | `AWS_ACCESS_KEY_ID` | `test` |
| both | `AWS_SECRET_ACCESS_KEY` | `test` |

Both services must point `SQS_EVENTS_QUEUE_URL` to the **same queue** so the screening service publishes and core-api consumes from it.

### 3. Run database migrations

```bash
# Screening service (local Postgres from docker-compose)
cd applicants-screening-service
uv run alembic upgrade head

# Core API (Supabase Postgres)
cd core-api
uv run alembic upgrade head
```

### 4. Start all services

You need five processes. Use separate terminals or a process manager like [overmind](https://github.com/DarthSim/overmind)/[foreman](https://github.com/ddollar/foreman):

```bash
# Terminal 1 — Screening API (receives form submissions)
cd applicants-screening-service
uv run uvicorn applicant_screening.entrypoints.api:create_app --factory --reload --port 8001

# Terminal 2 — Screening extraction worker
cd applicants-screening-service
uv run python -m applicant_screening.entrypoints.worker --queue extraction

# Terminal 3 — Screening assessment worker
cd applicants-screening-service
uv run python -m applicant_screening.entrypoints.worker --queue screening

# Terminal 4 — Core API server
cd core-api
uv run uvicorn customer_management.main:app --reload --port 8000

# Terminal 5 — Core API events worker (consumes APPLICANT_SCREENED)
cd core-api
uv run python -m customer_management.entrypoints.worker --queue events

# Terminal 6 — Agencies dashboard
cd agencies-dashboard
npm run dev

# Terminal 7 — Applicant intake form (Vite)
cd applicants-intake-form
npm run dev
```

### 5. End-to-end test

1. Open the agencies dashboard at `http://localhost:4000`
2. Navigate to **Intake Forms** and create a new request (fill in applicant name, email, property ID)
3. Open the link sent to the applicant (or go to `http://localhost:5173/<form-request-id>`)
4. Submit the intake form with documents
5. Watch the screening workers process the documents (extraction → screening)
6. The core-api events worker picks up the `APPLICANT_SCREENED` event and creates an applicant row
7. Refresh the dashboard — the new applicant appears in the **Applicants** list

### Manually publishing a test event

To test the core-api events worker without running the full screening pipeline:

```bash
aws --endpoint-url=http://localhost:4566 sqs send-message \
  --queue-url http://localhost:4566/000000000000/screening-events-queue \
  --message-body '{
    "event_type": "APPLICANT_SCREENED",
    "applicant_id": "00000000-0000-0000-0000-000000000001",
    "form_request_id": "<a-real-intake-form-request-id>",
    "owner_id": "<agency-user-uuid>",
    "name": "João Silva",
    "email": "joao@example.com",
    "date_of_birth": "1990-05-15",
    "property_type": "RENTAL",
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
    "screened_at": "2026-03-08T12:00:00Z"
  }'
```

Replace `form_request_id` and `owner_id` with real UUIDs from your Supabase `intake_form_requests` table. The events worker will log `screening_result_processed` and the applicant row will appear in the `applicants` table.

## Property Extraction Worker

The property extraction worker processes document extraction jobs from SQS.

### Running the worker

```bash
uv run python -m property_management.entrypoints.worker --queue extraction
```

### Retrying a failed extraction job

If an extraction job fails (e.g. due to a transient error), you can retry it via CLI or API.

**CLI:**

```bash
uv run python -m property_management.entrypoints.worker --retry-job <job_id>
```

This marks the job as `retrying`, re-publishes the extraction event to SQS, and exits. The running worker will then pick up and reprocess the job.

**API:**

```bash
curl -X POST http://localhost:8000/api/v1/extraction-jobs/<job_id>/retry \
  -H "Authorization: Bearer <token>"
```

Only jobs with `failed` status can be retried.

## Linting

```bash
uv run ruff check .
uv run ruff format .
```
