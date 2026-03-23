#!/bin/bash
set -euo pipefail

echo "Creating SQS queues..."
awslocal sqs create-queue --queue-name core-api-events
awslocal sqs create-queue --queue-name screening-events-queue
awslocal sqs create-queue --queue-name property-extraction-queue
awslocal sqs create-queue --queue-name property-discovery-queue

echo "Creating S3 buckets..."
awslocal s3 mb s3://property-documents

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
