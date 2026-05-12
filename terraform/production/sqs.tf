###############################################################################
# SQS — three queues consumed by Lambda functions (see `lambda.tf`):
#
#   1. property-extraction  — command queue. API publishes; the
#      `extraction-worker` Lambda consumes (entrypoint
#      `properties.entrypoints.lambda_extraction.handler`). Long-running
#      Reducto + LLM extraction; 12 min visibility matches the Lambda
#      timeout.
#
#   2. property-enrichment  — command queue. API publishes (via
#      `EnqueueEnrichProperty`); the `enrichment-worker` Lambda consumes
#      (entrypoint `properties.entrypoints.lambda_enrichment.handler`).
#      Google Places fan-out + LLM locality filter; 15 min visibility
#      matches the Lambda timeout (reduced from 30 min when running on
#      EC2; real runs stay well under 15 min — ADR-018).
#
#   3. listings-events      — domain-event fan-in queue. Subscribed (via
#      `sns.tf`) to seven SNS topics; the `listings-events-worker`
#      Lambda consumes (entrypoint `listings.entrypoints.lambda_events.handler`).
#      Short messages, 60 s visibility. Per-handler DLQ semantics from
#      ADR-008.
#
# Per-queue visibility >= the matching Lambda timeout is the contract:
# Lambda holds the message invisible for the duration of the invocation;
# anything less would let SQS redeliver while a handler is still running.
#
# Fallback path: `deploy/docker-compose.prod.yml` exposes the same workers
# under `profiles: [fallback]` for emergency consumption from the EC2.
###############################################################################

module "extraction_queue" {
  source = "../modules/sqs"

  sqs_name                       = "${var.prefix_name}-property-extraction"
  environment                    = "production"
  sqs_visibility_timeout_seconds = 720
  create_dlq                     = true
  sqs_max_receive_count          = 3
}

module "enrichment_queue" {
  source = "../modules/sqs"

  sqs_name                       = "${var.prefix_name}-property-enrichment"
  environment                    = "production"
  sqs_visibility_timeout_seconds = 900
  create_dlq                     = true
  sqs_max_receive_count          = 3
}

module "listings_events_queue" {
  source = "../modules/sqs"

  sqs_name                       = "${var.prefix_name}-listings-events"
  environment                    = "production"
  sqs_visibility_timeout_seconds = 60
  create_dlq                     = true
  sqs_max_receive_count          = 5
}
