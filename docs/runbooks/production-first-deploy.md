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

5. **CAA pre-check on `predileto.pt`.** This is the single biggest source of pain on a first deploy — skip it and you'll spend hours stuck in a `PENDING_VALIDATION` → `FAILED` loop with no clear error message.

   CAA (Certification Authority Authorization) records are a DNS-level allowlist saying "only these CAs may issue TLS certs for this domain." If the apex has CAA records that don't include Amazon, ACM will fail every validation regardless of how perfect the CNAME is.

   Check before you `apply`:

   ```bash
   dig +short CAA predileto.pt @8.8.8.8
   ```

   Three outcomes:

   - **No output** → no CAA, any CA may issue. Skip the rest of this step.
   - **Output mentions `amazon.com`, `amazontrust.com`, or `awstrust.com`** → Amazon is already authorised. Skip.
   - **Output lists other CAs only** (e.g. `letsencrypt.org`, `pki.goog`, `sectigo.com`) → **add Amazon now**, before the first `terraform apply`. In Vercel DNS:

     | Field | Value |
     |---|---|
     | Type | `CAA` |
     | Name | `@` (apex; leave blank in Vercel) |
     | Flags | `0` |
     | Tag | `issue` |
     | Value | `amazon.com` |

     If Vercel exposes a single combined Value field instead, paste: `0 issue "amazon.com"` (literal quotes).

     Verify within ~1 min:

     ```bash
     dig +short CAA predileto.pt @8.8.8.8
     # Should now include: 0 issue "amazon.com"
     ```

   The existing CAA records you might already see (Let's Encrypt etc.) are typically added by a previous CA's setup wizard or a security-hardening checklist. Keep them — you're adding a fourth entry, not replacing.

6. **GitHub repo settings:**
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

You need to add **two CNAMEs** to Vercel's DNS for `predileto.pt`. Skipping the second is a common foot-gun — the cert validates fine but no traffic reaches the ALB because `api.predileto.pt` doesn't resolve. The 502 you'd see is misleading (it implies traffic reached *something*); the actual symptom of a missing host CNAME is `NXDOMAIN` on `dig api.predileto.pt`.

| # | Type | Name in Vercel | Value | Purpose |
|---|---|---|---|---|
| 1 | CNAME | `_<hex>.api` | `_<hex>.<region>.acm-validations.aws` | Lets ACM issue + renew the cert |
| 2 | CNAME | `api` | `<alb-name>.elb.amazonaws.com` | Routes real HTTPS traffic to the ALB |

Both Name fields are **prefixes only** — Vercel auto-appends `.predileto.pt`. Pasting the full FQDN gives you `_xyz.api.predileto.pt.predileto.pt`, which silently doesn't resolve.

### CNAME #1 — ACM cert validation

Add a CNAME with:

- `Name`: the prefix-only portion of `acm_validation_record_name` (strip the trailing `.predileto.pt`).
- `Value`: full string from `acm_validation_record_value` (Vercel normalises trailing dots).

Verify the record is live before waiting on ACM:

```bash
dig +short CNAME _<validation-prefix>.api.predileto.pt @8.8.8.8
# Should return the acm-validations.aws target. Empty = Vercel didn't save the record.
```

Then poll ACM (1–10 min once DNS is live + CAA is correct):

```bash
aws acm describe-certificate \
  --certificate-arn $(terraform output -raw acm_cert_arn) \
  --region eu-west-3 --query 'Certificate.Status' --output text
# Expect: ISSUED
```

### CNAME #2 — API host

Add a CNAME with:

- `Name`: `api` (just the subdomain prefix — Vercel auto-appends `.predileto.pt`).
- `Value`: output of `terraform output -raw alb_dns_name` (looks like `estate-os-service-prod-alb-123456.eu-west-3.elb.amazonaws.com`).

This is the record that actually routes traffic. Without it, the ACM cert can be perfectly valid and the ALB perfectly healthy, but `https://api.predileto.pt` returns DNS resolution failure because no public DNS entry exists for that hostname.

Verify:

```bash
dig +short CNAME api.predileto.pt @8.8.8.8
# Should return the ALB DNS name. Empty = the host CNAME isn't set up yet.

# Once dig returns the ALB hostname AND the cert is ISSUED AND the API
# container is running (step 6), this should return 2xx:
curl -i https://api.predileto.pt/api/v1/health
```

### If the cert flips to `FAILED`

ACM doesn't retry failed certs — once it's `FAILED`, it's dead. Recovery is a delete-and-recreate cycle. Root cause is almost always one of:

- **CAA blocking Amazon** — re-check prerequisite step 5. `dig +short CAA predileto.pt` must include Amazon.
- **CNAME `Name` field contains the full FQDN** instead of just the subdomain prefix (see step 1 above).
- **CNAME `Value` doesn't match exactly** what ACM expected — character-for-character (trailing dot doesn't matter; the body must match).

Fix the root cause **first**. Then recreate:

```bash
cd terraform/production

# Drop the failed cert from state.
terraform state list | grep acm   # find the exact resource address
terraform state rm <that address>   # e.g. module.acm.aws_acm_certificate.this

# Delete in AWS.
aws acm delete-certificate \
  --certificate-arn <failed-cert-arn> \
  --region eu-west-3

# Recreate via terraform — partial-failure on the listener is expected.
terraform apply -var-file=production.tfvars

# Each new cert has a NEW validation token. Read the fresh values:
terraform output acm_validation_record_name
terraform output acm_validation_record_value

# Update (don't duplicate) the Vercel CNAME with the new Name and Value.
# Wait for ISSUED, then final apply.
```

Every recreation forces a new Vercel CNAME edit. If the underlying issue (CAA, name format) isn't fixed, you spin in this loop forever — each cert burns 5–10 min before failing. Don't proceed to apply until both the CAA check and the DNS check from step 1 are green.

---

## 4. Populate Secrets Manager

The `aws_secretsmanager_secret.app_secrets` container exists after step 2, but its value is empty. Until you populate it, the EC2 boot script will write a `.env` with only the Terraform-injected infrastructure pointers and the API will run with `Settings()` defaults for everything else (which means broken Supabase/OpenAI/Pinecone/etc connections).

**Secrets Manager holds only true secrets — never infrastructure pointers.** Queue URLs, the SNS topic ARN prefix, the S3 bucket name, and `AWS_REGION` are injected automatically:

- On EC2: via `templatefile()` rendering them into `user_data.sh`, which writes them to `.env` after the Secrets Manager merge so they always win.
- On Lambda: via each function's `environment.variables` block in `lambda.tf`.

So the secret payload is short — only the values Terraform genuinely doesn't know:

```bash
# Build the JSON from your local .env values. Don't include queue URLs,
# topic ARN, bucket name, or AWS_REGION — Terraform injects those.
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

If you do include infrastructure pointers in the JSON by mistake, the boot script's templated block still overrides them — no harm done, just clutter.

---

## 5. GitHub `production` environment secrets

Set these in `Settings → Environments → production → Environment secrets`:

| Secret             | Value                                                                          |
| ------------------ | ------------------------------------------------------------------------------ |
| `AWS_GHA_ROLE_ARN` | `terraform output -raw github_actions_role_arn`                                |
| `ALB_HOST`         | `terraform output -raw alb_dns_name` (or `api.predileto.pt` once DNS resolves) |

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

- **Don't skip the CAA pre-check in prerequisite step 5.** If the domain has restrictive CAA records that don't include Amazon, every ACM cert you create will `PENDING_VALIDATION` → `FAILED` regardless of DNS correctness. You'll burn an hour minimum before realising the error message ("must have a fully-qualified domain name, a supported signature, and a supported key size") doesn't actually mean what it says.
- **Don't flip a `lambda_consumes_*` flag to `true` before CI has run.** The function still holds the placeholder code from `data.archive_file.lambda_placeholder` — every invocation raises and a few hundred messages end up in the DLQ.
- **Don't forget step 4.** An empty Secrets Manager value means the EC2 boots with default config — broken Supabase, broken everything.
- **Don't change `prefix_name`** after the first apply. Most resource names are derived from it; changing it forces wholesale recreation.
- **Don't commit `production.tfvars`** — it has the bastion public key and the EC2 keypair name. Both are low-sensitivity individually but the whole file telegraphs your deploy identity.
- **Don't commit any `*.pem`** — the `terraform/production/` directory is the working dir; check `.gitignore`.
