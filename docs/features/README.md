# Feature Catalog

This directory documents every feature in the estate-os-service, organized by bounded context. It's intended as an onboarding reference: what each context does, what features it exposes, and where the code lives.

For each feature, you'll find:

- **Purpose** — what it does in one sentence
- **Trigger** — HTTP route, event, or worker
- **Inputs/Outputs** — execute() parameters and return type
- **Side effects** — DB writes, S3, AI calls, queue publishes, events
- **Source path** — where the code lives

## Bounded contexts

| Context | Doc | Purpose |
|---------|-----|---------|
| `customers/` | [customers.md](customers.md) | Multi-tenant users, organizations, memberships, invitations, subscriptions, notifications |
| `properties/` | [properties.md](properties.md) | Property records, owners, prices, images, AI extraction pipeline, amenity discovery |
| `listings/` | [listings.md](listings.md) | Public read-only property listings |
| `screening/` | [screening.md](screening.md) | Applicant document intake, OCR extraction, AI risk assessment |
| `bookings/` | [bookings.md](bookings.md) | Property visit slots and bookings (post-screening) |
| `contract_intelligence/` | [contract_intelligence.md](contract_intelligence.md) | Source document parsing, section analysis, template-based contract generation |

## Cross-context flows

Contexts are isolated — they communicate only via the shared event bus (ADR-008) and shared IDs. Every envelope is a `shared.events.base.DomainEvent` with a versioned `event_type` string.

**Domain events** (broadcast, `EventPublisher` → SNS topic per event type, per-context SQS queues subscribe):

```
properties  publishes  PROPERTY_CREATED.v1   → properties.discovery_processor (amenity discovery)
screening   publishes  APPLICANT_SCREENED.v1 → customers.event_processor (screening-complete email)
                                             → bookings.events.handlers (create booking applicant)
```

**Commands** (point-to-point, `CommandPublisher` → dedicated SQS queue, one consumer):

```
properties → PROPERTY_EXTRACTION_REQUESTED.v1 / BATCH_PROPERTY_EXTRACTION_REQUESTED.v1
                → properties.extraction_processor
screening  → APPLICANT_EXTRACTION_REQUESTED.v1 → screening.extraction_processor
           → APPLICANT_SCREENING_REQUESTED.v1  → screening.screening_processor
contract_intelligence → DOCUMENT_INGESTION_REQUESTED.v1 → ingestion_processor
                      → DOCUMENT_ANALYSIS_REQUESTED.v1  → analysis_processor
```

All handlers share one signature: `(event: DomainEvent, context: Any) -> None`. All handlers run on the shared `SQSWorker` (`src/shared/events/worker.py`).

## Reading order for new engineers

1. Start with **customers** — simplest CRUD patterns, RBAC, the prototypical use case structure.
2. Move to **listings** — tiny, read-only, shows the read-model pattern.
3. Then **properties** — the largest context, async pipelines, workers, S3, multiple integrations.
4. **screening** and **bookings** together — the applicant flow end-to-end.
5. **contract_intelligence** last — mostly experimental, half-implemented, longer pipeline.

## Architecture

Every context follows hexagonal architecture:

```
context/
├── domain/            # Pure business logic (entities, value objects, events, exceptions)
├── application/       # Orchestration (ports as ABCs, use cases or services)
├── adapters/          # Concrete implementations
│   ├── api/routes/    # FastAPI inbound
│   ├── database/      # SQLAlchemy outbound
│   ├── inmemory/      # Test doubles
│   └── workers/       # SQS event handlers
└── container.py       # Dependency injection wiring
```

See [`docs/architecture-scorecard.md`](../architecture-scorecard.md) for the DDD/hex evaluation rubric used in this codebase.
