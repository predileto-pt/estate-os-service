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

## Bounded Contexts

| Context | Package | Container | Notes |
|---|---|---|---|
| **Identity** | `src/identity/` | `app.state.identity_container` | User aggregate only. No organization FK on `User`. |
| **Organizations** | `src/organizations/` | `app.state.organizations_container` (alias: `app.state.container`) | Organization, Membership, Invitation, Notification. Owns the `users` table read from org-side via its own `UserRepository` port (internal mirror of identity's User class). |
| **Billing** | `src/billing/` | `app.state.billing_container` | Subscription aggregate + Stripe integration (Checkout, Customer Portal, webhooks, price catalog, idempotency store). Exposes `seed_freemium_subscription_port` consumed by organizations during admin registration. |
| **Properties** | `src/properties/` | `app.state.property_container` | |
| **Screening** | `src/screening/` | `app.state.screening_container` | Applicant screening + document extraction. |
| **Bookings** | `src/bookings/` | `app.state.booking_container` | Slot + booking management. |
| **Contract Intelligence** | `src/contract_intelligence/` | `app.state.contract_intelligence_container` | |
| **Listings** | `src/listings/` | `app.state.listing_container` | Public-facing property listings. Owns the `property_listings` projection (carried-state from `PROPERTY_*.v1` events) and the semantic-search indexing pipeline (Pinecone v1, gated by `LISTINGS_EMBEDDING_ENABLED`). |

Cross-context dependency rules:

- **Organizations depends on Identity and Billing** via callable Protocols injected at container construction: `RegisterUserPort` (identity) and `SeedFreemiumSubscription` (billing). No imports of identity or billing domain classes in organizations' business code — only the Protocol types. See `docs/features/organizations.md` and `docs/features/billing.md`.
- **Identity does not import from any other context.** Enforced by `grep -rn "from organizations" src/identity/` → zero hits.
- **Billing does not import from organizations.** Enforced by `grep -rn "from organizations" src/billing/` → zero hits.
- **Every other context (properties, screening, bookings, ...)** imports `identity.User` for route type hints via `require_org_member`, and `organizations.Membership` for the same. Neither property nor other-context imports leak into identity or organizations.
- **Shared infrastructure** (`src/shared/`) — middleware, events, database engine, config — may call any bounded context's container directly. It's not a bounded context itself.

Routes access use cases through `request.app.state.<context>_container.<use_case>`. The `IdentityMiddleware` populates `request.state.user` and `request.state.memberships` (a JOIN projection including org names) before the route handler runs; downstream `require_org_member` reads these with zero DB hits.

## Key Conventions

- **Async everywhere**: all repositories, services, use cases, and route handlers are async.
- **Ruff**: linter and formatter, 100-char line length, Python 3.13 target.
- **pytest-asyncio**: `asyncio_mode = "auto"` — async tests don't need the `@pytest.mark.asyncio` decorator.
- **Domain exceptions** raised by use cases are caught in routes and mapped to HTTP status codes.
- **Route response mapping**: helper functions in route files (e.g., `_user_response()`) convert domain models to Pydantic response dicts.

## Database

Supabase (PostgreSQL) with schema managed by SQLAlchemy + Alembic. Models in `adapters/database/models.py` (in each bounded context) are the schema source of truth. Migrations in `alembic/versions/`. Row-level security and triggers are managed via raw SQL in migrations.
