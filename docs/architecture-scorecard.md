# DDD & Hexagonal Architecture Scorecard

Use this scorecard to evaluate the repository against DDD and hexagonal architecture best practices.
Each category has checkpoints (yes/no). **Score = (yes_count / total_checkpoints) × 10**.

---

## 1. Domain Model Purity (Weight: High)

| # | Checkpoint | Yes/No |
|---|-----------|--------|
| 1 | Domain models live under `<context>/domain/` and import nothing from `adapters/` or `application/` | |
| 2 | Value objects are frozen dataclasses (immutable) with validation in `__post_init__` | |
| 3 | Aggregate roots have behavior methods beyond getters/setters (e.g., state transitions, add/remove children) | |
| 4 | Domain enums are defined in the domain layer, not imported from ORM models | |
| 5 | Domain exceptions carry no HTTP/infrastructure concepts (no status codes, no framework imports) | |

**Score: __ / 10**

---

## 2. Bounded Context Isolation (Weight: High)

| # | Checkpoint | Yes/No |
|---|-----------|--------|
| 1 | No context imports another context's domain models directly | |
| 2 | No context imports another context's ORM models or adapters | |
| 3 | Cross-context communication happens only through events, shared IDs (UUIDs), or an anti-corruption layer | |
| 4 | Each context has its own container/DI with its own set of ports | |
| 5 | Shared types appearing in multiple contexts are defined independently in each (no shared domain models) | |

**Verify:** `grep -r "from <other_context>" src/<context>/` should return nothing for each pair.

**Score: __ / 10**

---

## 3. Port/Adapter Separation (Weight: High)

| # | Checkpoint | Yes/No |
|---|-----------|--------|
| 1 | Every external dependency (DB, queue, email, AI, storage) is accessed through an ABC port in `application/ports/` | |
| 2 | Adapters implement exactly one port interface each | |
| 3 | No adapter imports another adapter directly | |
| 4 | In-memory test doubles exist for every port | |
| 5 | ORM/persistence models live in `adapters/`, not in `domain/` | |

**Score: __ / 10**

---

## 4. Use Case Design (Weight: Medium)

| # | Checkpoint | Yes/No |
|---|-----------|--------|
| 1 | Each use case is a single class with one public `execute()` method | |
| 2 | Use cases depend only on ports (ABCs), never on concrete adapters | |
| 3 | Use cases contain orchestration logic; business rules live in domain models/services | |
| 4 | No use case calls another use case directly (compose at container level if needed) | |

**Score: __ / 10**

---

## 5. Event-Driven Communication (Weight: Medium)

| # | Checkpoint | Yes/No |
|---|-----------|--------|
| 1 | Domain events are typed dataclasses (not raw dicts) | |
| 2 | Each context uses a consistent event pattern (frozen base class with typed subclasses) | |
| 3 | Event bus ports accept typed events, not `dict` | |
| 4 | Event handlers use a registry or dispatch pattern, not if/elif chains | |
| 5 | Events carry only IDs and minimal data needed for consumers | |

**Score: __ / 10**

---

## 6. Testing Architecture (Weight: Medium)

| # | Checkpoint | Yes/No |
|---|-----------|--------|
| 1 | Unit tests use in-memory adapters, not mocks of ABCs | |
| 2 | Unit tests cover domain logic independently (models, value objects, domain services) | |
| 3 | Integration tests exercise real adapters (DB, queues) | |
| 4 | Test structure mirrors source structure (easy to find tests for a given module) | |

**Score: __ / 10**

---

## 7. Dependency Injection (Weight: Low)

| # | Checkpoint | Yes/No |
|---|-----------|--------|
| 1 | Container wires ports to adapters; use cases receive ports via constructor | |
| 2 | Bootstrap/composition root is the only place that instantiates concrete adapters | |
| 3 | No service locator pattern (no global imports of concrete classes outside bootstrap) | |
| 4 | Optional dependencies are handled cleanly (explicit errors, not runtime AttributeError) | |

**Score: __ / 10**

---

## 8. Repository Health & Conciseness (Weight: Low)

| # | Checkpoint | Yes/No |
|---|-----------|--------|
| 1 | No dead code, unused imports, or commented-out blocks | |
| 2 | No duplicated mapping logic across contexts for the same data | |
| 3 | Response mapping helpers are consistent across route files | |
| 4 | File count per feature is proportional to complexity (not boilerplate-heavy) | |

**Score: __ / 10**

---

## Summary

| Category | Weight | Score | Finding |
|----------|--------|-------|---------|
| Domain Model Purity | High | /10 | |
| Bounded Context Isolation | High | /10 | |
| Port/Adapter Separation | High | /10 | |
| Use Case Design | Medium | /10 | |
| Event-Driven Communication | Medium | /10 | |
| Testing Architecture | Medium | /10 | |
| Dependency Injection | Low | /10 | |
| Repository Health | Low | /10 | |

**Weighted Total:** High categories × 3 + Medium × 2 + Low × 1, divided by max possible.

**Formula:** `((H1 + H2 + H3) × 3 + (M1 + M2 + M3) × 2 + (L1 + L2) × 1) / ((3 × 3 + 3 × 2 + 2 × 1) × 10) × 10`

---

## How to Use

1. Go through each checkpoint, reading the relevant code
2. Mark Yes or No
3. Calculate scores per category
4. Fill in the summary table with a one-line finding per category
5. Compute weighted total
6. Address any category scoring below 7/10
