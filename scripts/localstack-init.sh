#!/bin/bash
set -euo pipefail

echo "Creating SQS queues..."
awslocal sqs create-queue --queue-name domain-events
awslocal sqs create-queue --queue-name property-extraction-queue
awslocal sqs create-queue --queue-name applicant-extraction-queue
awslocal sqs create-queue --queue-name applicant-screening-queue

awslocal sqs create-queue --queue-name contract-ingestion-queue
awslocal sqs create-queue --queue-name contract-analysis-queue
awslocal sqs create-queue --queue-name contract-ingestion-dlq
awslocal sqs create-queue --queue-name contract-analysis-dlq

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

echo "LocalStack initialization complete."
