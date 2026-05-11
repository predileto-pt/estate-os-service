# Pending tasks before prod

Operational checklists for shipped-but-gated work. Each section lives until the gate is flipped on in production; archive (delete the section) afterwards.

---

## Listings semantic search — ADR-013 + ADR-014

**Status:** code shipped, gated off (`LISTINGS_SEARCH_ENABLED=false`).
**Specs:**
- `.claude/specs/archive/2026-05-listing-semantic-search.md` (phase 1 — indexing pipeline)
- `.claude/specs/archive/2026-05-listing-semantic-search-read-path.md` (phase 2 — read path)
- `.claude/specs/archive/2026-05-listing-search-structured-extraction.md` (ADR-014 — structured extraction + hybrid retrieval)

### Pre-flight (one-time per environment)

- [ ] **Provision Pinecone resources** (per environment: dev / staging / prod). See [README § Listings Semantic Search Setup → §1](README.md#1-create-a-pinecone-project--index) for the exact `pc` CLI commands.
  - Create the project + serverless index (`listings-<env>`, 1536 dims, cosine metric, aws/us-east-1).
  - Copy `PINECONE_HOST` (preferred) or `PINECONE_INDEX` (fallback) into the env's secret store.
  - Create the project-scoped API key → `PINECONE_API_KEY`.
- [ ] **Fill in the env vars** in the deployed secret store / `.env`:
  ```bash
  # Indexing pipeline (ADR-013 phase 1)
  LISTINGS_EMBEDDING_ENABLED=false   # flip to true after Pinecone provisioning is verified
  EMBEDDING_MODEL=text-embedding-3-small
  EMBEDDING_DIMENSIONS=1536
  PINECONE_API_KEY=…
  PINECONE_HOST=…           # preferred
  PINECONE_INDEX=…          # fallback
  VECTOR_INDEX_NAMESPACE=openai-text-embedding-3-small-v1

  # Search read path (ADR-014)
  LISTINGS_SEARCH_ENABLED=false
  SEARCH_LLM_MODEL=gpt-4o-mini
  SEARCH_LLM_TIMEOUT_SECONDS=4.0
  SEARCH_LLM_MAX_OUTPUT_TOKENS=200
  VECTOR_INDEX_TOP_K=50
  SEARCH_MAX_PRE_FILTER_CANDIDATES=1000
  SEARCH_BROAD_MODE_OVERSHOOT=4
  ```

### Phase 1 rollout — turn indexing on (per environment, staging first)

- [ ] Flip `LISTINGS_EMBEDDING_ENABLED=true` in staging. Restart the listings worker.
- [ ] **Verify end-to-end** ([README § Listings Semantic Search Setup → §4](README.md#4-verify-end-to-end)):
  - Publish a property via the admin endpoint.
  - Watch the worker logs: expect `property_listings.upsert applied=True` then `listing_embedding.indexed text_hash=… property_id=…`.
  - Verify the row: `SELECT id, embedding_status, embedded_at FROM property_listings WHERE id = '<pid>'` returns `INDEXED` / non-null.
  - Verify the Pinecone vector: `pc index stats --name listings-staging` shows `vector_count >= 1` in the `openai-text-embedding-3-small-v1` namespace.
- [ ] Run the canonical-text **v2** backfill if there are stagnant pre-indexing listings (rows already in `property_listings` from the carried-state projector). Spec: `2026-05-listings-canonical-text-backfill` (archived).
- [ ] Repeat for production. **Wait a release cycle** to make sure the indexing handler is stable before turning on the read path.

### Phase 2 rollout — turn the search read path on (after phase 1 is steady)

- [ ] **Wipe the dev/staging Pinecone namespace** before re-indexing. The canonical-text v3 schema is incompatible with v2 hashes — every listing needs to re-embed under the new shape. (In staging only — production wipes are out of scope; production migrates via the parallel-namespace pattern in ADR-013's "Bumping the embedding model" if it ever needs it.)
- [ ] **Run the canonical-text v3 backfill.** The handler routes on `CANONICAL_TEXT_VERSION = "v3"` in code; the hash mismatch on every row auto-triggers re-embed. For stagnant rows (no further `PROPERTY_UPDATED.v1` event), enqueue the event via the existing backfill mechanism.
  - Watch `embedding_status` drain from `PENDING` → `INDEXED` across the catalog.
  - Expected re-embed cost: (active listing count) × OpenAI embedding price. At small fanout this is negligible.
- [ ] **Validate offline against a manual PT query corpus** (~30 queries). Suggested coverage:
  - Single-facet: "casa", "T3", "com piscina", "perto de escola".
  - Multi-facet: "casa T3 com piscina perto de escola em Cascais".
  - Negation: "não preciso de piscina" → `has_pool` should stay null, not flip false.
  - Off-vocab POI: "casa perto de cabeleireiro" → should land in `free_text_remainder`, not `nearby_pois`.
  - Colloquial: "T2 jeitoso com varanda".
  - Listing-style: "ginásio escola supermercado".
  - Off-Cascais structural impossible: query something the test corpus genuinely doesn't have.
- [ ] **Flip `LISTINGS_SEARCH_ENABLED=true` in staging.** Eyeball for a day:
  - Latency p95 — target is 700ms end-to-end (LLM 400ms + parallel SQL/embed 150ms + ANN 100ms + hydrate 50ms).
  - `search_listings.broad_mode` log line frequency — should be **rare**. If it fires often, increase `SEARCH_MAX_PRE_FILTER_CANDIDATES` or look at which queries are saturating (likely highly populated areas with no other filters).
  - `search_listings.sql_prefilter_failed` / `embed_failed` / `vector_query_failed` — should never fire under normal conditions.
- [ ] **Flip `LISTINGS_SEARCH_ENABLED=true` in production.** Same observability watch for the first 24h.

### Pinecone index ops (ongoing)

- [ ] Stagnant-row monitoring query (cheap thanks to the `idx_property_listings_embedding_status_pending` partial index):
  ```sql
  SELECT id, organization_id, embedding_status, updated_at
  FROM property_listings
  WHERE embedding_status != 'INDEXED'
  ORDER BY updated_at DESC;
  ```
- [ ] FAILED rows need triage before re-driving from the DLQ:
  ```sql
  SELECT id, embedding_status, updated_at
  FROM property_listings WHERE embedding_status = 'FAILED';
  ```
- [ ] Hot-loop check (per ADR-013 §2a — properties should batch POI writes):
  ```sql
  SELECT id, count(*)
  FROM property_listings
  WHERE embedded_at > now() - interval '1 hour'
  GROUP BY id HAVING count(*) > 3;
  ```
- [ ] Rotate `PINECONE_API_KEY` per the dashboard's playbook ([README § 6](README.md#6-rotating-the-pinecone-api-key)).

### Follow-ups deferred from the specs

These are out-of-scope for the gated rollout; track them as fresh specs when they become real.

- [ ] **Cross-encoder re-ranker** (ADR-013 §6.7 / ADR-014 §9). Reach for this only when retrieval-quality data shows hybrid alone is insufficient.
- [ ] **Personalization** — saved searches, user history feeding back into ranking.
- [ ] **Faceted result counts** ("X in Cascais, Y in Estoril, …").
- [ ] **Polarity parsing** — "não preciso de piscina" → `has_pool=False` (currently treated conservatively as null).
- [ ] **Multilingual extraction** — EN/DE/FR query support. The v3 prompt is PT-tuned.
- [ ] **`min_parking_spaces` filter** — exact-count parking ("com 2 lugares de garagem"). TODO landed on `ParsedQuery`.
- [ ] **Type-aware price filtering** — current implementation uses `min_price` (lowest price across listing types). A rent+sale listing at €1500/mo + €500k filters by `min_price=1500`, which can exclude it from a `min_price >= 250000` sale query. Fix by filtering on `prices` JSONB by listing_type.
- [ ] **Batch presigned-URL generation** in `_to_response`. Sequential per-image S3 calls dominate the response time at high top_k.
- [ ] **Cursor pagination over the score-ordered list** beyond `VECTOR_INDEX_TOP_K`. Today, `limit + offset > top_k` returns whatever's left in the top-k window.
- [ ] **Replace `static_data/locations.json` with canonical INE dataset** before scaling beyond PT-EU early adopters. The current v1 starter covers all 20 top-level units, all 308 municipalities, and 279 parishes focused on the metro Lisboa/Porto/Setúbal areas — but stops short of all 3091 PT parishes.
