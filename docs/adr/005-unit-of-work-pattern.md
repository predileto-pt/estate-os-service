# ADR-005: Unit of Work pattern for SQLAlchemy-based bounded contexts

**Date:** 2026-03-31
**Status:** Accepted

## Context

The estate-os-service has three bounded contexts that use SQLAlchemy + PostgreSQL: `contract_intelligence`, `screening`, and `bookings`. Before this change, each used a different transaction strategy:

| Context | Pattern | Problem |
|---------|---------|---------|
| `contract_intelligence` | Repos called `flush()`, services called `commit()` | Services had to remember to commit; missing commits caused silent data loss |
| `screening` | Repos called `commit()` after every `save()` | Multi-repo operations were NOT atomic — partial failures left inconsistent data |
| `bookings` | Repos called `commit()` + manual rollback in exception handlers | Slot booking and booking creation were two separate transactions |

### Example: screening partial failure

```python
# screening/application/services/submission.py (BEFORE)
applicant = await self.applicant_repo.save(applicant)   # ← commit #1
submission = await self.submission_repo.save(submission) # ← commit #2
for doc in documents:
    await self.document_repo.save(doc)                   # ← commit #3, #4, ...
await self.publisher.publish(extraction_queue, msg)      # ← if this fails,
# applicant + submission + documents are already committed with no way to roll back
```

### Example: contract_intelligence missing commit

```python
# contract_intelligence/application/services/ingestion_service.py (BEFORE)
await self._repo.update_status(document.id, UploadStatus.PARSED)  # flush only
# ... no commit() anywhere in the service → transaction rolls back on session close
# Result: document stays UPLOADED forever despite successful parsing
```

## Decision

Implement the **Unit of Work** pattern. The UoW is an ABC (port) in the application layer with a SQLAlchemy implementation in the adapters layer. It owns the session lifecycle and transaction boundary.

### Architecture

```
shared/ports/unit_of_work.py          ← Base ABC: commit(), rollback(), async context manager
    │
    ├── screening/application/ports/unit_of_work.py       ← ScreeningUnitOfWork(UnitOfWork)
    │       .applicants, .documents, .extracted_data,        with context-specific repos
    │       .screening_reports, .events, .submissions, ...
    │
    ├── bookings/application/ports/unit_of_work.py        ← BookingUnitOfWork(UnitOfWork)
    │       .slots, .bookings, .applicants                   with context-specific repos
    │
    └── contract_intelligence/application/ports/unit_of_work.py  ← ContractUnitOfWork(UnitOfWork)
            .source_documents, .source_sections,                    with context-specific repos
            .templates, .generated_contracts

Each has a SqlAlchemy implementation in adapters/database/unit_of_work.py
```

### Rules

1. **Services receive a UoW**, not individual repos
2. **All DB work happens inside `async with self._uow:`** — this creates a fresh session
3. **Repos only `flush()`**, never `commit()` — flush is needed to get auto-generated IDs
4. **Services call `await self._uow.commit()`** explicitly when the operation succeeds
5. **Unhandled exceptions auto-rollback** via `__aexit__`
6. **SQS publish happens AFTER the `async with` block** (after commit) to prevent message-before-data races
7. **Exception handlers can commit failure state** before re-raising (e.g., mark document as FAILED). The `__aexit__` rollback that follows is a no-op since the transaction was already committed

## Usage

### Service pattern

```python
class IngestionService:
    def __init__(self, uow: ContractUnitOfWork, storage: FileStoragePort, ...) -> None:
        self._uow = uow
        self._storage = storage

    async def ingest(self, document_id: UUID) -> IngestResult:
        should_publish = False

        async with self._uow:
            document = await self._uow.source_documents.get_by_id(document_id)
            if not document:
                raise SourceDocumentNotFoundError(document_id)

            # ... do work through self._uow.source_documents, self._uow.source_sections ...

            try:
                result = await self._reducto.run_pipeline(document_input)

                for section in result.sections:
                    await self._uow.source_sections.save_section(section)

                document.mark_parsed()
                await self._uow.source_documents.update_status(document.id, document.upload_status)
                await self._uow.commit()
                should_publish = True

            except Exception:
                document.mark_failed()
                await self._uow.source_documents.update_status(document.id, document.upload_status)
                await self._uow.commit()  # persist failure state
                raise

        # SQS publish AFTER commit, OUTSIDE the async with
        if should_publish:
            await self._publisher.publish(queue_url, {"document_id": str(document.id)})
```

### Route pattern (for read-only or simple writes)

```python
@router.get("/{document_id}")
async def get_document(document_id: UUID, request: Request):
    container = request.app.state.contract_intelligence_container
    return await container.source_document_service.get_source_document(document_id)

# Inside the service:
async def get_source_document(self, document_id):
    async with self._uow:
        document = await self._uow.source_documents.get_by_id(document_id)
        if not document:
            raise SourceDocumentNotFoundError(document_id)
    # No commit needed for reads — session just closes
    return SourceDocumentRead(...)
```

### Booking optimistic locking (atomic)

```python
async def create(self, slot_id: str, applicant_id: str, notes: str = "") -> Booking:
    async with self._uow:
        slot = await self._uow.slots.find(slot_id)
        if not slot or not slot.is_available():
            raise SlotNotAvailableError(slot_id)

        booked = await self._uow.slots.mark_booked(slot_id)  # flush, not commit
        if not booked:
            raise SlotNotAvailableError(slot_id)

        booking = Booking(...)
        created = await self._uow.bookings.create(booking)
        await self._uow.commit()  # atomic: slot + booking in one transaction

    # No manual rollback needed — if anything fails, __aexit__ rolls back both
    await self.notifier.booking_confirmed(created)
    return created
```

### UoW implementation (adapters layer)

```python
class SqlAlchemyContractUnitOfWork(ContractUnitOfWork):
    def __init__(self, session_factory: async_sessionmaker) -> None:
        self._session_factory = session_factory

    async def __aenter__(self):
        self._session = self._session_factory()
        self.source_documents = SqlAlchemySourceDocumentRepository(self._session)
        self.source_sections = SqlAlchemySourceSectionRepository(self._session)
        self.templates = SqlAlchemyTemplateRepository(self._session)
        self.generated_contracts = SqlAlchemyGeneratedContractRepository(self._session)
        return self

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            await self.rollback()
        await self._session.close()
```

### Container wiring

```python
class Container:
    def __init__(self, session_factory: async_sessionmaker, storage, reducto, ...):
        uow = SqlAlchemyContractUnitOfWork(session_factory)
        self.source_document_service = SourceDocumentService(uow=uow, storage=storage, ...)
        self.ingestion_service = IngestionService(uow=uow, storage=storage, ...)
```

### Bootstrap

```python
async def get_contract_intelligence_container():
    engine = create_async_engine(settings.database_url, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    # Pass session_factory — container creates UoW internally
    return ContractIntelligenceContainer(session_factory=session_factory, ...)
```

## Consequences

### Positive

- **Atomic operations** — all repo changes in a service method commit or rollback together
- **No partial failures** — screening submission can't leave orphaned applicants
- **Booking atomicity** — slot reservation + booking creation in one transaction, no manual rollback
- **Session-per-operation** — fresh session each `async with`, no stale state across requests
- **Clean separation** — UoW ABC is a port in application layer, implementation is in adapters
- **SQS safety** — messages published after commit, not before

### Negative

- **Slightly more verbose** — services must use `async with self._uow:` blocks
- **Exception handler commits** — failure state updates require explicit `await self._uow.commit()` before re-raising (the subsequent `__aexit__` rollback is a no-op on the already-committed transaction)

### Not affected

- **Supabase-based contexts** (customer_management, property_management) — use Supabase client, not SQLAlchemy
- **properties_listing** — read-only, no writes
- **Domain layer** — entities don't know about UoW
- **API routes** — call services unchanged
