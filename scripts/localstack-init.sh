#!/bin/bash
set -euo pipefail

# ---------- S3 buckets ----------------------------------------------------

echo "Creating S3 buckets..."
awslocal s3 mb s3://property-documents
awslocal s3 mb s3://contract-intelligence-documents

echo "Configuring S3 bucket CORS..."
awslocal s3api put-bucket-cors --bucket property-documents --cors-configuration '{
  "CORSRules": [
    {
      "AllowedOrigins": ["*"],
      "AllowedMethods": ["GET", "PUT", "POST"],
      "AllowedHeaders": ["*"],
      "ExposeHeaders": ["ETag"]
    }
  ]
}'

awslocal s3api put-bucket-cors --bucket contract-intelligence-documents --cors-configuration '{
  "CORSRules": [
    {
      "AllowedOrigins": ["*"],
      "AllowedMethods": ["GET", "PUT", "POST"],
      "AllowedHeaders": ["*"],
      "ExposeHeaders": ["ETag"]
    }
  ]
}'

# ---------- SNS topics (domain events — one topic per .v1 event type) ----

echo "Creating SNS topics..."
# The publisher resolves the topic ARN by `${prefix}${event_type with dots→dashes}`.
# For LocalStack, the prefix is `arn:aws:sns:us-east-1:000000000000:domain-events-`.
awslocal sns create-topic --name domain-events-PROPERTY_CREATED-v1
awslocal sns create-topic --name domain-events-APPLICANT_SCREENED-v1
awslocal sns create-topic --name domain-events-USER_REGISTERED-v1
awslocal sns create-topic --name domain-events-SUBSCRIPTION_CREATED-v1
awslocal sns create-topic --name domain-events-SUBSCRIPTION_UPDATED-v1
awslocal sns create-topic --name domain-events-NOTIFICATION_SENT-v1
awslocal sns create-topic --name domain-events-MEMBER_INVITED-v1
awslocal sns create-topic --name domain-events-MEMBER_JOINED-v1
awslocal sns create-topic --name domain-events-MEMBER_REMOVED-v1
awslocal sns create-topic --name domain-events-MEMBER_ROLE_CHANGED-v1
awslocal sns create-topic --name domain-events-CONTRACT_ANALYZED-v1
awslocal sns create-topic --name domain-events-TEMPLATE_PUBLISHED-v1
awslocal sns create-topic --name domain-events-CONTRACT_GENERATED-v1

# ---------- Command queues (+ DLQs with redrive policies) -----------------

echo "Creating command-queue DLQs first (redrive targets)..."
awslocal sqs create-queue --queue-name property-extraction-dlq
awslocal sqs create-queue --queue-name applicant-extraction-dlq
awslocal sqs create-queue --queue-name applicant-screening-dlq
awslocal sqs create-queue --queue-name contract-ingestion-dlq
awslocal sqs create-queue --queue-name contract-analysis-dlq

echo "Creating command queues with redrive policies..."
# maxReceiveCount=5 per spec §Failure semantics.
awslocal sqs create-queue --queue-name property-extraction-queue \
  --attributes '{"RedrivePolicy": "{\"deadLetterTargetArn\":\"arn:aws:sqs:us-east-1:000000000000:property-extraction-dlq\",\"maxReceiveCount\":\"5\"}"}'
awslocal sqs create-queue --queue-name applicant-extraction-queue \
  --attributes '{"RedrivePolicy": "{\"deadLetterTargetArn\":\"arn:aws:sqs:us-east-1:000000000000:applicant-extraction-dlq\",\"maxReceiveCount\":\"5\"}"}'
awslocal sqs create-queue --queue-name applicant-screening-queue \
  --attributes '{"RedrivePolicy": "{\"deadLetterTargetArn\":\"arn:aws:sqs:us-east-1:000000000000:applicant-screening-dlq\",\"maxReceiveCount\":\"5\"}"}'
awslocal sqs create-queue --queue-name contract-ingestion-queue \
  --attributes '{"RedrivePolicy": "{\"deadLetterTargetArn\":\"arn:aws:sqs:us-east-1:000000000000:contract-ingestion-dlq\",\"maxReceiveCount\":\"5\"}"}'
awslocal sqs create-queue --queue-name contract-analysis-queue \
  --attributes '{"RedrivePolicy": "{\"deadLetterTargetArn\":\"arn:aws:sqs:us-east-1:000000000000:contract-analysis-dlq\",\"maxReceiveCount\":\"5\"}"}'

# ---------- Domain-event queues (per-context + DLQs) ---------------------

echo "Creating domain-event queue DLQs..."
awslocal sqs create-queue --queue-name customers-events-dlq
awslocal sqs create-queue --queue-name bookings-events-dlq
awslocal sqs create-queue --queue-name properties-events-dlq

echo "Creating per-context domain-event queues with redrive policies..."
awslocal sqs create-queue --queue-name customers-events-queue \
  --attributes '{"RedrivePolicy": "{\"deadLetterTargetArn\":\"arn:aws:sqs:us-east-1:000000000000:customers-events-dlq\",\"maxReceiveCount\":\"5\"}"}'
awslocal sqs create-queue --queue-name bookings-events-queue \
  --attributes '{"RedrivePolicy": "{\"deadLetterTargetArn\":\"arn:aws:sqs:us-east-1:000000000000:bookings-events-dlq\",\"maxReceiveCount\":\"5\"}"}'
awslocal sqs create-queue --queue-name properties-events-queue \
  --attributes '{"RedrivePolicy": "{\"deadLetterTargetArn\":\"arn:aws:sqs:us-east-1:000000000000:properties-events-dlq\",\"maxReceiveCount\":\"5\"}"}'

# Legacy shared queue — kept for the one-week cutover drain per §Rollout.
awslocal sqs create-queue --queue-name domain-events

# ---------- SNS → SQS subscriptions --------------------------------------

echo "Subscribing context queues to SNS topics..."

# customers — APPLICANT_SCREENED.v1 (send the screening-complete email)
awslocal sns subscribe \
  --topic-arn arn:aws:sns:us-east-1:000000000000:domain-events-APPLICANT_SCREENED-v1 \
  --protocol sqs \
  --notification-endpoint arn:aws:sqs:us-east-1:000000000000:customers-events-queue

# bookings — APPLICANT_SCREENED.v1 (create booking applicant)
awslocal sns subscribe \
  --topic-arn arn:aws:sns:us-east-1:000000000000:domain-events-APPLICANT_SCREENED-v1 \
  --protocol sqs \
  --notification-endpoint arn:aws:sqs:us-east-1:000000000000:bookings-events-queue

# properties — PROPERTY_CREATED.v1 (discover amenities)
awslocal sns subscribe \
  --topic-arn arn:aws:sns:us-east-1:000000000000:domain-events-PROPERTY_CREATED-v1 \
  --protocol sqs \
  --notification-endpoint arn:aws:sqs:us-east-1:000000000000:properties-events-queue

echo "LocalStack initialization complete."
