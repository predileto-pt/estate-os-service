# Coolify — first deploy

Operator runbook for the initial bring-up of the Coolify/Hetzner
production stack. Read [ADR-018 addendum](../adr/018-lambda-as-sqs-worker-runtime.md#addendum--2026-05-13-coolify-as-the-active-runtime)
first for the architecture; this doc is the sequenced "do these steps
in this order" companion.

After the first deploy, day-to-day deploys are automatic (push to
`main` → `.github/workflows/co-build-and-push.yml` → ECR → Coolify
webhook). This runbook is one-shot.

**Section order is load-bearing.** It solves a chicken-and-egg where
Coolify can't validate an `image: <repo>:latest` reference until the
first CI push has populated the tag. Don't skip ahead.

---

## 0. Prerequisites

These items live outside terraform and must exist before
`terraform init` works.

1. **AWS account + admin IAM** for the bootstrap operator (you).
   Create an access key locally for
   `aws configure --profile predileto-prod` or use AWS SSO.

2. **S3 bucket for terraform state.** The backend in
   `terraform/production-coolify/_providers.tf` is hardcoded:

   ```
   bucket = "estate-os-service-prod-terraform-state"
   region = "eu-west-3"
   ```

   The companion stack (`terraform/production/`) used the same
   bucket — it may still exist after the AWS resource purge. Check
   with `aws s3api head-bucket --bucket estate-os-service-prod-terraform-state --region eu-west-3`.
   If it's gone, create it once (encryption + versioning +
   public-access-block on):

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

3. **Hetzner VM with Coolify installed.** Docker daemon running,
   Coolify v4 UI reachable on the VM's public IP (port `:8000`
   typical), `aws` CLI installed on the VM
   (`sudo apt install awscli` or via `pip install awscli`).

4. **DNS control over `predileto.pt`.** Vercel-managed today. You'll
   add one A record + (potentially) one CAA record before the
   Let's Encrypt cert can issue.

5. **GitHub repo settings.**
   - Repo path is `predileto-pt/estate-os-service` (hardcoded in
     `github_oidc.tf`'s `:sub` claim).
   - Create a `production` environment under repo settings
     (Settings → Environments → New environment → `production`).

---

## 1. `terraform/production-coolify/` first apply

```bash
cd terraform/production-coolify
terraform init
terraform plan -out=tfplan
# review the plan — should be ~13 resources created
terraform apply tfplan
```

Expected resources:

- 1 ECR repo + 1 lifecycle policy
- 1 S3 bucket + 1 SSE config + 1 public-access-block
- 1 IAM role + 1 inline policy (GitHub OIDC)
- 2 IAM users + 2 inline policies + 2 access keys
  (Coolify ECR reader + app S3 client)
- Data lookups for caller identity + OIDC provider (no resources)

**Capture outputs.** You'll reference them in every subsequent
section:

```bash
terraform output ecr_repository_url
terraform output github_actions_role_arn
terraform output documents_bucket_name
terraform output coolify_ecr_reader_access_key_id
terraform output -raw coolify_ecr_reader_secret_access_key  # write this somewhere safe
terraform output app_s3_access_key_id
terraform output -raw app_s3_secret_access_key              # ditto
```

---

## 2. Configure the VM to pull from ECR

ECR doesn't accept the IAM secret key directly as a registry
password — it expects the short-lived token from
`aws ecr get-login-password`, valid ~12h. Hetzner VMs have no
IMDS/instance-profile equivalent, so we use the
`coolify_ecr_reader` static keys + a systemd timer to refresh
`docker login` every 8h. Coolify just uses the host's docker daemon
and inherits the credentials with zero Coolify-side config.

### 2a. Write AWS credentials to the VM

As root on the VM:

```bash
mkdir -p /root/.aws

cat > /root/.aws/credentials <<EOF
[coolify-ecr-reader]
aws_access_key_id = <terraform output -raw coolify_ecr_reader_access_key_id>
aws_secret_access_key = <terraform output -raw coolify_ecr_reader_secret_access_key>
EOF

cat > /root/.aws/config <<EOF
[profile coolify-ecr-reader]
region = eu-west-3
EOF

chmod 600 /root/.aws/credentials /root/.aws/config
```

### 2b. Install the systemd refresh timer

As root, paste verbatim (substitute `<account-id>`):

**`/etc/systemd/system/ecr-login.service`**:

```ini
[Unit]
Description=Refresh docker login against ECR (Coolify image pull)
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
ExecStart=/bin/bash -c "aws ecr get-login-password --profile coolify-ecr-reader --region eu-west-3 | docker login --username AWS --password-stdin <account-id>.dkr.ecr.eu-west-3.amazonaws.com"
```

**`/etc/systemd/system/ecr-login.timer`**:

```ini
[Unit]
Description=Refresh ECR docker login every 8h

[Timer]
OnCalendar=*-*-* 00,08,16:00:00
Persistent=true
Unit=ecr-login.service

[Install]
WantedBy=timers.target
```

Enable + kick the timer + service once immediately:

```bash
systemctl daemon-reload
systemctl enable --now ecr-login.timer
systemctl start ecr-login.service
```

Verify:

```bash
systemctl list-timers | grep ecr-login
journalctl -u ecr-login.service --no-pager -n 20
# expect: "Login Succeeded" in the output
```

**Don't `docker pull` yet** — no images exist in the ECR repo until
section 4.

---

## 3. GitHub `production` environment secrets

Set in `Settings → Environments → production → Environment secrets`:

| Secret | Value |
|---|---|
| `AWS_GHA_ROLE_ARN` | `terraform output -raw github_actions_role_arn` |

`COOLIFY_DEPLOY_WEBHOOK` is added in section 5d once Coolify is set up.

---

## 4. First CI run (`workflow_dispatch`)

`Actions → Build + Push to ECR (Coolify) → Run workflow → main`.

The workflow ships with `workflow_dispatch`-only trigger initially
(no `push: branches: [main]` yet — see section 11 for the flip). One
run does:

1. OIDC → assume `github_actions` role.
2. ECR login.
3. Resolve tags (`:latest` + `:<sha7>`).
4. `docker build -f Dockerfile.prod` + push both tags.
5. Coolify webhook step → skipped this run (the secret doesn't exist
   yet) with a `::warning::` log line and `exit 0`.

**Verify:** ECR console shows both `:latest` and `:<sha7>` tags on
`estate-os-service`.

---

## 5. Coolify project + services setup

Now that `:latest` exists in ECR, configure Coolify. Six services —
**not seven** (the `nginx` entry in the compose file is intentionally
not deployed; Coolify's Traefik handles ingress instead).

### 5a. Create the project + add services

In the Coolify UI:

1. New project (or use an existing one). Name it `estate-os-service`.
2. Add the compose file:
   - Option A: paste `deploy/docker-compose.prod.yml` contents and
     **remove the `nginx:` service** from the YAML before saving.
   - Option B: point at the git repo + path `deploy/docker-compose.prod.yml`
     and configure Coolify to skip the `nginx` service.
3. Confirm the six services Coolify is now managing: `api`,
   `extraction-worker`, `enrichment-worker`, `listings-events-worker`,
   `rabbitmq`, `redis`.

### 5b. Image source

Do **NOT** override the per-service image source in the Coolify UI.
The compose `image: ${ECR_IMAGE}` is filled by the project-level
`ECR_IMAGE` env var you'll set in section 6. All four Python services
pull the same image; setting per-service image fields would shadow
the unified-image semantics.

Mount the named volumes:

- `rabbitmq-data` → `/var/lib/rabbitmq` on the `rabbitmq` service.
- `redis-data` → `/data` on the `redis` service.

Verify all six services share the Coolify project's bridge network
(default behavior; check Project → Network) so the compose hostnames
`rabbitmq:5672` and `redis:6379` resolve via Docker service-name DNS.

### 5c. Don't touch the Container Registry UI

**Do NOT configure ECR credentials in the Coolify "Container
Registry" UI.** The host's docker daemon is already authenticated by
the systemd timer in step 2b, and Coolify reuses it. The Coolify
registry-config field stays empty.

### 5d. Generate the deploy webhook

In the Coolify UI: Project → Settings → Webhooks → Generate
(verify exact menu path against the running Coolify version — may be
under a different label).

Use the **project-level** webhook (one URL → all six services
redeploy together). Save the URL as the `COOLIFY_DEPLOY_WEBHOOK`
secret in the GitHub `production` environment.

---

## 6. Env vars in Coolify UI

**The key insight:** docker-compose interpolates `${VAR}` references
in the compose file at **parse time**, not container runtime. Almost
every env value in `deploy/docker-compose.prod.yml` is `KEY: ${KEY}`,
which means: for these to resolve correctly, the value must be
supplied where Coolify performs compose interpolation — typically
Coolify v4's **project-level "Environment Variables"** panel, not
the per-service env panel.

Verify which Coolify v4 panel feeds compose interpolation in the UI
you're running. If unsure, default to project-level for everything in
the table below — per-service env in Coolify is generally only useful
for true per-service overrides (the compose file already declares
those statically via `environment:` blocks, e.g. `GOOGLE_MAPS_API_KEY`
on `enrichment-worker` only).

Setting `RABBITMQ_USER`/`RABBITMQ_PASSWORD` or any other
compose-interpolated key per-service yields empty values in
containers and breaks the stack silently.

### 6a. Generate strong values first

These two are generated, not external-source:

- `RABBITMQ_USER` — generate a unique alphanumeric string
  (e.g. `openssl rand -base64 24 | tr -dc 'A-Za-z0-9'`).
- `RABBITMQ_PASSWORD` — same, separate value.

Store both in your secrets vault.

### 6b. Env-var table

All entries below go in the Coolify **project-level** env panel
unless otherwise noted. Compose-literal values (queue names,
RABBITMQ_URL, REDIS_URL, etc.) are pre-baked into the compose file
and require **no Coolify config**.

| Key | Source | Sensitive |
|---|---|---|
| `ECR_IMAGE` | `<terraform output -raw ecr_repository_url>:latest` | n |
| `RABBITMQ_USER` | generated (see 6a) | y |
| `RABBITMQ_PASSWORD` | generated (see 6a) | y |
| `AWS_REGION` | literal `eu-west-3` | n |
| `AWS_ACCESS_KEY_ID` | `terraform output -raw app_s3_access_key_id` | y |
| `AWS_SECRET_ACCESS_KEY` | `terraform output -raw app_s3_secret_access_key` | y |
| `S3_BUCKET_NAME` | `terraform output -raw documents_bucket_name` | n |
| `CONTRACT_S3_BUCKET_NAME` | leave at Settings default `contract-intelligence-documents` (no bucket yet — see section 12) | n |
| `OPENAI_API_KEY` | OpenAI dashboard → API keys | y |
| `REDUCTO_API_KEY` | Reducto dashboard → API keys | y |
| `DATABASE_URL` | Supabase admin project → Connection string (URI mode, +asyncpg) | y |
| `ENCRYPTION_PUBLIC_KEY` | local PEM file contents (RSA pub, screening) | n |
| `ENCRYPTION_PRIVATE_KEY` | local PEM file contents (RSA priv, screening) | y |
| `ENCRYPTION_HMAC_KEY` | generated (base64 256-bit) | y |
| `APP_ENV` | literal `production` | n |
| `LOG_LEVEL` | literal `info` | n |
| `LOGFIRE_TOKEN` | Logfire dashboard → project token | y |
| `LANGFUSE_PUBLIC_KEY` | Langfuse dashboard | n |
| `LANGFUSE_SECRET_KEY` | Langfuse dashboard | y |
| `LANGFUSE_BASE_URL` | literal (e.g. `https://cloud.langfuse.com`) | n |
| `SUPABASE_URL` | Supabase admin project → Project URL | n |
| `SUPABASE_SERVICE_ROLE_KEY` | Supabase admin → Service role key | y |
| `SUPABASE_JWT_SECRET` | Supabase admin → JWT secret | y |
| `STRIPE_API_KEY` | Stripe dashboard → live API key (`sk_live_…`) | y |
| `STRIPE_WEBHOOK_SECRET` | Stripe dashboard → webhook signing secret (`whsec_…`) | y |
| `STRIPE_PRICE_PRO_MONTHLY` | Stripe price id | n |
| `STRIPE_PRICE_PRO_YEARLY` | Stripe price id | n |
| `STRIPE_PRICE_ENTERPRISE_MONTHLY` | Stripe price id | n |
| `STRIPE_PRICE_ENTERPRISE_YEARLY` | Stripe price id | n |
| `STRIPE_TRIAL_PERIOD_DAYS` | literal (e.g. `7`) | n |
| `SUPABASE_PORTAL_URL` | Portal Supabase project → URL | n |
| `SUPABASE_PORTAL_JWT_SECRET` | Portal Supabase → JWT secret | y |
| `SUPABASE_PORTAL_AUDIENCE` | literal `authenticated` | n |
| `PORTAL_DATABASE_URL` | Portal Supabase → DB connection string | y |
| `SESSION_SIGNING_KEYS` | generated, format `1:<base64url>` (see ADR/spec) | y |
| `SESSION_SIGNING_ACTIVE_KEY` | literal `1` | n |
| `SESSION_COOKIE_DOMAIN` | literal `.predileto.pt` | n |
| `LISTINGS_SEARCH_ENABLED` | literal `true` or `false` per current rollout | n |
| `CORS_ORIGINS` | comma-separated Vercel origins (e.g. `https://os.predileto.pt,https://predileto.pt`) | n |
| `APP_URL` | literal `https://os.predileto.pt` (admin frontend on Vercel) | n |
| `RESEND_API_KEY` | Resend dashboard → API key | y |
| `GOOGLE_MAPS_API_KEY` | Google Cloud → API key (Maps Geocoding) — only enrichment-worker consumes, but set at project level | y |
| `PINECONE_API_KEY` | Pinecone dashboard | y |
| `PINECONE_HOST` | Pinecone index host (`<index>-<projectid>.svc.<region>.pinecone.io`) | n |
| `PINECONE_INDEX` | Pinecone index name (e.g. `listings-prod`) | n |
| `EMBEDDING_MODEL` | literal `text-embedding-3-small` | n |
| `EMBEDDING_DIMENSIONS` | literal `1536` | n |
| `VECTOR_INDEX_NAMESPACE` | literal `openai-text-embedding-3-small-v1` | n |

**Do NOT set in Coolify** (they're literals or compose-built and
already in the YAML):

- `RABBITMQ_URL` — compose builds it from `RABBITMQ_USER` +
  `RABBITMQ_PASSWORD` above.
- `RABBITMQ_DOMAIN_EVENTS_EXCHANGE`, `RABBITMQ_DLX`
- `PROPERTY_EXTRACTION_QUEUE`, `PROPERTY_ENRICHMENT_QUEUE`,
  `APPLICANT_EXTRACTION_QUEUE`, `APPLICANT_SCREENING_QUEUE`,
  `CONTRACT_INGESTION_QUEUE`, `CONTRACT_ANALYSIS_QUEUE`
- `REDIS_URL`, `LISTINGS_PAGE_CACHE_ENABLED`,
  `LISTINGS_EMBEDDING_ENABLED`

**Do NOT set in Coolify** (intentionally unset in prod):

- `AWS_ENDPOINT_URL` — LocalStack-only. Setting it in prod points S3
  calls at a LocalStack endpoint and every operation 404s.

---

## 7. Second CI run — image pull + deploy

With env vars populated, fire `workflow_dispatch` again. This run:

1. Pushes a new image (same flow as section 4).
2. Hits the Coolify webhook (now configured).
3. Coolify pulls the image, restarts the 6 services with the
   project-level env applied.

Watch the Coolify UI for green status on all six services.

---

## 8. Verify the stack is up

On the VM:

```bash
docker ps --filter "label=coolify.projectName=<project-slug>"
# expect 6 containers Up
```

From the VM, check the api directly:

```bash
docker exec $(docker ps --filter "name=api" --filter "label=coolify.projectName=<project-slug>" --format '{{.ID}}') \
  curl -fsS http://localhost:8000/api/v1/health
# expect 2xx
```

RabbitMQ — enable port-forward to `:15672` from your laptop
temporarily (e.g. `ssh -L 15672:localhost:15672 <vm>`), open
`http://localhost:15672` in a browser, sign in with
`RABBITMQ_USER` / `RABBITMQ_PASSWORD`. Check the Connections tab —
4 connections expected (api + 3 workers). Queue depth on the
extraction / enrichment / listings-events queues should stay near
zero (no message pile-up). Close the port-forward when done.

Coolify UI: per-service log tabs show no error spam (compose
healthcheck on `api` may emit a few `curl -f` lines during
start_period — that's fine).

---

## 9. DNS + TLS

### 9a. A record

Add an `A` record in Vercel DNS for `predileto.pt`:

| Field | Value |
|---|---|
| Type | `A` |
| Name | `api` (Vercel auto-appends `.predileto.pt`) |
| Value | `<VM public IPv4>` |

Verify:

```bash
dig +short A api.predileto.pt @8.8.8.8
# should return the VM IP
```

### 9b. CAA pre-check

Same gotcha as in `production-first-deploy.md` Section 0 prereq
step 5, but pointed at Let's Encrypt instead of Amazon:

```bash
dig +short CAA predileto.pt @8.8.8.8
```

Three outcomes:

- **No output** → no CAA records, any CA may issue. Skip to 9c.
- **Output includes `letsencrypt.org`** → already authorized. Skip
  to 9c.
- **Output lists other CAs only** (e.g. `amazon.com`, `pki.goog`) →
  add Let's Encrypt now. In Vercel DNS:

  | Field | Value |
  |---|---|
  | Type | `CAA` |
  | Name | `@` (apex; leave blank in Vercel) |
  | Flags | `0` |
  | Tag | `issue` |
  | Value | `letsencrypt.org` |

  If Vercel uses a single combined Value field, paste
  `0 issue "letsencrypt.org"` (literal quotes). Verify after ~1 min:

  ```bash
  dig +short CAA predileto.pt @8.8.8.8
  # should now include: 0 issue "letsencrypt.org"
  ```

### 9c. Configure the api domain in Coolify

Coolify UI: api service → Domains. Enter `https://api.predileto.pt`.
Toggle "Generate Domain" off (use the custom domain). Enable "Force
HTTPS". Save.

Coolify's built-in Traefik issues a Let's Encrypt cert via the
HTTP-01 challenge against the A record from 9a. Cert issuance is
typically 30s–2min.

### 9d. Verify TLS end-to-end

```bash
curl -fsS https://api.predileto.pt/api/v1/health
# expect 2xx
curl -vIs https://api.predileto.pt/api/v1/health 2>&1 | grep "issuer"
# expect: issuer: ... CN=R10 / Let's Encrypt ...
```

---

## 10. Operator workflows

### SSH into the VM

Hetzner-issued SSH key, or use the `coolify` user terminal in the UI
(Project → Server → Terminal).

### Tail container logs

Coolify UI: per-service log tab is the easiest path. Or on the VM:

```bash
docker logs -f <container-id>
# Coolify-managed containers aren't reachable via plain
# `docker compose logs` — there's no compose project on the host
# file system. Use `docker ps --filter "label=coolify.projectName=..."`
# to find container IDs.
```

### Manual redeploy

Coolify UI: "Restart" per service, or "Deploy" at the project level
(picks up the latest `:latest` from ECR).

### Rotate env vars

Edit in the Coolify UI → service auto-restarts on save (or hit
"Restart" if the auto-restart didn't pick up).

### Drain a worker queue

RabbitMQ management UI → Queues → select queue → "Purge messages".
Or stop the worker service in Coolify, drain via the management
API, restart the worker.

### Rotate the Coolify ECR access key

```bash
cd terraform/production-coolify
terraform taint aws_iam_access_key.coolify_ecr_reader
terraform apply
# Then on the VM, re-do section 2a with the new keys + restart the
# timer:
systemctl restart ecr-login.service
```

### Rotate the app S3 access key

```bash
cd terraform/production-coolify
terraform taint aws_iam_access_key.app_s3
terraform apply
# Then in Coolify, update the two project-level env vars
# (AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY). Coolify will
# restart the services on save.
```

---

## 11. Enable push-to-main trigger

Once two manual `workflow_dispatch` runs have ended green and
Coolify shows a clean deploy, edit
`.github/workflows/co-build-and-push.yml`:

```yaml
on:
  workflow_dispatch:
  push:
    branches:
      - main
```

Commit + push. From that point on, every merge to `main` builds +
pushes + redeploys automatically.

---

## 12. Things that will bite you

- **`ecr-login.timer` not enabled** → pulls 401 after 12h with no
  obvious symptom in the Coolify UI. Check
  `journalctl -u ecr-login.service` first.
- **`AWS_REGION` defaulted to `eu-west-1`** → `Settings.aws_region`
  in `src/shared/config.py:93` defaults to `eu-west-1`. If
  `AWS_REGION` isn't set in Coolify, every S3 call goes to the
  wrong region and 404s. The compose `x-shared-env` declares the
  slot but the value MUST come from Coolify.
- **`AWS_ENDPOINT_URL` must stay unset.** Compose comment explains:
  it's LocalStack-only. If anything (a stale `.env.local`
  copy-paste) injects it in prod, every S3 call goes to the dev
  endpoint and 404s.
- **Env vars set per-service instead of project-level.** Compose
  interpolates `${VAR}` references at parse time, before per-service
  env applies. Set everything in the section-6 table at
  project / shared level. Setting `RABBITMQ_USER`/`RABBITMQ_PASSWORD`
  per-service yields `amqp://:@rabbitmq:5672/` (empty auth →
  RabbitMQ rejects). Setting `SUPABASE_URL` per-service yields empty
  string → api 500s. Same trap for `ECR_IMAGE`.
- **Workers crashing with `uv: not found`.** Indicates the compose
  worker-command fix was reverted. Verify
  `deploy/docker-compose.prod.yml` lines 150 / 159 / 169 are
  `["python", "-m", …]` (not `["uv", "run", "python", "-m", …]`).
  The runtime stage of `Dockerfile.prod` doesn't carry `uv`.
- **YAML merge gotchas in the compose file.** `image:` + `restart:`
  can't be anchored, only `environment:` can — compose-go validates
  `image` before applying service-level merge keys. Don't refactor
  the compose to anchor those two keys.
- **Volume permissions on rabbitmq-data after a host reboot.**
  RabbitMQ refuses to start if its data dir is owned by root after
  a docker daemon reinstall. Fix with `chown -R 999:999 rabbitmq-data`
  (UID 999 is the rabbitmq UID in the official image; confirm via
  `docker exec <rabbitmq> id rabbitmq` if the chown doesn't
  unblock it).
- **Container user mismatch on host-mounted volumes.** The api
  container runs as UID 1001 (`Dockerfile.prod` creates user
  `app`). If you add a host-mounted volume for debugging, `chown -R
  1001:1001` it or the api can't read/write.
- **Contract-intelligence runtime gap.** Routes that exercise
  contract S3 storage will 500 with `NoSuchBucket`; contract
  workers may fail to dispatch DLQ events
  (`sqs_contract_*_dlq_url` is empty by default). The contracts
  bucket is deferred to a follow-up spec — don't expose contract
  endpoints to users until that lands.
- **In-compose `nginx` service deployed by mistake.** Coolify's
  Traefik fronts api directly. If you see Coolify trying to spin
  up an `nginx:1.27-alpine` container, you added the `nginx`
  service in section 5a by mistake. Remove it from the Coolify
  project config.
- **Committing env values to git.** The heredocs and table cells in
  this runbook are operator-side only. Never paste real values
  into PRs.
- **Webhook URL in CI logs.** The workflow binds
  `COOLIFY_DEPLOY_WEBHOOK` via the step's `env:` block so GitHub
  log-masking applies. Don't add `set -x` or curl `-v` to that
  step — masking only catches the masked literal, not text that
  contains it.
