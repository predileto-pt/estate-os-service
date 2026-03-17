#!/bin/bash
set -euo pipefail

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
REGION=$(ec2-metadata --availability-zone | awk '{print $2}' | sed 's/.$//')
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ECR_REGISTRY="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"

aws ecr get-login-password --region "${REGION}" | \
  docker login --username AWS --password-stdin "${ECR_REGISTRY}"

# --- Pull the application image ---
ECR_IMAGE="${ECR_REGISTRY}/customers-dashboard-service:latest"
docker pull "${ECR_IMAGE}"

# --- Fetch secrets from Secrets Manager ---
SECRET_NAME="customers-dashboard-service-prod"
SECRETS=$(aws secretsmanager get-secret-value \
  --secret-id "${SECRET_NAME}" \
  --region "${REGION}" \
  --query SecretString \
  --output text)

# Write secrets as .env file
APP_DIR="/opt/customers-dashboard-service"
mkdir -p "${APP_DIR}"
echo "${SECRETS}" | jq -r 'to_entries[] | "\(.key)=\(.value)"' > "${APP_DIR}/.env"

# Add ECR_IMAGE to .env for docker-compose
echo "ECR_IMAGE=${ECR_IMAGE}" >> "${APP_DIR}/.env"

# --- Copy docker-compose file ---
cat > "${APP_DIR}/docker-compose.yml" << 'COMPOSE'
services:
  api:
    image: ${ECR_IMAGE}
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
cd "${APP_DIR}"
docker compose up -d
