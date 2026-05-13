# Coolify production stack — compose + nginx + Redis

**Status:** shipped
**Owner:** Peter
**Created:** 2026-05-13

## Problem

Two issues block running this service on Coolify with `deploy/docker-compose.prod.yml` as-is:

1. **The current compose is shaped for EC2 + Lambda.** Workers sit behind `profiles: ["fallback"]`; only `api` runs by default. Coolify ingests compose directly and runs every declared service as long-running.
2. **`env_file: .env` is the only env source.** On EC2 the file is built at user-data boot from Secrets Manager. Coolify injects env vars per-service from its UI; there is no `.env` file on disk for the container to read.

We also consolidate the runtime stack while we're at it:

- **Nginx** in front of api for HTTP reverse-proxy + forwarded-headers + request shaping. Api stops binding host ports.
- **Redis** for the ADR-016 listings page cache, which has been dark in prod because no Redis was wired.
- **RabbitMQ** as the event-bus transport. Adapters + bootstrap swap land in `2026-05-rabbitmq-transport-adapter`; this spec just runs `rabbitmq` as a service and points the prod compose at it (no flag — `bootstrap.py` constructs RabbitMQ publishers when given an `amqp_connection`).

S3 stays the file store. SNS+SQS adapter code, Lambda entrypoints, and AWS Terraform stay in place — none of them is exercised once the prod compose flips backend.

## Dependency

Depends on **`2026-05-rabbitmq-transport-adapter`** being shipped first. That spec lands the adapters, the bootstrap switch, the dev compose RabbitMQ service, and the ADR-008 addendum. **This spec is a pure ops change once that's in.**

## Prerequisites confirmed

The api-side AMQP connection wiring is already in place from the hotfix commit on top of the RabbitMQ migration: `shared/main.py:lifespan` opens one `aio_pika.connect_robust(settings.rabbitmq_url, heartbeat=30)` on startup and threads it into `get_property_container() / get_screening_container() / get_contract_intelligence_container()`. The 6 command-queue settings (`property_extraction_queue` etc.) are transport-neutral Settings fields. This spec doesn't re-do that wiring — only the compose layout, nginx reverse-proxy, Redis service, and docs.

## Goal

A Coolify-ready production stack in `deploy/docker-compose.prod.yml`: **nginx + api + three always-on workers + rabbitmq + redis**. Every env var referenced by name; shared image + env baseline come from `x-base-service` + `x-shared-env` top-level anchors. api uses RabbitMQ for events + commands, S3 for files, Redis for cache; nginx terminates external HTTP and proxies to api.

## Non-goals

- **The RabbitMQ adapters themselves.** Handled by `2026-05-rabbitmq-transport-adapter`.
- **Removing SNS / SQS / Lambda / EC2 code.** Adapters, entrypoints, IAM, Terraform stay. `bootstrap.py` constructs RabbitMQ publishers when callers pass an `amqp_connection`; SNS+SQS adapter classes are dormant unless a Lambda entrypoint calls `get_*_container()` with no connection (the retained fallback path).
- **Migrating S3.** Stays the file store; containers need `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY` for it.
- **RabbitMQ clustering / HA.** Single-node container, persistent volume.
- **Cutover of in-flight messages.** Coolify cutover happens with SNS/SQS drained.
- **TLS termination on nginx.** Coolify (or upstream LB) handles TLS; nginx speaks plain HTTP between containers.
- **Stripe / Supabase URL changes** once the production hostname moves to Coolify. Captured as a follow-up.
- **Pruning EC2 / Lambda Terraform.** Kept for emergency revert.
- **Coolify operator runbook.** Captured for first-deploy follow-up.

## Approach

### 1. Compose layout

Seven services in `deploy/docker-compose.prod.yml`:

```yaml
x-base-service: &base-service
  image: ${ECR_IMAGE}
  restart: unless-stopped

x-shared-env: &shared-env
  # Supabase admin
  SUPABASE_URL: ${SUPABASE_URL}
  SUPABASE_SERVICE_ROLE_KEY: ${SUPABASE_SERVICE_ROLE_KEY}
  SUPABASE_JWT_SECRET: ${SUPABASE_JWT_SECRET}
  # AWS — S3 only. AWS_ENDPOINT_URL deliberately absent (LocalStack-only).
  AWS_REGION: ${AWS_REGION}
  AWS_ACCESS_KEY_ID: ${AWS_ACCESS_KEY_ID}
  AWS_SECRET_ACCESS_KEY: ${AWS_SECRET_ACCESS_KEY}
  S3_BUCKET_NAME: ${S3_BUCKET_NAME}
  # OpenAI
  OPENAI_API_KEY: ${OPENAI_API_KEY}
  # Reducto (document OCR — exercised by api + property/screening/contract
  # workers that build Reducto clients in their container construction).
  REDUCTO_API_KEY: ${REDUCTO_API_KEY}
  # Admin DB (SQLAlchemy engine — api + screening/bookings/contract/listings
  # workers all call create_async_engine(settings.database_url, ...)).
  DATABASE_URL: ${DATABASE_URL}
  # Screening encryption (RSA + HMAC). The screening worker's
  # SqlAlchemyScreeningUnitOfWork calls load_private_key_from_env() at
  # container construction — empty keys raise. Belongs in baseline so the
  # workers don't fail to start.
  ENCRYPTION_PUBLIC_KEY: ${ENCRYPTION_PUBLIC_KEY}
  ENCRYPTION_PRIVATE_KEY: ${ENCRYPTION_PRIVATE_KEY}
  ENCRYPTION_HMAC_KEY: ${ENCRYPTION_HMAC_KEY}
  # Event bus: RabbitMQ. SNS_*/SQS_* deliberately absent — bootstrap.py
  # constructs RabbitMQ publishers whenever it receives an amqp_connection;
  # SNS+SQS adapter classes are retained for the Lambda fallback path only.
  RABBITMQ_URL: amqp://${RABBITMQ_USER}:${RABBITMQ_PASSWORD}@rabbitmq:5672/
  RABBITMQ_DOMAIN_EVENTS_EXCHANGE: domain-events
  RABBITMQ_DLX: domain-events-dlx
  # Command queue names — LITERAL values (not ${...} interpolation).
  # Identical to the names worker entrypoints declare; api + workers
  # publish to them via the RabbitMQ default exchange (routing-key =
  # queue name). Without these, command publishers route to "" and the
  # broker drops every message as unroutable. Same values everywhere
  # means no operator config needed in Coolify for these six.
  PROPERTY_EXTRACTION_QUEUE: property-extraction-queue
  PROPERTY_ENRICHMENT_QUEUE: property-enrichment-queue
  APPLICANT_EXTRACTION_QUEUE: applicant-extraction-queue
  APPLICANT_SCREENING_QUEUE: applicant-screening-queue
  CONTRACT_INGESTION_QUEUE: contract-ingestion-queue
  CONTRACT_ANALYSIS_QUEUE: contract-analysis-queue
  # App + observability
  APP_ENV: ${APP_ENV}
  LOG_LEVEL: ${LOG_LEVEL}
  LOGFIRE_TOKEN: ${LOGFIRE_TOKEN}
  LANGFUSE_PUBLIC_KEY: ${LANGFUSE_PUBLIC_KEY}
  LANGFUSE_SECRET_KEY: ${LANGFUSE_SECRET_KEY}
  LANGFUSE_BASE_URL: ${LANGFUSE_BASE_URL}

services:
  nginx:
    image: nginx:1.27-alpine
    ports: ["80:80"]
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf:ro
    depends_on: [api]
    restart: unless-stopped

  api:
    <<: *base-service
    command: ["uv", "run", "uvicorn", "shared.main:app", "--host", "0.0.0.0", "--port", "8000"]
    expose: ["8000"]              # internal-only; nginx fronts it
    environment:
      <<: *shared-env
      # Stripe
      STRIPE_API_KEY: ${STRIPE_API_KEY}
      STRIPE_WEBHOOK_SECRET: ${STRIPE_WEBHOOK_SECRET}
      STRIPE_PRICE_PRO_MONTHLY: ${STRIPE_PRICE_PRO_MONTHLY}
      STRIPE_PRICE_PRO_YEARLY: ${STRIPE_PRICE_PRO_YEARLY}
      STRIPE_PRICE_ENTERPRISE_MONTHLY: ${STRIPE_PRICE_ENTERPRISE_MONTHLY}
      STRIPE_PRICE_ENTERPRISE_YEARLY: ${STRIPE_PRICE_ENTERPRISE_YEARLY}
      # Portal Supabase + portal DB + session signing
      SUPABASE_PORTAL_URL: ${SUPABASE_PORTAL_URL}
      SUPABASE_PORTAL_JWT_SECRET: ${SUPABASE_PORTAL_JWT_SECRET}
      PORTAL_DATABASE_URL: ${PORTAL_DATABASE_URL}
      SESSION_SIGNING_KEYS: ${SESSION_SIGNING_KEYS}
      SESSION_SIGNING_ACTIVE_KEY: ${SESSION_SIGNING_ACTIVE_KEY}
      SESSION_COOKIE_DOMAIN: ${SESSION_COOKIE_DOMAIN}
      # Cache + listings flags
      REDIS_URL: redis://redis:6379/0
      LISTINGS_PAGE_CACHE_ENABLED: "true"
      LISTINGS_SEARCH_ENABLED: ${LISTINGS_SEARCH_ENABLED}
      # Misc api-only
      CORS_ORIGINS: ${CORS_ORIGINS}
      APP_URL: ${APP_URL}
      # Resend (transactional email — used by api invitation flow and
      # by the organizations worker's handle_applicant_screened via its
      # `customer` context dict).
      RESEND_API_KEY: ${RESEND_API_KEY}
    depends_on: [rabbitmq, redis]
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/api/v1/health"]
      interval: 30s

  extraction-worker:
    <<: *base-service
    command: ["uv", "run", "python", "-m", "properties.entrypoints.worker", "--queue", "extraction"]
    environment: {<<: *shared-env}
    depends_on: [rabbitmq]

  enrichment-worker:
    <<: *base-service
    command: ["uv", "run", "python", "-m", "properties.entrypoints.worker", "--queue", "enrichment"]
    environment:
      <<: *shared-env
      GOOGLE_MAPS_API_KEY: ${GOOGLE_MAPS_API_KEY}
    depends_on: [rabbitmq]

  listings-events-worker:
    <<: *base-service
    command: ["uv", "run", "python", "-m", "listings.entrypoints.events_worker"]
    environment:
      <<: *shared-env
      LISTINGS_EMBEDDING_ENABLED: "true"
      PINECONE_API_KEY: ${PINECONE_API_KEY}
      PINECONE_HOST: ${PINECONE_HOST}
      PINECONE_INDEX: ${PINECONE_INDEX}
      EMBEDDING_MODEL: ${EMBEDDING_MODEL}
      EMBEDDING_DIMENSIONS: ${EMBEDDING_DIMENSIONS}
      VECTOR_INDEX_NAMESPACE: ${VECTOR_INDEX_NAMESPACE}
    depends_on: [rabbitmq]

  rabbitmq:
    image: rabbitmq:3.13-management-alpine
    environment:
      RABBITMQ_DEFAULT_USER: ${RABBITMQ_USER}
      RABBITMQ_DEFAULT_PASS: ${RABBITMQ_PASSWORD}
    volumes: ["rabbitmq-data:/var/lib/rabbitmq"]
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "rabbitmq-diagnostics", "ping"]
      interval: 30s

  redis:
    image: redis:7-alpine
    command: ["redis-server", "--save", "60", "1", "--appendonly", "yes"]
    volumes: ["redis-data:/data"]
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 30s

volumes:
  rabbitmq-data:
  redis-data:
```

Notes:
- **Nginx is the only port-bound service** (`80:80`). `api` uses `expose:`, not `ports:` — internal-only.
- **RabbitMQ management UI (15672) is NOT exposed externally** — operators tunnel via the Coolify host.
- **Volumes are host-persistent** (`rabbitmq-data`, `redis-data`); backups are operator-side.
- **`AWS_ENDPOINT_URL` deliberately absent** (LocalStack-only).
- **`SNS_*` / `SQS_*` deliberately absent** — `bootstrap.py` constructs RabbitMQ publishers whenever an `amqp_connection` is passed in (no runtime flag). SNS+SQS adapter classes are retained for the Lambda fallback path, but Lambda is dormant on Coolify and no env var feeds them here.

### 2. Shared resource (anchors)

Top-level `x-base-service` declares `image:` + `restart:`. Top-level `x-shared-env` declares the env baseline every Python service exercises. The four Python services (api + 3 workers) merge both via `<<: *…`. Nginx / rabbitmq / redis have distinct images and don't share the anchor.

**Mechanism committed up-front:** YAML merge keys (`<<:`). YAML 1.2 dropped the merge key from the core spec, but recent docker-compose (and Coolify's parser, which uses the same compose-go library) honors it. Named fallback if the smoke test fails: `extends:` — more verbose, compose-spec-guaranteed. Decision made here so implementation doesn't pivot mid-flight.

**Three buckets, framed by what each runtime exercises** (not by what `shared.config` reads on import — `src/shared/config.py:219-225` defaults every field and sets `extra: "ignore"`, so import never fails on missing env; the worker WILL boot regardless. The cutoff is exercise-based):

- **baseline** (`x-shared-env`): Supabase admin, AWS region + creds + S3 bucket, OpenAI, **Reducto API key, `DATABASE_URL`, encryption keys (`ENCRYPTION_*`), the 6 command-queue name literals (`PROPERTY_EXTRACTION_QUEUE` etc.) so any service that publishes commands can route correctly**, RabbitMQ connection + exchange + DLX, `APP_ENV`, `LOG_LEVEL`, Logfire, Langfuse. Every Python service exercises one or more of these at container-construction time — the SQLAlchemy engine builders in `get_screening_container` / `get_booking_container` / `get_contract_intelligence_container` / `get_listing_container` need `DATABASE_URL`; `get_screening_container` calls `load_private_key_from_env(settings.encryption_private_key)` and crashes on empty input; the property + screening + contract containers all construct Reducto clients; and any container that holds a `CommandPublisher` needs its destination queue names bound at construction (otherwise `command_publisher.send("", event)` is unroutable).
- **api-only**: Stripe block, portal Supabase + portal DB + session signing, `REDIS_URL`, `LISTINGS_PAGE_CACHE_ENABLED`, `LISTINGS_SEARCH_ENABLED`, `CORS_ORIGINS`, `RESEND_API_KEY`, `APP_URL`. Exercised only by HTTP routes (or by the organizations worker via the `customer` context, which still constructs the organizations container — so `RESEND_API_KEY` would be needed there too if it actually used the email service in a handler; today it doesn't, so api-only is correct).
- **per-worker**: `extraction-worker` adds nothing beyond baseline. `enrichment-worker` adds `GOOGLE_MAPS_API_KEY` (POI discovery). `listings-events-worker` adds Pinecone + embedding vars (`PINECONE_*`, `EMBEDDING_*`, `VECTOR_INDEX_*`, `LISTINGS_EMBEDDING_ENABLED`) gated by the embedding flag.

### 3. Nginx config

`deploy/nginx/nginx.conf` — single `server` block:

- `listen 80;`
- `proxy_pass http://api:8000;`
- Standard forwarded headers (`Host`, `X-Real-IP`, `X-Forwarded-For`, `X-Forwarded-Proto`)
- `proxy_read_timeout 60s` (survive LLM-bound requests)
- `client_max_body_size 20m` (document uploads)
- `gzip on` for text + JSON

No TLS — Coolify (or upstream LB) handles it.

### 4. Redis wiring

api's environment sets `REDIS_URL=redis://redis:6379/0` and `LISTINGS_PAGE_CACHE_ENABLED=true`. ADR-016's page cache lights up for the first time in prod. Workers do NOT get `REDIS_URL` — they don't touch the page cache.

### 5. ADR-018 addendum + docs

- `docs/adr/018-lambda-as-sqs-worker-runtime.md` — dated addendum (2026-05-13): Coolify is the active runtime; Lambda + EC2 paths retained for future scaling / emergency revert. Cross-reference ADR-008 addendum (RabbitMQ adapters).
- `README.md` — Production deploy section retargeted at Coolify.
- `CLAUDE.md` — Worker runtime section updated: Coolify is the active host, RabbitMQ is the prod transport.

## Affected files / surfaces

**New:**
- `deploy/nginx/nginx.conf`

**Modified:**
- `deploy/docker-compose.prod.yml` — rewritten to the 7-service shape above
- `docs/adr/018-lambda-as-sqs-worker-runtime.md` — addendum
- `README.md` — Production deploy section
- `CLAUDE.md` — Worker runtime section

**Read-only sources of truth:**
- `.env.example` — variable-name list (already extended by `2026-05-rabbitmq-transport-adapter`)
- `src/shared/config.py` — per-runtime exercise sets via field defaults

**Explicitly untouched:**
- `src/shared/events/adapters/*` — none modified here (SQS/SNS retained from before; RabbitMQ added by the prerequisite spec)
- `src/shared/events/lambda_*.py`, `src/**/lambda_*.py`
- `terraform/production/**`
- `.github/workflows/deploy.yml`
- `docker-compose.yml` (dev) — owned by `2026-05-rabbitmq-transport-adapter`
- `deploy/user_data.sh.tpl`

## Acceptance criteria

**Compose / Coolify**
- [ ] `deploy/docker-compose.prod.yml` defines exactly **seven** services: `nginx`, `api`, `extraction-worker`, `enrichment-worker`, `listings-events-worker`, `rabbitmq`, `redis`. All `restart: unless-stopped`, no `profiles:`.
- [ ] No service uses `env_file:`. `environment:` blocks use **map form** (`KEY: ${KEY}`, not list-form `KEY=${KEY}`) — required so `<<: *shared-env` can merge.
- [ ] Top-level `x-base-service` + `x-shared-env` anchors. The four Python services merge them via `<<: *…`.
- [ ] `nginx` is the only service binding host ports (`80:80`). `api` uses `expose:`, not `ports:`.
- [ ] RabbitMQ management UI (15672) is NOT exposed externally.
- [ ] `rabbitmq` + `redis` have persistent named volumes (`rabbitmq-data`, `redis-data`).
- [ ] `AWS_ENDPOINT_URL` does NOT appear anywhere in the prod compose.
- [ ] `SNS_*` and `SQS_*` env vars do NOT appear in the prod compose.

**Env partitioning**
- [ ] api's env block adds api-only vars: full Stripe block, portal Supabase + portal DB + session signing, `REDIS_URL`, `LISTINGS_PAGE_CACHE_ENABLED`, `LISTINGS_SEARCH_ENABLED`, `CORS_ORIGINS`, `RESEND_API_KEY`, `APP_URL`.
- [ ] `x-shared-env` baseline includes `DATABASE_URL`, `REDUCTO_API_KEY`, and `ENCRYPTION_PUBLIC_KEY` / `ENCRYPTION_PRIVATE_KEY` / `ENCRYPTION_HMAC_KEY` — verified by grep + by booting the screening worker (which would otherwise raise on `load_private_key_from_env("")`).
- [ ] `x-shared-env` baseline includes the 6 command-queue name literals: `PROPERTY_EXTRACTION_QUEUE=property-extraction-queue`, `PROPERTY_ENRICHMENT_QUEUE=property-enrichment-queue`, `APPLICANT_EXTRACTION_QUEUE=applicant-extraction-queue`, `APPLICANT_SCREENING_QUEUE=applicant-screening-queue`, `CONTRACT_INGESTION_QUEUE=contract-ingestion-queue`, `CONTRACT_ANALYSIS_QUEUE=contract-analysis-queue`. Verified by booting the api and POSTing the enrich endpoint — the message lands on `property-enrichment-queue` (visible in the RabbitMQ management UI), not silently dropped.
- [ ] Workers do NOT list Stripe vars (`STRIPE_*`), portal Supabase (`SUPABASE_PORTAL_*`), portal DB (`PORTAL_DATABASE_URL`), session signing (`SESSION_*`), `REDIS_URL`, `RESEND_API_KEY`, `APP_URL`, or `CORS_ORIGINS`. Greppable.
- [ ] `enrichment-worker` is the only worker listing `GOOGLE_MAPS_API_KEY`.
- [ ] `listings-events-worker` is the only worker listing Pinecone + embedding vars (`PINECONE_*`, `EMBEDDING_*`, `VECTOR_INDEX_*`, `LISTINGS_EMBEDDING_ENABLED`).

**Nginx**
- [ ] `deploy/nginx/nginx.conf` proxies `/` to `api:8000` with `X-Forwarded-Proto` / `X-Forwarded-For` / `X-Real-IP` / `Host` headers.
- [ ] `proxy_read_timeout` ≥ 60s; `client_max_body_size` ≥ 20m.
- [ ] `gzip on` for text + JSON.

**Preservation**
- [ ] No file under `src/shared/events/`, `terraform/production/`, `src/**/lambda_*.py`, or `docker-compose.yml` (dev) is modified.
- [ ] `docs/adr/018-lambda-as-sqs-worker-runtime.md` has a dated addendum cross-referencing ADR-008.
- [ ] README + CLAUDE.md updated.

## Open questions

- **AWS IAM user for S3-only access:** operator must provision an IAM user with read/write/delete on `${S3_BUCKET_NAME}` — the current `ec2_profile` role is broader. Out-of-scope to *create* the user here; captured for operator handoff.
- **Alembic migrations on Coolify:** operator-side (same as today, from laptop) vs. Coolify pre-deploy hook vs. one-shot service. **Default: operator-side** — out-of-scope to wire automation until first Coolify deploy exercises the gap.
- **`ECR_IMAGE` variable name:** keep for continuity or rename to `APP_IMAGE`? **Default: keep** — renaming touches `deploy/user_data.sh.tpl` and pulls the EC2 path back in. Coolify operators can ignore the name.
- **RabbitMQ credentials provisioning:** `RABBITMQ_USER` / `RABBITMQ_PASSWORD` are set at first rabbitmq container start and persisted to the volume. Rotating means scratching the volume or running `rabbitmqctl` against the live container. Out-of-scope to wire rotation; captured for ops handoff. (These two vars are also used at compose-render time only to build the AMQP URL string — they don't exist in `Settings` and don't need to.)

## Out of scope follow-ups

- `docs/runbooks/coolify-first-deploy.md`
- Migrating dev compose to RabbitMQ as the default (drop LocalStack-for-SNS-SQS in dev).
- Stripe webhook + Supabase redirect URL updates once the production hostname moves to the Coolify host.
- Decommissioning EC2 user-data template + Terraform EC2 module after Coolify runs cleanly.
- Decommissioning Lambda + SQS event source mappings + SNS topics after Coolify runs cleanly on RabbitMQ.
- RabbitMQ HA / clustering when traffic justifies it.
- TLS termination at nginx (currently delegated to Coolify / upstream LB).

## Commits

- `feat(deploy): Coolify production compose — nginx + api + workers + RabbitMQ + Redis`
- `feat(deploy): nginx reverse-proxy config for api`
- `docs(adr): ADR-018 addendum — Coolify as active runtime`
- `docs: production deploy section targets Coolify`
