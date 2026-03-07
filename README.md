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

Schema is defined in SQLAlchemy models at `src/core_api/adapters/database/models.py`.

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
uv run uvicorn core_api.main:app --reload --port 8000
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
src/core_api/
├── domain/           # Entities, value objects, events, exceptions (no dependencies)
├── application/
│   ├── ports/        # Abstract interfaces (repository ABCs, services)
│   └── use_cases/    # Business logic orchestration
├── adapters/
│   ├── api/          # Inbound: FastAPI routes, schemas, middleware
│   ├── database/     # SQLAlchemy models and async engine (schema source of truth)
│   ├── persistence/  # Outbound: Supabase repository implementations
│   ├── email/        # Outbound: Resend email service
│   ├── queue/        # Outbound: SQS event bus
│   └── inmemory/     # Test doubles for all ports
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

## Linting

```bash
uv run ruff check .
uv run ruff format .
```
