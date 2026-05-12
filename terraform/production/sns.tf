###############################################################################
# SNS — domain event fan-out (ADR-008).
#
# Topic naming: `${prefix_name}-domain-events-{event_type}` where
# `event_type` has dots replaced with dashes (e.g. PROPERTY_UPDATED.v1
# → PROPERTY_UPDATED-v1). Matches what
# `shared.events.adapters.sns_event_publisher` constructs at publish time.
#
# Listings-events queue subscriptions: seven topics consumed by
# `listings.entrypoints.events_worker` per its docstring:
#   - PROPERTY_CREATED/UPDATED/DELETED/PUBLISHED/UNPUBLISHED  → projector
#   - PROPERTY_LISTING_NEEDS_ADDRESS_ENRICHMENT              → enrichment
#   - PROPERTY_LISTING_UPDATED                                → embedding
#   - PROPERTY_LISTING_DELETED                                → cleanup
#
# Other bounded contexts (bookings, applicant screening, customers,
# subscriptions, organizations) publish their own event types but their
# workers are not deployed yet. Adding those topics when those workers
# land is a follow-up.
###############################################################################

locals {
  domain_event_topic_prefix = "${var.prefix_name}-domain-events-"

  # ARN-shaped prefix used both as a Terraform output (consumed by EC2
  # + Lambda env wiring) and by the per-event-type topic ARN
  # construction. The publisher (`shared.events.adapters.sns_event_publisher`)
  # concatenates `<prefix><event_type.replace('.', '-')>` to resolve
  # each topic ARN at publish time.
  sns_domain_events_topic_arn_prefix = "arn:aws:sns:${var.aws_region}:${local.account_id}:${local.domain_event_topic_prefix}"

  # Property write-side events emitted by the `properties` context.
  property_event_types = [
    "PROPERTY_CREATED-v1",
    "PROPERTY_UPDATED-v1",
    "PROPERTY_DELETED-v1",
    "PROPERTY_PUBLISHED-v1",
    "PROPERTY_UNPUBLISHED-v1",
  ]

  # Listings-internal events emitted by the projector worker itself.
  property_listing_event_types = [
    "PROPERTY_LISTING_NEEDS_ADDRESS_ENRICHMENT-v1",
    "PROPERTY_LISTING_UPDATED-v1",
    "PROPERTY_LISTING_DELETED-v1",
  ]

  # Topics that the listings-events queue subscribes to. Every event
  # type above (both groups) is consumed by `events_worker.py`.
  listings_subscribed_event_types = concat(
    local.property_event_types,
    local.property_listing_event_types,
  )
}

# One topic per event type. Per ADR-008 the contract is "topic-per-event-
# type"; adding a new event type means adding it to one of the lists
# above (and to localstack-init.sh for local dev).
resource "aws_sns_topic" "property_events" {
  for_each = toset(local.property_event_types)
  name     = "${local.domain_event_topic_prefix}${each.key}"
}

resource "aws_sns_topic" "listing_events" {
  for_each = toset(local.property_listing_event_types)
  name     = "${local.domain_event_topic_prefix}${each.key}"
}

# Topic ARN prefix the publisher expects. We use this in the EC2 .env
# so the publisher resolves the right ARN per event type.
output "sns_domain_events_topic_arn_prefix" {
  description = "Prefix the SNS publisher concatenates with the dash-mangled event_type to get a topic ARN. Goes in `.env` as `SNS_DOMAIN_EVENTS_TOPIC_ARN_PREFIX`."
  value       = local.sns_domain_events_topic_arn_prefix
}

###############################################################################
# Subscriptions — listings-events queue subscribes to every relevant topic.
#
# `raw_message_delivery = true` strips the SNS envelope so SQS messages
# carry just the DomainEvent JSON the worker expects (no double-decoding
# of the SNS wrapper). Matches the localstack pattern.
###############################################################################

resource "aws_sns_topic_subscription" "listings_property" {
  for_each             = toset(local.property_event_types)
  topic_arn            = aws_sns_topic.property_events[each.key].arn
  protocol             = "sqs"
  endpoint             = module.listings_events_queue.arn
  raw_message_delivery = true
}

resource "aws_sns_topic_subscription" "listings_internal" {
  for_each             = toset(local.property_listing_event_types)
  topic_arn            = aws_sns_topic.listing_events[each.key].arn
  protocol             = "sqs"
  endpoint             = module.listings_events_queue.arn
  raw_message_delivery = true
}

# SQS policy allowing the seven SNS topics to deliver into the queue.
# Without this, SNS publishes succeed but the messages silently never
# arrive (SNS->SQS auth is on the *queue* side).
resource "aws_sqs_queue_policy" "listings_events_from_sns" {
  queue_url = module.listings_events_queue.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AllowSNSDelivery"
        Effect    = "Allow"
        Principal = { Service = "sns.amazonaws.com" }
        Action    = "sqs:SendMessage"
        Resource  = module.listings_events_queue.arn
        Condition = {
          ArnEquals = {
            "aws:SourceArn" = concat(
              [for t in aws_sns_topic.property_events : t.arn],
              [for t in aws_sns_topic.listing_events : t.arn],
            )
          }
        }
      }
    ]
  })
}
