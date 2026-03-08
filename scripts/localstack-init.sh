#!/bin/bash
set -euo pipefail

echo "Creating SQS queues..."
awslocal sqs create-queue --queue-name core-api-events
awslocal sqs create-queue --queue-name screening-events-queue

echo "LocalStack initialization complete."
