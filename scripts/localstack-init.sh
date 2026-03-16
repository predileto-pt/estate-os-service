#!/bin/bash
set -euo pipefail

echo "Creating SQS queues..."
awslocal sqs create-queue --queue-name core-api-events
awslocal sqs create-queue --queue-name screening-events-queue
awslocal sqs create-queue --queue-name property-extraction-queue

echo "Creating S3 buckets..."
awslocal s3 mb s3://property-documents

echo "LocalStack initialization complete."
