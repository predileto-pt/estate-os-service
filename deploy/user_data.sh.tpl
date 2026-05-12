#!/bin/bash
set -euo pipefail

# Rendered by Terraform via `templatefile()` - see `terraform/production/
# ec2.tf`. Terraform vars use $${name} here so they survive shell
# expansion at runtime (only $${aws_region} and friends get substituted
# at plan time).

# --- Install Docker ---
dnf update -y
dnf install -y docker curl jq
systemctl enable docker
systemctl start docker
usermod -aG docker ec2-user

# --- Install Docker Compose plugin ---
mkdir -p /usr/local/lib/docker/cli-plugins
curl -SL "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-$(uname -m)" \
  -o /usr/local/lib/docker/cli-plugins/docker-compose
chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

# --- Authenticate to ECR ---
ECR_REGISTRY="${ecr_registry}"
aws ecr get-login-password --region "${aws_region}" | \
  docker login --username AWS --password-stdin "$${ECR_REGISTRY}"

# --- Pull the application image ---
ECR_IMAGE="${ecr_image}"
docker pull "$${ECR_IMAGE}"

# --- Build the .env file ---
#
# Two sources, in order (later writes WIN on duplicates per docker
# compose env_file semantics):
#   1. Real secrets from Secrets Manager (operator-seeded JSON).
#   2. Infrastructure pointers + ECR_IMAGE rendered by Terraform.
#
# Step (2) is the source of truth for queue URLs, topic ARNs, the
# bucket name, and the region - the operator should NOT include these
# in the Secrets Manager JSON. If they do, step (2) overrides cleanly.
APP_DIR="/opt/estate-os-service"
mkdir -p "$${APP_DIR}"

aws secretsmanager get-secret-value \
  --secret-id "${secret_name}" \
  --region "${aws_region}" \
  --query SecretString \
  --output text \
  | jq -r 'to_entries[] | "\(.key)=\(.value)"' > "$${APP_DIR}/.env"

cat >> "$${APP_DIR}/.env" <<EOF
AWS_REGION=${aws_region}
S3_BUCKET_NAME=${s3_bucket_name}
SNS_DOMAIN_EVENTS_TOPIC_ARN_PREFIX=${sns_domain_events_topic_arn_prefix}
SQS_PROPERTY_EXTRACTION_QUEUE_URL=${sqs_property_extraction_queue_url}
SQS_PROPERTY_ENRICHMENT_QUEUE_URL=${sqs_property_enrichment_queue_url}
SQS_LISTINGS_EVENTS_QUEUE_URL=${sqs_listings_events_queue_url}
ECR_IMAGE=${ecr_image}
EOF

# --- Write the docker-compose file ---
cat > "$${APP_DIR}/docker-compose.yml" << 'COMPOSE'
services:
  api:
    image: $${ECR_IMAGE}
    command: ["uv", "run", "uvicorn", "shared.main:app", "--host", "0.0.0.0", "--port", "8000"]
    ports:
      - "8000:8000"
    env_file: .env
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/api/v1/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 15s

COMPOSE

# --- Start the application ---
cd "$${APP_DIR}"
docker compose up -d
