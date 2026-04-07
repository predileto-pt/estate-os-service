# Contract Intelligence

The `contract_intelligence` bounded context turns uploaded source contracts into reusable templates for generating new contracts. The pipeline ingests a PDF/DOCX, runs OCR + layout analysis (Reducto), analyses sections with an LLM, and exposes hooks for human review and template promotion. **This is the most experimental context — half of the surface is scaffolded but not yet implemented.**

**Source:** `src/contract_intelligence/`

## Status legend

- ✅ **Implemented** — production code, hooked up to routes/workers
- ⚠️ **Scaffolded** — service method exists but raises `NotImplementedError`

## Domain entities

| Entity | Description |
|--------|-------------|
| `SourceDocument` | Uploaded contract. Status: `UPLOADED` → `PARSED` → `ANALYZED` (or `FAILED`). |
| `SourceParseRun` | A Reducto OCR job linked to a document. Tracks `job_id`, raw response JSON, status. |
| `SourceSection` | One parsed chunk from a document (text, page number, position). |
| `SourceSectionAnalysis` | LLM verdict for a section: type, risk level, recommended strategy, reasoning. |
| `SourceSectionAnalysisRun` | Batch grouping of section analyses for a document. |
| `SourceFieldEvidence` | Extracted key/value field with provenance. Used to bind templates. |
| `ContractTemplate` / `TemplateVersion` / `TemplateSection` | Reusable contract template with parameterized sections. |
| `GeneratedContract` / `GeneratedContractArtifact` | A contract generated from a template version, with a rendered PDF artifact. |

## Pipeline

```
upload (POST)
   │
   ▼
SourceDocumentService.upload_source_document     ✅
   ├─ S3 upload
   ├─ SHA256 dedup check
   ├─ writes SourceDocument (UPLOADED)
   └─ publishes to ingestion queue
        │
        ▼
ingestion_processor (SQS worker)
   └─ IngestionService.ingest                    ✅
        ├─ Reducto OCR (parse + layout)
        ├─ writes SourceParseRun, SourceSections
        ├─ backfills page_count
        ├─ marks SourceDocument PARSED
        └─ publishes to analysis queue
             │
             ▼
analysis_processor (SQS worker)
   └─ SectionAnalysisService.analyze             ✅
        ├─ loads sections + field evidence
        ├─ LLM analyses each section
        ├─ writes SourceSectionAnalysis + references
        └─ marks SourceDocument ANALYZED
             │
             ▼
human review                                      ⚠️ scaffolded
   └─ ReviewService.* (not implemented)
             │
             ▼
template promotion                                ⚠️ scaffolded
   └─ TemplateService.* (not implemented)
             │
             ▼
contract generation                               ⚠️ scaffolded
   └─ GeneratedContractService.* (not implemented)
```

A `dlq_processor` worker consumes the dead-letter queue and marks documents `FAILED` if they aren't already.

## Feature catalog

### SourceDocumentService

| Feature | Status | Trigger | Purpose |
|---------|--------|---------|---------|
| [upload_source_document](#sourcedocumentserviceupload_source_document) | ✅ | `POST /api/v1/admin/contracts/source-documents` | Upload + dedup + enqueue ingestion |
| [get_source_document](#sourcedocumentserviceget_source_document) | ✅ | `GET /api/v1/admin/contracts/source-documents/{document_id}` | Return metadata |
| [list_source_documents](#sourcedocumentservicelist_source_documents) | ✅ | `GET /api/v1/admin/contracts/source-documents` | List documents (with presigned URLs) |
| [get_source_document_detail](#sourcedocumentserviceget_source_document_detail) | ✅ | `GET /api/v1/admin/contracts/source-documents/{document_id}/detail` | Return metadata + raw Reducto response |
| [retry_document](#sourcedocumentserviceretry_document) | ✅ | `POST /api/v1/admin/contracts/source-documents/{document_id}/retry` | Reset a failed document and re-enqueue |

### IngestionService

| Feature | Status | Trigger | Purpose |
|---------|--------|---------|---------|
| [ingest](#ingestionserviceingest) | ✅ | SQS ingestion queue | Worker: Reducto OCR → sections → publish to analysis queue |

### SectionAnalysisService

| Feature | Status | Trigger | Purpose |
|---------|--------|---------|---------|
| [analyze](#sectionanalysisserviceanalyze) | ✅ | SQS analysis queue | Worker: LLM-analyse sections, persist results |

### ReviewService (scaffolded)

| Feature | Status | Trigger | Purpose |
|---------|--------|---------|---------|
| `get_source_review_bundle` | ⚠️ | `GET /api/v1/admin/contracts/review/source-documents/{document_id}` | Return sections + field evidence for review |
| `update_source_section_review` | ⚠️ | `PATCH /api/v1/admin/contracts/review/source-sections/{section_id}` | Accept/correct/reject a section |
| `update_field_evidence_review` | ⚠️ | `PATCH /api/v1/admin/contracts/review/source-field-evidence/{evidence_id}` | Accept/correct field evidence |

### TemplateService (scaffolded)

| Feature | Status | Trigger | Purpose |
|---------|--------|---------|---------|
| `create_template_version_from_source` | ⚠️ | `POST /api/v1/admin/contracts/template-versions/from-source/{source_document_id}` | Promote a reviewed source to a template |
| `get_template_version` | ⚠️ | `GET /api/v1/admin/contracts/template-versions/{version_id}` | Return a template version |
| `update_template_version` | ⚠️ | `PATCH /api/v1/admin/contracts/template-versions/{version_id}` | Patch a draft template |
| `update_template_section` | ⚠️ | `PATCH /api/v1/admin/contracts/template-versions/template-sections/{section_id}` | Patch one template section |
| `publish_template_version` | ⚠️ | `POST /api/v1/admin/contracts/template-versions/{version_id}/publish` | Approve a template version |

### GeneratedContractService (scaffolded)

| Feature | Status | Trigger | Purpose |
|---------|--------|---------|---------|
| `create_from_crm` | ⚠️ | `POST /api/v1/admin/contracts/generated-contracts/from-crm` | Create a draft contract from CRM data + template |
| `get_generated_contract` | ⚠️ | `GET /api/v1/admin/contracts/generated-contracts/{contract_id}` | Return a generated contract |
| `render_generated_contract` | ⚠️ | `POST /api/v1/admin/contracts/generated-contracts/{contract_id}/render` | Render Jinja → PDF, store in S3 |

---

## Feature details

### SourceDocumentService.upload_source_document

Receive a file upload, store in S3 under `source-documents/{org_id}/{doc_id}/{filename}`, compute SHA256 for dedup, create the `SourceDocument`, publish to the ingestion queue.

- **Inputs:** `file: UploadFile`, `organization_id`
- **Output:** `UploadSourceDocumentResponse`
- **Side effects:** S3 upload, DB write, SQS publish (after commit)
- **Errors:** `DuplicateDocumentHashError` if the content hash already exists
- **Source:** `src/contract_intelligence/application/services/source_document_service.py`

### SourceDocumentService.get_source_document

Return basic metadata + status.

- **Inputs:** `document_id`
- **Output:** `SourceDocumentRead`

### SourceDocumentService.list_source_documents

List documents, optionally filtered by organization. Generates a pre-signed S3 download URL for each.

- **Inputs:** `organization_id?`
- **Output:** `list[SourceDocumentListItem]`

### SourceDocumentService.get_source_document_detail

Return the document plus the latest succeeded `SourceParseRun` (with the raw Reducto response JSON).

- **Inputs:** `document_id`
- **Output:** `SourceDocumentDetail`

### SourceDocumentService.retry_document

Reset a `FAILED` document back to `UPLOADED` and re-publish to the ingestion queue.

- **Inputs:** `document_id`
- **Output:** `UploadSourceDocumentResponse`
- **Errors:** raises if the document is not in `FAILED`

### IngestionService.ingest

**Worker.** Triggered by an ingestion-queue message with `{document_id}`. Runs Reducto OCR + layout analysis, creates one `SourceSection` per parsed chunk, backfills `page_count`, advances the document status to `PARSED`, then publishes to the analysis queue.

- **Inputs:** `document_id`
- **Output:** `IngestResult(parse_run_id, sections_created)`
- **Side effects:**
  - In dev: downloads the file from LocalStack and uploads to Reducto
  - In prod: generates a presigned URL for Reducto to fetch directly
  - DB: writes `SourceParseRun`, `SourceSection`s, updates `SourceDocument.upload_status`
  - SQS: publishes to analysis queue
- **Idempotency:** skips if `upload_status != UPLOADED`
- **Failure handling:** marks both `SourceParseRun` and `SourceDocument` as `FAILED`, commits, then re-raises
- **Source:** `src/contract_intelligence/application/services/ingestion_service.py`
- **Worker entry:** `src/contract_intelligence/adapters/workers/ingestion_processor.py`

### SectionAnalysisService.analyze

**Worker.** Triggered by an analysis-queue message with `{document_id}`. Loads parsed sections + extracted field evidence, calls the LLM to analyze sections, writes `SourceSectionAnalysis` + reference rows, advances the document status to `ANALYZED`.

- **Inputs:** `document_id`
- **Output:** `SourceSectionAnalysisRun`
- **Guard:** requires `upload_status == PARSED`
- **Idempotency:** skips if a succeeded run already exists
- **Side effects:** DB writes (run + analyses + references), LLM call (`SectionAnalysisLLMPort.analyze_sections`)
- **Failure handling:** marks run + document as `FAILED`
- **Source:** `src/contract_intelligence/application/services/section_analysis_service.py`
- **Worker entry:** `src/contract_intelligence/adapters/workers/analysis_processor.py`

## Workers

| Worker | Queue | Action |
|--------|-------|--------|
| `ingestion_processor.py` | ingestion / analysis queue | Routes to `IngestionService.ingest()` |
| `analysis_processor.py` | analysis queue | Routes to `SectionAnalysisService.analyze()` |
| `dlq_processor.py` | dead letter queue | Marks `SourceDocument` as `FAILED` if not already |

## Container

`src/contract_intelligence/container.py` wires all six services and their port dependencies. The ports live in `application/ports/` (`reducto.py`, `llm.py`, `storage.py`, `repositories.py`, `messaging.py`). Built in `src/shared/entrypoints/bootstrap.py::get_contract_intelligence_container()`.

## Caveats for new engineers

- Half the surface (review, templates, contract generation) is scaffolded but raises `NotImplementedError`. Routes exist; calling them returns 501.
- The pipeline only runs through `ANALYZED`. Anything past that is not wired up.
- This context uses a `commit()` method on the repository abstraction (a unit-of-work pattern), unlike the rest of the codebase which commits inside each repository call.
