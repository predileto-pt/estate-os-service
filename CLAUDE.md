# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
uv sync --extra dev

# Run the server
uv run uvicorn customer_management.main:app --reload --port 8000

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

- **Domain** (`src/customer_management/domain/`) — Pure business logic with no external dependencies. Contains entities (User, Company, Subscription, Notification), value objects (PhoneNumber, Address as frozen dataclasses), domain events, and domain exceptions.
- **Application** (`src/customer_management/application/`) — Orchestration layer. **Ports** define abstract interfaces (repository ABCs, EmailService, EventBus). **Use cases** are individual classes with an async `execute()` method that combine ports to implement business operations.
- **Adapters** (`src/customer_management/adapters/`) — Concrete implementations. Inbound: FastAPI routes and middleware. Outbound: Supabase repositories, Resend email service, SQS event bus. Test doubles: in-memory implementations in `adapters/inmemory/`. Schema source of truth: SQLAlchemy models in `adapters/database/models.py`.

## Dependency Injection

`container.py` wires all use cases with their dependencies. The container is attached to `app.state.container` via the app factory in `main.py`. Routes access use cases through `request.app.state.container.<use_case_name>`.

For tests, `conftest.py` builds a container using in-memory adapters — no external services needed.

## Auth Flow

JWT-based via Supabase. `JWTAuthMiddleware` extracts the `sub` claim (Supabase user ID) from the Bearer token and stores it in `request.state.supabase_user_id`. Public endpoints (`/health`, `/subscriptions/plans`, docs) skip auth.

## Key Conventions

- **Async everywhere**: all repositories, services, use cases, and route handlers are async.
- **Ruff**: linter and formatter, 100-char line length, Python 3.13 target.
- **pytest-asyncio**: `asyncio_mode = "auto"` — async tests don't need the `@pytest.mark.asyncio` decorator.
- **Domain exceptions** raised by use cases are caught in routes and mapped to HTTP status codes.
- **Route response mapping**: helper functions in route files (e.g., `_user_response()`) convert domain models to Pydantic response dicts.

## Database

Supabase (PostgreSQL) with schema managed by SQLAlchemy + Alembic. Models in `src/customer_management/adapters/database/models.py` are the schema source of truth. Migrations in `alembic/versions/`. Tables: applicants, companies, users, subscriptions, notifications. Row-level security and triggers are managed via raw SQL in migrations.
