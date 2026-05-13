"""Canonical event type constants.

Every constant is versioned via a `.v1` suffix on the string value
(mapped to a dash in SNS topic names — see `SNSEventPublisher._topic_suffix`).
Schema evolution is "publish V2 alongside V1, migrate consumers, drop V1".

Events and commands live side-by-side: both use the same `DomainEvent`
envelope, same `EventBusWorker`, same handler signature. The distinction is
only in HOW they're published — domain events via topic-exchange fan-out
(`EventPublisher`), commands via direct send (`CommandPublisher`).
"""

# --- Domain events (broadcast via SNS) ---

# Properties — carried-state lifecycle events (see
# `docs/features/listings.md` + the carried-state spec).
PROPERTY_CREATED_V1 = "PROPERTY_CREATED.v1"
PROPERTY_UPDATED_V1 = "PROPERTY_UPDATED.v1"
PROPERTY_DELETED_V1 = "PROPERTY_DELETED.v1"
PROPERTY_PUBLISHED_V1 = "PROPERTY_PUBLISHED.v1"
# Symmetric to PUBLISHED — distinct event so subscribers (notifications,
# analytics) can treat "took off market" differently from "deleted from
# system". The listings projector treats both UNPUBLISHED and DELETED
# the same way (delete the property_listings row); other subscribers
# may not.
PROPERTY_UNPUBLISHED_V1 = "PROPERTY_UNPUBLISHED.v1"

# Read-model enrichment (listings side)
PROPERTY_LISTING_NEEDS_ADDRESS_ENRICHMENT_V1 = "PROPERTY_LISTING_NEEDS_ADDRESS_ENRICHMENT.v1"
# Listings-side domain event published by the projector after every
# applied upsert. The embedding handler subscribes via SNS fan-out
# (same shape as NEEDS_ADDRESS_ENRICHMENT), runs on the same listings
# queue. Spec `2026-05-listing-semantic-search`.
PROPERTY_LISTING_UPDATED_V1 = "PROPERTY_LISTING_UPDATED.v1"
PROPERTY_LISTING_DELETED_V1 = "PROPERTY_LISTING_DELETED.v1"

# Applicant Screening
APPLICANT_SCREENED_V1 = "APPLICANT_SCREENED.v1"

# Customer Management
USER_REGISTERED_V1 = "USER_REGISTERED.v1"
SUBSCRIPTION_CREATED_V1 = "SUBSCRIPTION_CREATED.v1"
SUBSCRIPTION_UPDATED_V1 = "SUBSCRIPTION_UPDATED.v1"
NOTIFICATION_SENT_V1 = "NOTIFICATION_SENT.v1"
MEMBER_INVITED_V1 = "MEMBER_INVITED.v1"
MEMBER_JOINED_V1 = "MEMBER_JOINED.v1"
MEMBER_REMOVED_V1 = "MEMBER_REMOVED.v1"
MEMBER_ROLE_CHANGED_V1 = "MEMBER_ROLE_CHANGED.v1"

# Contract Intelligence
CONTRACT_ANALYZED_V1 = "CONTRACT_ANALYZED.v1"
TEMPLATE_PUBLISHED_V1 = "TEMPLATE_PUBLISHED.v1"
CONTRACT_GENERATED_V1 = "CONTRACT_GENERATED.v1"


# --- Commands (point-to-point via SQS) ---

# Properties (existing pathway — shape of envelope already canonical via
# the subclass `to_dict()`; this spec replaces the subclass publishes with
# direct `DomainEvent(event_type=..._V1, data=...)` constructors)
PROPERTY_EXTRACTION_REQUESTED_V1 = "PROPERTY_EXTRACTION_REQUESTED.v1"
BATCH_PROPERTY_EXTRACTION_REQUESTED_V1 = "BATCH_PROPERTY_EXTRACTION_REQUESTED.v1"
ENRICH_PROPERTY_REQUESTED_V1 = "ENRICH_PROPERTY_REQUESTED.v1"

# Screening (new — these commands are published today as flat payloads via
# the legacy `SQSMessagePublisher`; this spec moves them onto the canonical
# envelope via `SQSCommandPublisher`)
APPLICANT_EXTRACTION_REQUESTED_V1 = "APPLICANT_EXTRACTION_REQUESTED.v1"
APPLICANT_SCREENING_REQUESTED_V1 = "APPLICANT_SCREENING_REQUESTED.v1"

# Contract intelligence (new — same story)
DOCUMENT_INGESTION_REQUESTED_V1 = "DOCUMENT_INGESTION_REQUESTED.v1"
DOCUMENT_ANALYSIS_REQUESTED_V1 = "DOCUMENT_ANALYSIS_REQUESTED.v1"
