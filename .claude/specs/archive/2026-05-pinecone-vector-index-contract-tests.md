# Pinecone VectorIndex contract-test parametrization

**Status:** shipped
**Created:** 2026-05-09

## Problem

ADR-013 §6 says every `VectorIndex` adapter should pass the same contract test suite — that's the whole point of the port. Phase 1 of `2026-05-listing-semantic-search` shipped 15 in-memory contract tests at `tests/unit/listings/adapters/test_inmemory_vector_index.py` but **did not parametrize them over `PineconeVectorIndex`** because:

- Pinecone needs a real index/namespace + an API key.
- A test namespace requires CI secrets + provisioning.
- The Pinecone adapter is small (mostly filter-operator translation) and depends on the SDK behaving as advertised; risk was assessed as low for phase 1.

But this leaves the adapter without an automated check for the filter-translation logic (`_translate_filter` in `src/listings/adapters/vector/pinecone_index.py`), which is the only non-trivial thing it does. A regression there silently breaks production search at the first model bump or filter-shape change.

## Goal

Run the same contract suite against both adapters. Pinecone tests are skipped when `PINECONE_API_KEY` is unset (so local dev / CI without secrets stays green) and run against a dedicated `pinecone-contract-tests` namespace when the key is present.

## Approach

Two phases:

### Phase 1 — pure unit tests for filter translation (no API)

Add `tests/unit/listings/adapters/test_pinecone_filter_translation.py` exercising `_translate_filter` directly with golden inputs/outputs. No Pinecone client needed. Covers:

- Bare `eq` → bare value (`{"status": "ACTIVE"}`)
- `in` → `$in`
- `gte` / `lte` → `$gte` / `$lte`
- `and` composition → `$and` of translated sub-filters
- Unsupported operators → `ValueError`

This is the highest-value chunk and ships without infra.

### Phase 2 — parametrized integration suite (requires Pinecone)

Refactor `test_inmemory_vector_index.py` so each test takes a `vector_index` fixture parametrized over `[InMemoryVectorIndex(), PineconeVectorIndex(...)]`. Pytest skip logic:

```python
@pytest.fixture(params=[
    pytest.param("inmemory", id="inmemory"),
    pytest.param("pinecone", id="pinecone", marks=pytest.mark.integration),
])
def vector_index(request):
    if request.param == "inmemory":
        return InMemoryVectorIndex()
    if not os.environ.get("PINECONE_API_KEY"):
        pytest.skip("PINECONE_API_KEY not set")
    idx = PineconeVectorIndex(
        api_key=os.environ["PINECONE_API_KEY"],
        index_name=os.environ.get("PINECONE_TEST_INDEX", "listings-contract-tests"),
    )
    yield idx
    # Teardown: delete every namespace we created for this test run
    # (use a UUID-prefixed namespace per test for isolation)
```

Each test uses a UUID-prefixed namespace so parallel runs don't collide; teardown deletes the namespace at the end.

Mark the Pinecone variant with `pytest.mark.integration` (already declared in `pyproject.toml`'s markers) so `uv run pytest -m "not integration"` excludes it for fast local loops.

## Affected files / surfaces

- `src/listings/adapters/vector/pinecone_index.py` — possibly extract `_translate_filter` to a public-but-`_`-prefixed helper for direct unit testing (it already is).
- New: `tests/unit/listings/adapters/test_pinecone_filter_translation.py` — phase 1.
- `tests/unit/listings/adapters/test_inmemory_vector_index.py` → rename + parametrize, or keep and add `tests/integration/listings/adapters/test_vector_index_contract.py` running the same assertions.
- `pyproject.toml` — `markers = ["integration: needs PINECONE_API_KEY"]` if not already there.
- CI: a separate workflow that exposes `PINECONE_API_KEY` from a secrets store and runs `pytest -m integration` against a Pinecone test project.

## Acceptance criteria

- [ ] Filter-translation unit tests cover every operator + `and` composition + unsupported-op rejection.
- [ ] Contract suite can be parametrized over both adapters via a fixture.
- [ ] `uv run pytest` (no markers) ≡ phase 1 unit tests only — no network calls.
- [ ] `uv run pytest -m integration` runs the parametrized suite. Skips Pinecone variants gracefully when key absent; runs them when present.
- [ ] Pinecone teardown deletes test namespaces (no leftover state in the test index).
- [ ] CI green on the integration workflow.

## Out of scope

- Performance benchmarks (Pinecone latency vs. in-memory).
- Cross-encoder re-ranker (ADR-013 v6).
- Read-path tests (separate phase 2 spec).

## Commit

- `test(listings): unit tests for Pinecone filter translation`
- `test(listings): parametrize VectorIndex contract suite for Pinecone`
- `chore(ci): add Pinecone integration test workflow`
