#!/bin/bash
set -euo pipefail

# S3 buckets only — SNS topics and SQS queues are no longer provisioned
# here after the RabbitMQ cutover (ADR-008 addendum 2026-05-13). The
# SNS/SQS-related init steps below this header have been removed; the
# retained SNS+SQS adapter classes in `src/shared/events/adapters/` are
# unit-tested in isolation and don't need a running LocalStack broker.

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

echo "LocalStack initialization complete (S3-only)."
