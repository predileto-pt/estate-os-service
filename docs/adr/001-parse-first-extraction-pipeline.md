# ADR-001: Parse-first extraction pipeline — single OCR, text-based classification and extraction

**Date:** 2026-03-16
**Status:** Accepted

## Context

The original batch property extraction pipeline had a design problem: it used two separate classification paths and redundant OCR.

### Before (double-OCR design)

```mermaid
flowchart LR
    subgraph "Path 1 — Classification"
        A[Raw PDF bytes] --> B["OpenAIDocumentClassifier<br/>(GPT-4o vision API)"]
        B --> C["base64-encoded images<br/>sent to OpenAI"]
    end

    subgraph "Path 2 — Extraction"
        A --> D["ReductoOpenAIPropertyExtractor"]
        D --> E["Reducto OCR<br/>(2nd parse of same docs)"]
        E --> F["Classify from text<br/>(duplicate classification)"]
        F --> G["Extract property data"]
        F --> H["Extract ID owner data"]
    end
```

Problems:

1. **Double OCR** — Every document was parsed twice: once by OpenAI vision (base64 images) for classification, once by Reducto for text-based extraction. This doubled latency and API costs.
2. **No persistence of parsed content** — Reducto text was used in-memory and discarded. Re-processing a job required re-OCR'ing all documents.
3. **Monolithic extractor** — `ReductoOpenAIPropertyExtractor` (339 lines) did OCR + classification + property extraction + ID extraction + owner merging in one class, violating single responsibility.
4. **Two classification implementations** — `OpenAIDocumentClassifier` (vision-based, used by `ProcessBatchPropertyExtraction`) and `_classify_documents()` (text-based, internal to the extractor) both classified documents with different prompts and schemas.

### Cost analysis

| Operation | Old pipeline | New pipeline |
|-----------|-------------|-------------|
| Reducto OCR calls per document | 1 (extractor) | 1 (parser) |
| OpenAI vision API calls | N documents (classifier) | 0 |
| OpenAI text LLM calls | classification + property + N×ID | classification + property + N×ID |
| **Total API calls per batch of 5 docs** | **5 vision + 5 OCR + 7 LLM = 17** | **5 OCR + 7 LLM = 12** |

## Decision

### Parse all documents first, then classify and extract from text

The new design follows a strict linear pipeline: **parse → persist → classify → extract**.

```mermaid
flowchart TB
    start([Batch extraction job]) --> download["1. Download documents from S3"]
    download --> parse["2. Parse all documents with Reducto<br/>(single OCR pass per document)"]
    parse --> persist["3. Persist parsed text<br/>→ document_contents table"]
    persist --> classify["4. Classify from parsed text<br/>(OpenAITextDocumentClassifier)"]
    classify --> update_clf["5. Update document_contents<br/>with category + subtype"]
    update_clf --> split{"6. Split by category"}

    split -->|property_document| extract_prop["7. Extract property data<br/>(ReductoOpenAIPropertyExtractor)"]
    split -->|personal_id| extract_id["8. Extract owner data per ID doc<br/>(OpenAIIdDocumentExtractor)<br/>subtype-routed prompts"]

    extract_prop --> merge["9. Merge owners<br/>(dedup by NIF, ID wins)"]
    extract_id --> merge

    merge --> create["10. Create Property +<br/>PropertyOwner records"]
    create --> complete(["11. Mark job completed"])

    style parse fill:#e1f5fe,stroke:#0288d1
    style persist fill:#c8e6c9,stroke:#388e3c
    style classify fill:#f3e5f5,stroke:#7b1fa2
    style split fill:#fff3e0,stroke:#f57c00
    style merge fill:#fce4ec,stroke:#c62828
```

### Split the monolith into focused classes

The 339-line `ReductoOpenAIPropertyExtractor` is decomposed into four single-responsibility classes:

```mermaid
classDiagram
    class DocumentParser {
        <<abstract>>
        +parse(bytes) str
        +parse_batch(list~bytes~) list~str~
    }

    class DocumentClassifier {
        <<abstract>>
        +classify(list~str~) list~ClassifiedDocument~
    }

    class PropertyExtractorService {
        <<abstract>>
        +extract(list~str~) PropertyExtractionResult
    }

    class DocumentDataExtractor {
        <<abstract>>
        +extract_property_owner_data(str, str) dict
    }

    class ReductoDocumentParser {
        -reducto_api_key: str
        +parse(bytes) str
        +parse_batch(list~bytes~) list~str~
    }

    class OpenAITextDocumentClassifier {
        -api_key: str
        -model: str
        +classify(list~str~) list~ClassifiedDocument~
    }

    class ReductoOpenAIPropertyExtractor {
        -openai_api_key: str
        -model: str
        +extract(list~str~) PropertyExtractionResult
    }

    class OpenAIIdDocumentExtractor {
        -api_key: str
        -model: str
        +extract_property_owner_data(str, str) dict
    }

    DocumentParser <|.. ReductoDocumentParser
    DocumentClassifier <|.. OpenAITextDocumentClassifier
    PropertyExtractorService <|.. ReductoOpenAIPropertyExtractor
    DocumentDataExtractor <|.. OpenAIIdDocumentExtractor
```

### Persist parsed content

A new `document_contents` table stores the Reducto output for each document in a job:

```mermaid
erDiagram
    extraction_jobs ||--o{ document_contents : "has"
    extraction_jobs {
        uuid id PK
        uuid user_id
        string status
        jsonb document_keys
        string listing_type
        string typology
        uuid property_id FK
    }
    document_contents {
        uuid id PK
        uuid extraction_job_id FK
        int document_index
        string document_key
        text parsed_text
        string category
        string document_subtype
        timestamp created_at
    }
    extraction_jobs ||--o| properties : "creates"
    properties {
        uuid id PK
        uuid user_id
        string address
        string listing_type
        string typology
    }
    properties ||--o{ property_owners : "has"
    property_owners {
        uuid id PK
        uuid property_id FK
        string full_name
        string nif
    }
```

### Port signature changes

All ports now accept **text** instead of **raw bytes**, making the OCR boundary explicit:

| Port | Before | After |
|------|--------|-------|
| `PropertyExtractorService.extract()` | `list[bytes]` | `list[str]` |
| `DocumentClassifier.classify()` | `list[bytes]` | `list[str]` |
| `DocumentDataExtractor.extract_property_owner_data()` | `(bytes, content_type: str)` | `(parsed_text: str, document_subtype: str)` |

The new `DocumentParser` port owns the bytes→text boundary:

| Port | Method | Signature |
|------|--------|-----------|
| `DocumentParser` | `parse()` | `(bytes) → str` |
| `DocumentParser` | `parse_batch()` | `(list[bytes]) → list[str]` |

### ID document subtype routing

`OpenAIIdDocumentExtractor` routes each ID document to a type-specific extraction prompt based on the classification result:

```mermaid
flowchart LR
    input["parsed text +<br/>document_subtype"] --> router{subtype?}
    router -->|cartao_cidadao| cc["CARTAO_CIDADAO_PROMPT<br/>NIF, doc number, district"]
    router -->|titulo_residencia| tr["TITULO_RESIDENCIA_PROMPT<br/>NIF, permit number, SEF/AIMA"]
    router -->|visto_residencia| vr["VISTO_RESIDENCIA_PROMPT<br/>visa number, NIF if present"]
    router -->|passport| pp["PASSPORT_PROMPT<br/>passport number, NIF if present"]
    cc --> llm["ChatOpenAI.with_structured_output<br/>(IdOwnerSchema)"]
    tr --> llm
    vr --> llm
    pp --> llm
    llm --> result["owner dict"]

    style router fill:#f3e5f5,stroke:#7b1fa2
    style llm fill:#e1f5fe,stroke:#0288d1
```

### Owner merge strategy

Owners from property documents (escrituras, certidões) are merged with owners from ID documents. The merge uses NIF as the join key, with ID extraction taking precedence for non-null fields:

```mermaid
flowchart TB
    prop_owners["Property extraction owners<br/>(from escritura text)"] --> by_nif["Index by NIF<br/>(lower priority)"]
    id_owners["ID extraction owners<br/>(from cartão/passport text)"] --> merge["Merge into NIF index<br/>(higher priority, non-null fields win)"]
    by_nif --> merge
    merge --> dedup["Deduplicated owner list"]
    dedup --> create["Create PropertyOwner records"]

    style id_owners fill:#c8e6c9,stroke:#388e3c
    style prop_owners fill:#fff3e0,stroke:#f57c00
    style merge fill:#fce4ec,stroke:#c62828
```

Special cases:
- NIF `000000000` (placeholder for visas/passports without NIF) is never used as a merge key
- Owners without NIF are added as separate entries keyed by `_no_nif_{full_name}`

## Consequences

**Positive:**

- **Eliminates double OCR** — Each document is parsed exactly once, reducing latency and Reducto API costs
- **Eliminates vision API dependency** — Classification and ID extraction use text LLM calls instead of expensive GPT-4o vision calls, reducing OpenAI costs
- **Parsed content is persisted** — `document_contents` enables re-classification or re-extraction without re-OCR, supports debugging, and provides an audit trail
- **Single responsibility** — Each adapter class does one thing; easier to test, replace, or swap providers (e.g., replace Reducto with another OCR provider by implementing `DocumentParser`)
- **Text-based ports** — Downstream components are decoupled from the OCR provider; they only see strings

**Negative:**

- **More classes and files** — The monolith split adds 8 new files and 2 new ports; more surface area to navigate
- **Sequential parsing** — `parse_batch()` processes documents one at a time; could be parallelized with `asyncio.gather()` in a future iteration
- **Extra DB writes** — Persisting parsed content adds N inserts + N updates (for classification) per job; acceptable overhead for the audit/reuse benefit

## Files

| File | Role |
|------|------|
| `domain/models/document_content.py` | `DocumentContent` dataclass |
| `application/ports/document_parser.py` | `DocumentParser` ABC — bytes→text boundary |
| `application/ports/repositories/document_content_repository.py` | `DocumentContentRepository` ABC |
| `adapters/ai/reducto_document_parser.py` | `ReductoDocumentParser` — Reducto OCR |
| `adapters/ai/openai_text_document_classifier.py` | `OpenAITextDocumentClassifier` — text-based classification |
| `adapters/ai/openai_id_document_extractor.py` | `OpenAIIdDocumentExtractor` — subtype-routed ID extraction |
| `adapters/ai/reducto_openai_property_extractor.py` | `ReductoOpenAIPropertyExtractor` — property-only extraction from text |
| `adapters/persistence/supabase_document_content_repo.py` | `SupabaseDocumentContentRepository` |
| `adapters/database/models.py` | `DocumentContentModel` ORM model |
| `alembic/versions/a8c3d4e5f901_add_document_contents.py` | Migration |
| `application/use_cases/process_batch_property_extraction.py` | Rewritten pipeline orchestration |
| `application/use_cases/process_property_extraction.py` | Updated to parse-then-extract |
| `container.py` | Rewired with new dependencies |
| `shared/entrypoints/bootstrap.py` | Production adapter wiring |
