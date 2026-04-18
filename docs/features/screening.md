# Screening

The `screening` bounded context handles the end-to-end applicant flow: a prospective tenant fills out an intake form, uploads identification and proof-of-income documents, and the system runs OCR + LLM-based risk assessment to produce a screening report. Sensitive fields (NIF) are encrypted at rest with RSA + HMAC.

**Source:** `src/screening/`

## Domain entities

| Entity | Description |
|--------|-------------|
| `Applicant` | Personal info + property of interest. NIF is encrypted (RSA) and indexed via HMAC. |
| `Submission` | Per-form-request submission. Status: `PENDING` → `PROCESSING` → `PROCESSED` / `FAILED`. |
| `Document` | Uploaded file. Status: `PENDING` → `UPLOADED` → `EXTRACTING` → `EXTRACTED`. |
| `ExtractedData` | OCR result + structured fields per document. |
| `ScreeningReport` | LLM assessment: `risk_level` (LOW / MEDIUM / HIGH), justification, identity_verified, income_verified, DTI ratio, average monthly income. |
| `IntakeFormRequest` | A form request created by an agent that the applicant fills in. |

## Pipeline

```
intake form created (agent)
        │
        ▼
applicant submits (POST /portal/submissions)
   ├─ creates Applicant + Submission + N Documents
   └─ publishes 1 message per document → extraction queue
        │
        ▼
extraction_processor (SQS worker)
   ├─ ExtractionService.extract_document()
   ├─ Reducto OCR → ExtractedData saved
   └─ when ALL documents extracted → publishes to screening queue
        │
        ▼
screening_processor (SQS worker)
   ├─ ScreeningService.screen_applicant()
   ├─ LangGraph assessor (OpenAI) → risk + justification
   ├─ translator → justification in pt-PT
   ├─ saves ScreeningReport, marks Submission PROCESSED
   └─ publishes APPLICANT_SCREENED.v1 (SNS fan-out via EventPublisher)
        │
        ▼
consumed by (each on its own SQS queue subscribed to the topic):
   - bookings.events.handlers.handle_applicant_screened (creates BookingApplicant unless HIGH risk)
   - customers.adapters.workers.event_processor.handle_applicant_screened (sends screening-complete email)
   - customers.event_processor (sends email notification to property owner)
```

## Feature catalog

| Feature | Trigger | Purpose |
|---------|---------|---------|
| [SubmissionService.submit](#submissionservicesubmit) | `POST /api/v1/portal/submissions` | Applicant submits form + document references |
| [ExtractionService.extract_document](#extractionserviceextract_document) | SQS extraction queue | Worker: OCR a single document, enqueue screening when all done |
| [ScreeningService.screen_applicant](#screeningservicescreen_applicant) | SQS screening queue | Worker: assess risk and produce a screening report |

Routes also expose `GET /api/v1/portal/submissions/{applicant_id}/status` for polling, plus admin endpoints under `/api/v1/admin/applicants` and `/api/v1/admin/intake-form-requests` for listing/managing form requests and viewing reports. These read directly from repositories (no service method).

---

## Feature details

### SubmissionService.submit

Accept an applicant submission. Validates that the form request exists, that all S3 keys exist in storage, creates the applicant + submission + documents in one transaction, then publishes one extraction message per document.

- **Inputs:** `nif`, `name`, `date_of_birth`, `email`, `organization_id`, `form_request_id`, `listing_type`, `property_type?`, `terms_accepted`, `documents` (list of `{document_type, s3_key, original_filename}`), optional contact and property fields
- **Output:** `(applicant_id, submission_id, doc_count)`
- **Side effects:**
  - DB: encrypts NIF, computes HMAC index, creates `Applicant`, `Submission` (status `PROCESSING`), `Document` rows (status `UPLOADED`)
  - S3: verifies each `s3_key` exists
  - SQS: publishes one message per document to the extraction queue
- **Limits:** 5 documents per submission (configurable via `max_applicant_documents`)
- **Errors:** `DuplicateApplicantError` if `(nif, form_request_id)` already exists
- **Source:** `src/screening/application/services/submission.py`

### ExtractionService.extract_document

**Worker.** Triggered by an SQS message containing `{document_id, applicant_id}`. Downloads the document, runs Reducto OCR, persists the extraction result, marks the document `EXTRACTED`. When the last document for an applicant transitions to `EXTRACTED`, publishes an `{applicant_id}` message to the screening queue.

- **Inputs:** `document_id`, `applicant_id`
- **Output:** `None`
- **Side effects:**
  - S3: download the file
  - OCR: `Reducto.extract` → structured fields
  - DB: writes `ExtractedData`, updates `Document.status` and `Document.reducto_document_id`
  - SQS: publishes to screening queue when all documents are extracted
- **Idempotency:** if extraction has already succeeded, returns early without re-processing
- **Source:** `src/screening/application/services/extraction.py`
- **Worker entry:** `src/screening/adapters/workers/extraction_processor.py`

### ScreeningService.screen_applicant

**Worker.** Triggered by `APPLICANT_SCREENING_REQUESTED.v1` on the screening command queue. Loads the applicant + all extracted data, runs the LangGraph-based assessor (OpenAI under the hood) to produce a risk level and justification, translates the justification to Portuguese, persists the report, and emits an enriched `APPLICANT_SCREENED.v1` domain event.

- **Inputs:** `applicant_id`, `force?` (default `False`)
- **Output:** `None`
- **Side effects:**
  - LLM: `ScreeningAssessor.assess` (LangGraph + OpenAI)
  - Translator: best-effort translation of justification to pt-PT (logs warning on failure, doesn't fail the screening)
  - DB: writes `ScreeningReport`, updates `Submission.status` to `PROCESSED`, appends a `ScreeningAuditEvent` row
  - Domain events: `EventPublisher.publish(APPLICANT_SCREENED.v1)` with the full payload (applicant, documents, screening result, DTI ratio, income, identity flags). SNS fan-out to `customers-events-queue` and `bookings-events-queue`.
- **Idempotency:** skips if a report already exists, unless `force=True`
- **Source:** `src/screening/application/services/screening.py`
- **Worker entry:** `src/screening/adapters/workers/screening_processor.py:handle_applicant_screening_requested`

## Encryption

NIF (Portuguese tax ID) is sensitive PII. It is encrypted with RSA at rest and indexed via HMAC for lookup:

- RSA keys loaded from env vars (`encryption_public_key`, `encryption_private_key`)
- HMAC key loaded from env (`encryption_hmac_key`, base64-encoded)
- The repository computes `hmac_index` for queries — equality lookups stay fast without storing plaintext

See `src/screening/application/crypto.py` and `src/screening/adapters/database/repositories.py::SqlAlchemyApplicantRepository`.

## Container

`src/screening/container.py` wires three services (`SubmissionService`, `ExtractionService`, `ScreeningService`), all repositories, the SQS publisher and consumer, the AI adapters (Reducto extractor, LangGraph assessor, LangChain translator), and the encryption keys. Built in `src/shared/entrypoints/bootstrap.py::get_screening_container()` and stored on `app.state.screening_container`.
