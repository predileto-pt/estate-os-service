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
# review the plan — should be ~23 resources created
terraform apply tfplan
```

Expected resources:

- **ECR (2 resources)** — 1 repo + 1 lifecycle policy.
- **Documents S3 bucket (3)** — 1 bucket + 1 SSE config + 1 public-access-block. AES256 only, no bucket policy.
- **Property-images S3 bucket (5)** — 1 bucket + 1 SSE + 1 public-access-block + 1 ownership-controls (`BucketOwnerEnforced`) + 1 bucket policy locking reads to the CloudFront distribution.
- **CloudFront (3)** — 1 Origin Access Control (sigv4) + 1 distribution (alias `images.predileto.pt`) + 1 response-headers policy (`Cache-Control: max-age=31536000, immutable`).
- **ACM (2, in `us-east-1`)** — 1 cert for `images.predileto.pt` + 1 DNS validation resource. CloudFront's TLS requirement.
- **GitHub OIDC role (2)** — 1 IAM role assumable from the `estate-os-service` repo's `production` env + 1 inline policy scoped to ECR push.
- **IAM users (6)** — Coolify ECR reader (user + read-only ECR inline policy + access key) and app S3 client (user + R/W/D inline policy on both buckets + access key).
- **Data sources (no resources)** — caller identity + GitHub OIDC provider lookup.

**Expected partial-failure on first apply.** The `aws_acm_certificate_validation.images` resource has a 20-minute create timeout and will fail if DNS isn't wired before it expires — that's normal on the very first apply because the validation CNAME comes from this apply's outputs (chicken-and-egg). Sections 2–9 proceed independently; section 10 wires the DNS and re-applies to pick up the validation.

If you want to avoid the partial-failure shape entirely, run a `-target`'d apply that skips the validation resource:

```bash
terraform apply tfplan -target='module.ecr' -target='module.documents_bucket' \
  -target='module.images_bucket' -target='aws_cloudfront_origin_access_control.images' \
  -target='aws_cloudfront_distribution.images' -target='aws_cloudfront_response_headers_policy.images_long_cache' \
  -target='aws_acm_certificate.images' -target='aws_s3_bucket_policy.images' \
  -target='aws_iam_role.github_actions' -target='aws_iam_user.coolify_ecr_reader' \
  -target='aws_iam_user.app_s3'
```

Either pattern reaches the same end state — section 10's re-apply completes the cert validation either way.

**Capture outputs.** You'll reference them in every subsequent section:

```bash
terraform output ecr_repository_url
terraform output github_actions_role_arn
terraform output documents_bucket_name
terraform output images_bucket_name
terraform output images_cdn_domain                            # CNAME target for images.predileto.pt
terraform output -raw acm_validation_record_name              # CNAME name for ACM DNS validation
terraform output -raw acm_validation_record_value             # CNAME value
terraform output coolify_ecr_reader_access_key_id
terraform output -raw coolify_ecr_reader_secret_access_key    # write this somewhere safe
terraform output app_s3_access_key_id
terraform output -raw app_s3_secret_access_key                # ditto
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
(no `push: branches: [main]` yet — see section 12 for the flip). One
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
| `S3_IMAGES_BUCKET_NAME` | `terraform output -raw images_bucket_name` | n |
| `IMAGES_CDN_BASE_URL` | literal `https://images.predileto.pt` (consumed by `record_property_image` to build CDN URLs; empty in dev to fall back to `S3DocumentStorage.get_public_url`) | n |
| `CONTRACT_S3_BUCKET_NAME` | leave at Settings default `contract-intelligence-documents` (no bucket yet — see section 13) | n |
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

### How the request reaches `api` (architecture primer)

Before the step-by-step: understand the full request path so the
config below makes sense. **Nginx is not involved** — we intentionally
didn't deploy the in-compose `nginx` service (section 5a). Coolify's
own Traefik proxy is the entry point.

```
                    Browser
                       │  https://api.predileto.pt
                       ▼
              [ DNS: api.predileto.pt → VM public IP ]   (your Vercel A record, section 9a)
                       │
                       ▼
        ┌─────────────────────────────────┐
        │  Hetzner VM (the host)          │
        │                                 │
        │  ┌───────────────────────────┐  │
        │  │ Coolify Traefik (proxy)   │  │
        │  │  - binds :80 + :443       │  │ ← installed by Coolify on day 0
        │  │  - TLS termination        │  │
        │  │  - Let's Encrypt ACME     │  │
        │  │  - routes by Host header  │  │
        │  └───────────┬───────────────┘  │
        │              │ HTTP (plain)     │
        │              │ via docker net   │
        │              ▼                  │
        │  ┌───────────────────────────┐  │
        │  │ api container             │  │
        │  │  uvicorn :8000            │  │ ← compose `expose: 8000`
        │  │  (NOT mapped to host)     │  │   (internal-only port)
        │  └───────────────────────────┘  │
        └─────────────────────────────────┘
```

**What Coolify does when you set a domain on a service.** Behind the
scenes, when you configure `api.predileto.pt` on the api service in
section 9c, Coolify writes Docker labels onto the api container, like:

```
traefik.enable=true
traefik.http.routers.<router-id>.rule=Host(`api.predileto.pt`)
traefik.http.routers.<router-id>.entrypoints=websecure
traefik.http.routers.<router-id>.tls.certresolver=letsencrypt
traefik.http.services.<svc-id>.loadbalancer.server.port=8000
```

Traefik watches the Docker daemon (via `/var/run/docker.sock`),
notices the labels, and:

1. **Adds a router** matching `Host(api.predileto.pt)` to its config.
2. **Sees `tls.certresolver=letsencrypt`** → triggers an ACME
   request to Let's Encrypt for a cert covering `api.predileto.pt`.
3. **Solves the HTTP-01 challenge** automatically (see TLS flow below).
4. **Stores the cert** in its `acme.json` (Coolify-managed Docker
   volume on the VM, persists across restarts).
5. **Auto-renews** ~30 days before expiry (Let's Encrypt cert lifetime
   is 90 days).

You don't run any of this — it's automatic the moment you save the
domain in the Coolify UI. The pre-conditions (sections 9a, 9b) just
need to be in place first.

**The TLS flow in plain English.**

- *Cert issuance (one-shot, ~30s–2min):*
  - Traefik calls Let's Encrypt's ACME endpoint: "issue a cert for
    `api.predileto.pt`."
  - LE responds: "prove you control this domain by serving the file
    `/.well-known/acme-challenge/<token>` over HTTP on port 80."
  - Traefik on the VM (which holds :80) responds to that path
    automatically when the challenge fires.
  - LE checks: `GET http://api.predileto.pt/.well-known/acme-challenge/<token>`
    → reaches Traefik via the A record from 9a → matches the
    expected token. Validation passes.
  - LE returns the signed cert. Traefik stores it.
- *Steady-state traffic:*
  - Browser opens `https://api.predileto.pt`.
  - DNS resolves → VM IP.
  - TLS handshake terminates at Traefik (using the LE cert).
  - Traefik proxies the **decrypted** request to `api:8000` over the
    Coolify project's docker bridge network.
  - api returns the response. Traefik wraps it in TLS and sends back.
- *Auto-renewal:*
  - Traefik checks cert expiry continuously.
  - ~30 days before expiry, it re-runs the HTTP-01 challenge.
  - **Port 80 must stay open** to the internet for this to work
    (don't firewall it off thinking you only need :443).

**Why nginx isn't here.** Traefik already does TLS termination,
host-header routing, and cert auto-management. Adding nginx between
Traefik and api would just add a hop with no behavior change — and
double TLS termination if you wanted nginx to also do HTTPS. The
in-compose nginx is dev-only scaffolding.

**Why api uses `expose: 8000` instead of `ports: 80:8000`.** Because
api shouldn't be reachable from the internet directly — only via
Traefik. `expose:` makes the port reachable from other containers
on the same docker network (Traefik) but NOT from the VM host or
the internet. This is correct.

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

DNS propagation is usually 1–5 minutes. If `dig` returns nothing,
wait and try again — don't proceed to 9c until this resolves.

### 9b. CAA pre-check

CAA records on the apex domain restrict which Certificate Authorities
may issue certs. If `predileto.pt` has restrictive CAA records that
don't include Let's Encrypt, the HTTP-01 challenge will succeed but
Let's Encrypt will refuse to issue the cert ("CAA record check
failed"). Pre-check:

```bash
dig +short CAA predileto.pt @8.8.8.8
```

Three outcomes:

- **No output** → no CAA records, any CA may issue. Skip to 9c.
- **Output includes `letsencrypt.org`** → already authorized. Skip
  to 9c.
- **Output lists other CAs only** (e.g. `amazon.com`, `pki.goog`) →
  add Let's Encrypt now, before continuing. In Vercel DNS:

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

You're adding a new CAA entry alongside any existing ones, not
replacing them — keep whatever else is already there.

### 9c. Configure the api domain in Coolify

Now Coolify takes over.

1. Coolify UI → your project → `api` service → Domains.
2. Enter `https://api.predileto.pt` (note: **https**, not http —
   this is what tells Coolify to wire `tls.certresolver=letsencrypt`).
3. If there's a "Generate Domain" toggle (Coolify-managed
   auto-subdomain), turn it OFF — you're using a custom domain.
4. Enable "Force HTTPS" (or "Redirect HTTP → HTTPS", depending on
   Coolify version). This adds a Traefik middleware that 301s any
   plain-HTTP request to https://.
5. Save.

What happens immediately after Save:

- Coolify writes the Traefik labels onto the api container
  (Docker label update, no restart needed).
- Traefik picks up the new router via its Docker provider.
- ACME request fires automatically.
- Cert issuance takes typically 30s–2min.

Watch the Coolify api service log tab; you may see a brief 502 or
"cert issuance pending" while ACME completes, then green.

### 9d. Verify TLS end-to-end

```bash
curl -fsS https://api.predileto.pt/api/v1/health
# expect 2xx (JSON body, e.g. {"status":"ok"})

curl -vIs https://api.predileto.pt/api/v1/health 2>&1 | grep -E "issuer:|subject:"
# expect:
#   subject: CN=api.predileto.pt
#   issuer: CN=R10, O=Let's Encrypt, C=US   (or similar LE issuer)
```

Also verify the HTTP→HTTPS redirect:

```bash
curl -sI http://api.predileto.pt/api/v1/health | head -3
# expect:
#   HTTP/1.1 308 Permanent Redirect
#   Location: https://api.predileto.pt/api/v1/health
```

### 9e. If cert issuance fails

Check Traefik's logs on the VM. In a Coolify-default setup the
Traefik container is named `coolify-proxy` (verify with
`docker ps --filter "name=proxy"`):

```bash
docker logs coolify-proxy 2>&1 | grep -i "acme\|certificate\|api.predileto.pt" | tail -30
```

Common failures:

- **`urn:ietf:params:acme:error:caa`** — CAA record blocks LE. Re-do 9b.
- **`urn:ietf:params:acme:error:connection`** or `DNS problem: NXDOMAIN`
  — DNS hasn't propagated yet, or the A record points at the wrong IP.
  Re-do 9a, wait, retry.
- **`unauthorized: ... 80 timeout`** — port 80 is firewalled off
  the VM. Open it (Hetzner firewall / `ufw allow 80/tcp`); Traefik
  needs :80 for both initial issuance and renewal.
- **Cert issued but `curl` still times out** — check that Traefik
  is actually fronting the request: `curl -v https://api.predileto.pt/api/v1/health 2>&1 | head -30` should show a TLS handshake completing with the LE
  cert. If it 404s with a Traefik default page, the labels on the
  api container didn't get written — check Coolify api service
  → Domains is saved correctly.

---

## 10. Property images CDN bring-up

Wires DNS, completes the ACM cert validation that section 1's apply
left hanging, and configures Coolify for the new private S3 images
bucket + CloudFront distribution at `https://images.predileto.pt`.
Spec: `property-images-bucket-cdn` (archive).

The Terraform resources themselves were already provisioned in section 1
(or are pending validation). This section is mostly operator-side DNS
+ Coolify config + a re-apply to pick up the validation.

### 10.1 CAA pre-check (apex)

Before adding DNS records, confirm the apex CAA permits Amazon Trust
Services to issue the cert. Both `letsencrypt.org` (api domain,
section 9) and `amazon.com` (ACM/CloudFront here) should already be
present from earlier setup — verify:

```bash
dig +short CAA predileto.pt @8.8.8.8
# expect output including:
#   0 issue "letsencrypt.org"
#   0 issue "amazon.com"
```

If `amazon.com` is missing, add `0 issue "amazon.com"` in Vercel DNS
at the apex before 10.3 — otherwise ACM will reject validation with
`urn:ietf:params:acme:error:caa` even with the correct CNAME in place.

### 10.2 Add the images CNAME in Vercel DNS

In Vercel for the `predileto.pt` zone:

| Field | Value |
|---|---|
| Type | `CNAME` |
| Name | `images` (Vercel auto-appends `.predileto.pt`) |
| Value | output of `terraform output -raw images_cdn_domain` (looks like `d1xyzabc123.cloudfront.net`) |

Verify:

```bash
dig +short CNAME images.predileto.pt @8.8.8.8
# expect the CloudFront hostname
```

### 10.3 Add the ACM validation CNAME

The ACM cert from section 1 is in `PENDING_VALIDATION` (or its
`aws_acm_certificate_validation.images` resource timed out and is
errored). Wire the validation CNAME so ACM can issue:

| Field | Value |
|---|---|
| Type | `CNAME` |
| Name | `terraform output -raw acm_validation_record_name` (strip the trailing `.predileto.pt.`) |
| Value | `terraform output -raw acm_validation_record_value` |

Validation typically completes within 1–10 minutes after DNS
propagates.

### 10.4 Re-apply Terraform to complete cert validation

With both CNAMEs in place and the CAA records confirmed, re-apply so
`aws_acm_certificate_validation.images` succeeds:

```bash
cd terraform/production-coolify
terraform plan -out=tfplan
terraform apply tfplan
```

- If section 1 used the `-target`'d first-apply pattern, this run is
  where the validation resource gets created for the first time.
- If section 1 did the full apply and timed out on validation, this
  run retries it.

Either way the end state is identical: cert ISSUED, distribution
ready to attach it.

### 10.5 Wait for distribution + verify routing

The CloudFront distribution was created in section 1's apply and is
likely already `Deployed` by the time you get here. Verify the
end-to-end path:

- **10.5a.** Check distribution status:
  ```bash
  aws cloudfront get-distribution \
    --id $(terraform output -raw images_cdn_distribution_id) \
    --query 'Distribution.Status' --output text
  # expect: Deployed   (until then it returns: InProgress; takes 5-20min from first apply)
  ```
- **10.5b.** Verify DNS resolves at the edge:
  ```bash
  dig +short CNAME images.predileto.pt @8.8.8.8
  # should return the same hostname as `terraform output -raw images_cdn_domain`
  ```
- **10.5c.** Verify TLS + routing end-to-end with a known-missing key:
  ```bash
  curl -I https://images.predileto.pt/this-key-does-not-exist
  # expect: HTTP/2 403   (or 404 — both prove CloudFront answered)
  ```
  A `curl: (6) Could not resolve host` means DNS hasn't propagated.
  An `SSL_ERROR_BAD_CERT_DOMAIN` means the cert didn't attach (the
  validation in 10.4 didn't actually complete — `terraform plan`
  should be clean before reaching here). A 502 means the distribution
  is still deploying (re-do 10.5a).

### 10.6 Coolify env vars

`S3_IMAGES_BUCKET_NAME` and `IMAGES_CDN_BASE_URL` should already be
in the Coolify project-level env panel — they're rows in the
section 6b table that the operator runs through during initial
bring-up. If you skipped them (e.g. this is an add-CDN-to-existing-stack
run, not a from-scratch first deploy), add them now. NOT per-service —
compose interpolates `${VAR}` at parse time.

Also **verify `PORTAL_DATABASE_URL` is present at the project level**.
If it's missing or scoped to the `api` service only, the `migrations`
service from `deploy/docker-compose.prod.yml` will fail with
`PORTAL_DATABASE_URL not set` and block every deploy.

### 10.7 Trigger a Coolify redeploy

`workflow_dispatch` the `co-build-and-push.yml` workflow (or push a
commit to `main` if you already flipped section 12's trigger).
This pulls the new image, restarts the stack, and runs the new
`migrations` service first.

### 10.8 Verify migrations ran clean

In the Coolify UI → `migrations` service → Logs. Expect:

- `migrate_admin.sh` output ending with `INFO ... Will assume non-transactional DDL.` and similar alembic completion lines.
- The `e1f8c5a2b6d7_clear_legacy_property_images` revision applied (look for the revision id in the alembic output).
- `migrate_portal.sh` output the same shape.
- Container status: `exited (0)`.

If the migrations service shows `exited (1)` or `exited (137)`, the
api + workers will be stuck in `Created` (not `Running`). Most common
cause: `PORTAL_DATABASE_URL` not set at project level (see 10.6).
Fix and re-trigger the deploy.

### 10.9 Verify image upload + render end-to-end

From the dashboard frontend:

1. Open a property → upload a new image.
2. Confirm the image renders in the browser. The `<img src="">` should
   point at `https://images.predileto.pt/properties/<id>/images/<uuid>.<ext>`.
3. In the browser dev tools Network tab, confirm:
   - The request resolves over HTTP/2 to a `*.cloudfront.net` server.
   - Response includes `Cache-Control: public, max-age=31536000, immutable`.
4. Confirm the bucket-direct URL is blocked:
   ```bash
   curl -I https://$(terraform output -raw images_bucket_name).s3.eu-west-3.amazonaws.com/properties/<id>/images/<uuid>.<ext>
   # expect: HTTP/1.1 403 Forbidden
   ```

If image rendering 403s through `images.predileto.pt`: most likely
the bucket policy doesn't include the distribution's ARN — check
`aws_s3_bucket_policy.images` in Terraform.

---

## 11. Operator workflows

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

## 12. Enable push-to-main trigger

**Status: enabled 2026-05-16.** Every merge to `main` now builds +
pushes + redeploys automatically via the Coolify webhook.

The trigger in `.github/workflows/co-build-and-push.yml` is:

```yaml
on:
  workflow_dispatch:
  push:
    branches:
      - main
```

To temporarily disable auto-deploy (e.g. for a freeze window), remove
the `push:` block and re-merge. `workflow_dispatch` continues to work
for manual rebuilds.

---

## 13. Things that will bite you

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
- **Port 80 firewalled off.** Tempting after the cert is issued
  ("we only need 443 now"). Don't — Traefik solves the Let's Encrypt
  HTTP-01 challenge on :80, and it does this *every renewal* (~60
  days). Block :80 and the cert silently expires in ~90 days. Hetzner
  firewall (if used) + the VM's `ufw` must both allow tcp/80 inbound
  from the world.
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
