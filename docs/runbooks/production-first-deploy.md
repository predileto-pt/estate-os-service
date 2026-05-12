# Production — first deploy

Operator runbook for the initial provisioning of the production AWS account and the first end-to-end deploy. Read [ADR-018](../adr/018-lambda-as-sqs-worker-runtime.md) first for the architecture; this doc is the sequenced "do these steps in this order" companion.

After the first deploy, day-to-day deploys are automatic (push to `main` → `.github/workflows/deploy.yml`). This runbook is one-shot.

---

## 0. Prerequisites (one-time, before any terraform)

These items live outside terraform and must exist before `terraform init` works.

1. **AWS account + admin IAM** for the bootstrap operator (you). Create an access key locally for `aws configure --profile predileto-prod` or use AWS SSO.

2. **S3 bucket for terraform state.** The backend in `terraform/production/_providers.tf` is hardcoded:
   ```
   bucket = "estate-os-service-prod-terraform-state"
   region = "eu-west-3"
   ```
   Create it once (encryption + versioning + public-access-block on):
   ```bash
   aws s3api create-bucket \
     --bucket estate-os-service-prod-terraform-state \
     --region eu-west-3 \
     --create-bucket-configuration LocationConstraint=eu-west-3
   aws s3api put-bucket-versioning \
     --bucket estate-os-service-prod-terraform-state \
     --versioning-configuration Status=Enabled
   aws s3api put-bucket-encryption \
     --bucket estate-os-service-prod-terraform-state \
     --server-side-encryption-configuration \
       '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
   aws s3api put-public-access-block \
     --bucket estate-os-service-prod-terraform-state \
     --public-access-block-configuration \
       BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
   ```

3. **EC2 keypair for the API instance.** The API EC2 still uses an AWS-managed keypair (separate from the bastion's tfstate-managed one). Create it in the console (`EC2 → Key Pairs → Create`) or:
   ```bash
   aws ec2 create-key-pair \
     --key-name estate-os-service-prod-api \
     --region eu-west-3 \
     --query 'KeyMaterial' --output text > ~/.ssh/estate-os-service-prod-api.pem
   chmod 400 ~/.ssh/estate-os-service-prod-api.pem
   ```
   Set `key_name = "estate-os-service-prod-api"` in `production.tfvars` (step 1 below).

4. **DNS control over `predileto.pt`** (currently Vercel-managed per `_outputs.tf` comments). You'll need to add two CNAMEs after the first `terraform apply` — one for the ACM cert validation, one for the API host. Have access to the DNS provider ready.

5. **GitHub repo settings:**
   - The repo is `predileto-pt/estate-os-service` (hardcoded in `github_oidc.tf`'s `:sub` claim).
   - Create a GitHub `production` environment under repo settings (Settings → Environments → New).
   - You'll add secrets to that environment after step 5 (`AWS_GHA_ROLE_ARN`, `ALB_HOST`) using the terraform outputs.

---

## 1. `production.tfvars`

Create `terraform/production/production.tfvars` (gitignored — never commit). Minimum required values:

```hcl
# EC2 keypair name from prereq step 3.
key_name = "estate-os-service-prod-api"

# Bastion BYOK — paste your laptop's SSH public key contents.
# (Output of `cat ~/.ssh/id_ed25519.pub` on macOS.)
bastion_public_key = "ssh-ed25519 AAAAC3... you@laptop"

# Optional — tighten bastion SSH to a specific IP. Default is 0.0.0.0/0
# with key auth.
# bastion_allowed_cidr = "203.0.113.42/32"

# Lambda consumer flags — keep ALL false for the first apply. Flip them
# only after CI has run and the functions hold real code.
# lambda_consumes_extraction       = false
# lambda_consumes_enrichment       = false
# lambda_consumes_listings_events  = false
```

---

## 2. First `terraform apply`

```bash
cd terraform/production
terraform init        # backend resolves once the state bucket exists
terraform plan  -var-file=production.tfvars -out=tfplan
# review the plan carefully — should be ~80-100 resources created
terraform apply tfplan
```

Expected high-level resources:

- **Networking** — VPC + 9 subnets (3 public, 3 private app, 3 private data), IGW, NAT EC2 (`t4g.nano`, single AZ), route tables.
- **Security groups** — `alb_sg`, `ec2_sg`, `bastion_sg`, `lambda_sg`, `nat_sg`.
- **Public surface** — ACM cert (will be in `PENDING_VALIDATION` until step 3), ALB, bastion EC2 + EIP.
- **Private surface** — API EC2 (no public IP), 3× Lambda functions (placeholder code, mappings disabled), 3× SQS queues + DLQs, KMS key + Secrets Manager container (empty), S3 documents bucket.
- **Events** — 8 SNS topics, 8 SNS→SQS subscriptions, SQS queue policy.
- **IAM** — EC2 role + instance profile (CloudWatch, Secrets, S3, SQS, SNS, ECR, SSM agent), Lambda role (SQS consume, SNS publish, S3 R/W/D/List, Secrets, KMS, BasicExecution, VPCAccess), GitHub OIDC provider + role (ECR push, SSM, Lambda update, layer publish).
- **ECR** — repository.

**Capture outputs:**
```bash
terraform output  # note: alb_dns_name, acm_validation_record_name,
                  # acm_validation_record_value, bastion_public_ip,
                  # github_actions_role_arn, ec2_instance_id, etc.
```

---

## 3. DNS records — ACM validation + ALB

In the DNS provider (Vercel for `predileto.pt`):

1. **ACM cert validation** — add a CNAME from `acm_validation_record_name` → `acm_validation_record_value`. Wait 1-10 min for the cert to flip from `PENDING_VALIDATION` to `ISSUED`. You can re-run `terraform plan` to see when it settles.

2. **API host** — add a CNAME from `api.predileto.pt` → `alb_dns_name`. After DNS propagation, HTTPS will serve from `https://api.predileto.pt` once the API container is running (step 6).

---

## 4. Populate Secrets Manager

The `aws_secretsmanager_secret.app_secrets` container exists after step 2, but its value is empty. Until you populate it, the EC2 boot script will write an empty `.env` and the API will run with `Settings()` defaults (which means broken Supabase/OpenAI/Pinecone/etc connections).

The secret payload is a single JSON object with one key per `Settings` field. Build it from your existing local `.env` (or from `.env.example`) and seed:

```bash
# Example — adapt to your real values. Every field in
# src/shared/config.py:Settings that doesn't have a sane default needs
# a value here. See ADR-018's "Audit aws_secretsmanager_secret.app_secrets"
# follow-up.
cat > /tmp/app-secrets.json <<EOF
{
  "APP_ENV": "production",
  "LOG_LEVEL": "info",
  "SUPABASE_URL": "https://....supabase.co",
  "SUPABASE_SERVICE_ROLE_KEY": "...",
  "SUPABASE_JWT_SECRET": "...",
  "DATABASE_URL": "postgresql+asyncpg://...",
  "PORTAL_DATABASE_URL": "postgresql+asyncpg://...",
  "SUPABASE_PORTAL_URL": "https://....supabase.co",
  "SUPABASE_PORTAL_JWT_SECRET": "...",
  "OPENAI_API_KEY": "sk-...",
  "REDUCTO_API_KEY": "...",
  "PINECONE_API_KEY": "...",
  "PINECONE_HOST": "...",
  "GOOGLE_MAPS_API_KEY": "...",
  "RESEND_API_KEY": "re_...",
  "STRIPE_API_KEY": "sk_live_...",
  "STRIPE_WEBHOOK_SECRET": "whsec_...",
  "AWS_REGION": "eu-west-3",
  "S3_BUCKET_NAME": "estate-os-service-prod-property-documents",
  "SQS_PROPERTY_EXTRACTION_QUEUE_URL": "https://sqs.eu-west-3.amazonaws.com/...",
  "SQS_PROPERTY_ENRICHMENT_QUEUE_URL": "https://sqs.eu-west-3.amazonaws.com/...",
  "SQS_LISTINGS_EVENTS_QUEUE_URL": "https://sqs.eu-west-3.amazonaws.com/...",
  "SNS_DOMAIN_EVENTS_TOPIC_ARN_PREFIX": "arn:aws:sns:eu-west-3:...:estate-os-service-prod-domain-events-",
  "SESSION_SIGNING_KEYS": "...",
  "SESSION_SIGNING_ACTIVE_KEY": "1",
  "ENCRYPTION_PUBLIC_KEY": "...",
  "ENCRYPTION_PRIVATE_KEY": "...",
  "ENCRYPTION_HMAC_KEY": "..."
}
EOF

aws secretsmanager put-secret-value \
  --secret-id estate-os-service-prod \
  --secret-string file:///tmp/app-secrets.json \
  --region eu-west-3

rm /tmp/app-secrets.json   # don't leave secrets on disk
```

The queue URLs and SNS topic ARN prefix come from `terraform output` (step 2's capture).

---

## 5. GitHub `production` environment secrets

Set these in `Settings → Environments → production → Environment secrets`:

| Secret | Value |
|---|---|
| `AWS_GHA_ROLE_ARN` | `terraform output -raw github_actions_role_arn` |
| `ALB_HOST` | `terraform output -raw alb_dns_name` (or `api.predileto.pt` once DNS resolves) |

---

## 6. First CI deploy

Push to `main` (or trigger `Deploy to production` via `Actions → Run workflow`). The workflow does:

1. **Build + push Docker image** — both `:SHA` and `:latest` to ECR.
2. **Build Lambda zips** — deps layer (`uv sync --no-dev` → `layer/python/lib/python3.13/site-packages/`) + app zip (`src/`).
3. **Publish Lambda deps layer** — `aws lambda publish-layer-version`, capture ARN.
4. **Update each worker function** — `update-function-code` + `wait function-updated` + `update-function-configuration --layers <ARN>`.
5. **EC2 SSM redeploy** — pull image, run admin + portal alembic migrations in a one-shot container, `docker compose up -d`.
6. **Health check** — hit `https://${ALB_HOST}/api/v1/health` until 200 (or 60s timeout).

After this completes:

- ECR has the first real image.
- Each Lambda function has real code + the deps layer attached (no longer the placeholder).
- The API EC2 is running uvicorn behind the ALB.
- The Lambda functions exist but are NOT consuming SQS yet (`lambda_consumes_*` flags still `false`).

Spot-check in the console:

- **Lambda → extraction-worker → Code** — confirm "Code size" > a few MB (not the tiny placeholder).
- **Lambda → extraction-worker → Configuration → Layers** — confirm the `estate-os-service-prod-deps` layer is attached.
- **ALB → Target Groups** — API EC2 instance shows `healthy`.
- **`curl -fsS https://api.predileto.pt/api/v1/health`** returns 200.

---

## 7. Enable Lambda consumers (per-queue rollout)

Now you can flip the consumer flags. Start with the lowest-risk one and verify before moving on.

```hcl
# production.tfvars
lambda_consumes_listings_events = true
```

```bash
terraform apply -var-file=production.tfvars
```

Watch:
- **CloudWatch Logs → /aws/lambda/estate-os-service-prod-listings-events-worker** — invocation logs appear when an event lands.
- **SQS → estate-os-service-prod-listings-events** — `Messages Available` stays near 0; `Messages In Flight` spikes only briefly.
- **DLQ depth** — should stay 0.

If stable for 24h, repeat for `lambda_consumes_extraction = true`, then `lambda_consumes_enrichment = true`.

---

## 8. Operator workflows

### SSH into the API EC2 via the bastion

`~/.ssh/config` snippet:

```
Host predileto-bastion
  HostName <terraform output -raw bastion_public_ip>
  User ec2-user
  IdentityFile ~/.ssh/id_ed25519     # the private key matching var.bastion_public_key

Host predileto-api
  HostName <private IP from terraform output ec2_instance_id → console>
  User ec2-user
  IdentityFile ~/.ssh/estate-os-service-prod-api.pem
  ProxyJump predileto-bastion
```

Then `ssh predileto-api` works directly.

### SSM Session Manager (no SSH needed)

```bash
aws ssm start-session --target $(terraform output -raw ec2_instance_id) --region eu-west-3
```

Requires the `Session Manager Plugin` on your laptop (`brew install --cask session-manager-plugin`). Uses IAM auth; no inbound ports involved.

### Trigger a redeploy without pushing a commit

`Actions → Deploy to production → Run workflow`. Useful after rotating a Secrets Manager value to pick up the new env on the EC2.

### Emergency fallback — run a worker on the EC2

If a Lambda function misbehaves and you need to drain its queue while you debug:

```bash
ssh predileto-api    # or via SSM
cd /opt/estate-os-service
# Stop Lambda consumption:
#   (locally) terraform apply with var.lambda_consumes_<queue> = false
# Then start the fallback profile service:
docker compose --profile fallback up -d listings-events-worker   # or extraction-worker / enrichment-worker
docker compose logs -f listings-events-worker
```

The fallback service runs the same handler code from the same image (different command). Same `.env`, same IAM via the EC2 instance profile (which has SQS consume + SNS publish perms for exactly this case).

---

## 9. Things that will bite you if you skip them

- **Don't flip a `lambda_consumes_*` flag to `true` before CI has run.** The function still holds the placeholder code from `data.archive_file.lambda_placeholder` — every invocation raises and a few hundred messages end up in the DLQ.
- **Don't forget step 4.** An empty Secrets Manager value means the EC2 boots with default config — broken Supabase, broken everything.
- **Don't change `prefix_name`** after the first apply. Most resource names are derived from it; changing it forces wholesale recreation.
- **Don't commit `production.tfvars`** — it has the bastion public key and the EC2 keypair name. Both are low-sensitivity individually but the whole file telegraphs your deploy identity.
- **Don't commit any `*.pem`** — the `terraform/production/` directory is the working dir; check `.gitignore`.
