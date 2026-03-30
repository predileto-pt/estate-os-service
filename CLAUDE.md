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

See [README.md](README.md) for full architecture docs including bounded contexts, domain flows, ports & adapters, and API endpoints.

Hexagonal (ports & adapters) architecture with three layers:

- **Domain** (`domain/`) — Pure business logic with no external dependencies. Contains entities, value objects (frozen dataclasses), domain events, and domain exceptions.
- **Application** (`application/`) — Orchestration layer. **Ports** define abstract interfaces (repository ABCs, service protocols). **Use cases** are individual classes with an async `execute()` method.
- **Adapters** (`adapters/`) — Concrete implementations. Inbound: FastAPI routes and middleware. Outbound: Supabase repositories, Resend email, SQS event bus, OpenAI document extraction. Test doubles: in-memory implementations in `adapters/inmemory/`.

## Two Bounded Contexts

| Context | Package | Container |
|---------|---------|-----------|
| **Customer Management** | `src/customers/` | `Container` on `app.state.container` |
| **Property Management** | `src/properties/` | `Container` on `app.state.property_container` |

Routes access use cases through `request.app.state.container.<use_case>` or `request.app.state.property_container.<use_case>`. Neither context imports from the other. Shared infrastructure lives in `src/shared/`.

## Key Conventions

- **Async everywhere**: all repositories, services, use cases, and route handlers are async.
- **Ruff**: linter and formatter, 100-char line length, Python 3.13 target.
- **pytest-asyncio**: `asyncio_mode = "auto"` — async tests don't need the `@pytest.mark.asyncio` decorator.
- **Domain exceptions** raised by use cases are caught in routes and mapped to HTTP status codes.
- **Route response mapping**: helper functions in route files (e.g., `_user_response()`) convert domain models to Pydantic response dicts.

## Database

Supabase (PostgreSQL) with schema managed by SQLAlchemy + Alembic. Models in `adapters/database/models.py` (in each bounded context) are the schema source of truth. Migrations in `alembic/versions/`. Row-level security and triggers are managed via raw SQL in migrations.
