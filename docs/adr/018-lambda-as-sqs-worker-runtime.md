# ADR-018: Lambda as the SQS worker runtime — extraction, enrichment, listings projector

**Date:** 2026-05-12
**Status:** Accepted (completes ADR-002's "Lambda for workers" decision; updates the deployment notes in ADR-008). **Amended 2026-05-12** — see "Addendum: zip packaging" at the end.
**Relates to:** [ADR-002](002-migrate-lambda-to-ec2.md) (hybrid EC2 API + Lambda workers — the originating decision), [ADR-008](008-event-bus-ports-and-fanout.md) (event-bus ports + SNS fan-out — handler code is reused unchanged), [ADR-006](006-sqs-worker-reliability-improvements.md) (SQSWorker — retained for local dev + docker-compose fallback).

## Context

There is no production worker runtime today. `deploy/docker-compose.prod.yml` runs only the FastAPI service, and the file's header comment already documents the intended target state ("Workers … run as Lambda functions consuming from the SQS queues provisioned in `terraform/production/sqs.tf`"). The Lambda stack referenced by that comment was deleted during the bounded-context split and unified-event-bus refactor (ADR-007 / ADR-008) — `terraform/production/lambda.tf` was removed, and the previous entrypoints (`property_management.entrypoints.lambda_extraction`, `customer_management.entrypoints.lambda_events`) were dropped at the same time.

The result is a stalled migration: the worker handlers (`adapters/workers/*_handler.py`, `*_processor.py`) and the shared `SQSWorker` (`src/shared/events/worker.py`) exist as code, the SQS queues + SNS topic-per-event-type fan-out are already provisioned in terraform, but nothing is consuming. ADR-002 already established Lambda as the worker runtime ("EC2 for API only, Lambda for workers"). This ADR records the architectural choices made when picking that work back up.

Three SQS consumers are in scope:

| Queue | Visibility | Consumer characteristics |
|---|---|---|
| `property-extraction` | 720 s | Reducto + OpenAI long-running extraction. Reads/writes S3 documents. |
| `property-enrichment` | 900 s (was 1800 s; reduced to match Lambda max) | Google Places POI fan-out + LLM locality filter. |
| `listings-events` | 60 s | Domain-event projector. Idempotent. Writes to `property_listings` + Pinecone, emits follow-on `PROPERTY_LISTING_*` events. |

## Decision

### 1. One Lambda per worker concern, one SQS record per invocation

Three image-based `aws_lambda_function` resources in `terraform/production/lambda.tf`, all sharing the existing ECR image (`local.ecr_image`). Each function points at a different Python entrypoint via `image_config.command`:

- `properties.entrypoints.lambda_extraction.handler`
- `properties.entrypoints.lambda_enrichment.handler`
- `listings.entrypoints.lambda_events.handler`

`aws_lambda_event_source_mapping` configures `batch_size = 1` on every function. AWS Lambda scales by adding parallel invocations up to the function's reserved concurrency cap — in-process concurrency is irrelevant and `SQSWorker`'s semaphore/heartbeat machinery is unused.

**Why `batch_size = 1`.** With one record per invocation, success/failure semantics collapse to "the invocation succeeded" / "the invocation raised", and `batchItemFailures` partial-batch responses become unnecessary. A handler exception propagates → SQS sees the invocation as failed → the single record redrives per the queue's `maxReceiveCount`, eventually landing in the DLQ. This matches the EC2 `SQSWorker.nack` behaviour bit-for-bit.

### 2. Shared Lambda entrypoint wrapper

`src/shared/events/lambda_handler.py` exposes `make_handler(router, build_context)` — a factory used by each per-context entrypoint. Responsibilities:

- Validate event shape (must contain `Records`); raise a clear `ValueError` otherwise so console-Test invocations or misconfigured triggers fail loudly.
- Unwrap the SNS envelope when present (mirrors `SQSMessage.__init__` in `sqs_message_consumer.py`).
- Build a fresh `DomainEvent` via `DomainEvent.from_dict(...)`.
- Drive the existing async router via `asyncio.run(...)` — fresh event loop per invocation. No persistent state across warm invocations.

The router is constructed once at module import (cold start) and reused warm — it's a pure Python dict of `event_type → handler` with no async resources.

### 3. Fresh container per invocation

`shared.entrypoints.bootstrap` caches per-context containers as module-level globals. Those containers hold async clients (Supabase, aioboto3 SNS, asyncpg) bound to the event loop that created them. Because the handler calls `asyncio.run(...)` per invocation, each warm invocation runs under a fresh loop — using a cached container would raise "Future attached to a different loop" errors.

Each Lambda entrypoint invalidates the relevant `_*_container` globals at the start of `_build_context()` so `get_*_container()` rebuilds cleanly. The cost is one container construction per invocation (~50-200 ms of pool/client setup), traded for correctness and no cross-loop client-binding bugs. See the "Alternatives considered" section for why we don't persist clients across warm invocations.

### 4. Secrets Manager bootstrap

`src/shared/events/lambda_bootstrap.py` runs at module import time as the first line of each Lambda entrypoint. It fetches the JSON blob from the existing `aws_secretsmanager_secret.app_secrets`, parses it, and `os.environ.setdefault(...)`s each key. This populates the env vars `Settings()` (pydantic-settings) reads when the per-context container is built.

**Import-order constraint.** The bootstrap depends only on `os`, `json`, and `boto3`. It must not import `shared.config` or any module that transitively imports it: `shared/config.py` wires Logfire at module load via `logfire.configure(token=settings.logfire_token)`, which instantiates `Settings()` immediately. If env vars haven't been populated yet, `Settings()` reads defaults and the Lambda silently runs in degraded config.

**`setdefault` semantics.** Anything already in process env wins over the secret payload. This makes local Lambda testing painless (export env in the shell; the bootstrap won't clobber) and lets an operator override a single key without rotating the secret.

### 5. Hybrid concurrency caps

| Function | Memory | Timeout | Reserved concurrency |
|---|---|---|---|
| `extraction-worker` | 2048 MB | 720 s | 10 (Reducto + OpenAI rate limits) |
| `enrichment-worker` | 1024 MB | 900 s | 10 (Google Places quota) |
| `listings-events-worker` | 512 MB | 60 s | unreserved |

Extraction and enrichment both call providers with strict rate limits. Without a cap, an SQS event source mapping ramp-up would 429-storm those APIs and burn budget on retries. Listings is short, idempotent, and only writes to internal infrastructure (Supabase, Pinecone); capping it would just create artificial queue depth during normal spikes.

Caps are tunable via the `lambda_<worker>_reserved_concurrency` terraform variables. Setting the listings cap to `-1` means "no reservation" — AWS treats negative values as "unset" rather than "cap at -1".

### 6. Per-queue feature flags + compose-profile fallback

Each event source mapping is gated by `var.lambda_consumes_<queue>` (default `false`). The initial `terraform apply` provisions the Lambdas and event source mappings, but mappings stay disabled until flipped in `production.tfvars`. Rollback is one terraform var flip.

When Lambda is disabled and the SQS queue starts backing up, an operator can take over consumption from the EC2 by starting the corresponding fallback service: `docker compose --profile fallback up -d <service>`. `deploy/docker-compose.prod.yml` defines three services (`extraction-worker`, `enrichment-worker`, `listings-events-worker`) under `profiles: [fallback]` — they don't start on a normal `docker compose up`. Each runs the same `uv run python -m …` command used in local dev, so handler code is identical between Lambda and the fallback path.

### 7. CI/CD: `aws lambda update-function-code` per worker

`.github/workflows/deploy.yml` already builds + pushes the image to ECR. A new step between the push and the EC2 SSM-update step calls `aws lambda update-function-code` for each of the three functions, pinning to the SHA-tagged URI (`${{ steps.tag.outputs.image }}`) — not `latest`. Lambda caches image layers per URI; pointing repeatedly at `latest` doesn't reliably trigger a code refresh on subsequent pushes. After the update calls, the step waits for `function-updated` on each function so a successful deploy means the new image is actually live.

The terraform `aws_lambda_function.image_uri` is set to `local.ecr_image` (which uses `var.ecr_image_tag = "latest"` by default) and the resource has `lifecycle { ignore_changes = [image_uri] }`. Terraform owns the function shape; CI owns code updates.

### 8. Image architecture: x86_64

The ECR image is built for whatever architecture the EC2 (`t3.small`, x86_64) consumes. Lambda must match — `architectures = ["x86_64"]` on each function. A future move to arm64 (Graviton; cheaper) is a separate change to the image build pipeline, out of scope here.

### 9. Network topology — everything but the ALB lives in private subnets

The VPC has three subnet tiers: `presentation_subnets` (public, 10.0.1-3.0/24), `logic_subnets` (private application tier, 10.0.11-13.0/24), and `data_subnets` (private data tier, 10.0.21-23.0/24). After this work, the deployment looks like:

```
                       ┌─────────────┐
        Internet ────► │     IGW     │
                       └──────┬──────┘
                              │
         ┌────────────────────▼───────────────────────────────┐
         │  presentation_subnets  (public)                    │
         │  ┌─────────┐   ┌────────────────┐   ┌────────────┐ │
         │  │   ALB   │   │  NAT EC2       │   │  Bastion   │ │
         │  │         │   │  (t4g.nano)    │   │  (t4g.nano)│ │
         │  └────┬────┘   └────────▲───────┘   └─────▲──────┘ │
         └───────┼─────────────────┼─────────────────┼────────┘
                 │ :8000           │ egress          │ :22
         ┌───────▼─────────────────┴─────────────────┴────────┐
         │  logic_subnets  (private)                          │
         │  ┌─────────────────┐  ┌─────────────────────────┐  │
         │  │ API EC2         │  │ 3× Lambda workers       │  │
         │  │ (private IP)    │  │ (ENIs in private subnet)│  │
         │  └─────────────────┘  └─────────────────────────┘  │
         └────────────────────────────────────────────────────┘
```

**Public surface (`presentation_subnets`):**
- ALB — the only internet-reachable application surface. Receives HTTPS on the ACM cert, forwards to the API EC2 on port 8000 by instance ID.
- NAT EC2 (`module.nat_instance`, t4g.nano, single AZ) — egress for everything in the private subnets.
- Bastion EC2 (`aws_instance.bastion`, t4g.nano AL2023 arm64, EIP attached) — SSH jump host. Pattern mirrors `raz-consulting-services/compliance-agent-service`: direct `aws_instance` + `aws_security_group` (no module indirection for a single bastion), **BYOK keypair** (operator pastes their `ssh-ed25519 ...` public key into `var.bastion_public_key` — terraform never generates or stores a private key), CIDR-tightenable ingress via `var.bastion_allowed_cidr` (default `0.0.0.0/0` with key-auth-only), and IMDSv2-required.

**Private application tier (`logic_subnets`):**
- API EC2 — moved here from the public subnet. `associate_public_ip_address = false`, no EIP. Reachable on port 8000 only from `alb_sg` (app traffic) and port 22 only from `bastion_sg` (operator SSH via ProxyJump). Operator workflow: `ssh -i <bastion-pem> -J ec2-user@<bastion-eip> ec2-user@<api-private-ip>`.
- Three Lambda functions — `vpc_config` attaches each to `logic_subnets` with `lambda_sg` (no ingress, all egress). `AWSLambdaVPCAccessExecutionRole` lets the runtime manage ENIs.

**SSM** (`AmazonSSMManagedInstanceCore` on `ec2_role`) remains attached — required for the CI's `aws ssm send-command` deploys to reach a private-subnet EC2. Interactive operator shell uses the bastion, not SSM Session Manager.

**Private data tier (`data_subnets`):** unused today, reserved for future RDS / cache placement.

**Outbound traffic** from anything in the private subnets (API EC2 calling ECR/Secrets Manager/SSM, Lambdas calling Supabase/OpenAI/Pinecone/Reducto/Google Places/Resend) flows through the NAT EC2 → IGW → internet. The VPC module's `enable_ec2_nat_gateway = true` wires the route tables.

**Why this topology**:
- Defense-in-depth — the ALB is the only thing accepting public traffic. An accidentally-permissive SG on the EC2 or a Lambda misconfiguration can't expose those resources directly to the internet because they have no public IP and no IGW route. The blast radius of an SG misconfiguration is contained to "things inside the VPC".
- Single egress chokepoint — every outbound connection from private resources passes through one NAT instance, giving us a natural point for flow-log auditing if compliance needs it later.
- The NAT is already paid for and routes the (previously public) EC2's outbound traffic; adding the Lambdas and moving the EC2 costs zero incremental infrastructure.
- Future RDS / internal services can be placed in `data_subnets` and reached by the EC2 / Lambdas without any further re-architecting.

**Tradeoffs accepted**:
- Cold-start ENI attachment for Lambdas adds ~100-400 ms on the first invocation per ENI. Hyperplane ENI reuse (AWS, 2019+) means steady-state has no penalty.
- The single NAT EC2 is a SPOF for all private-subnet egress (both Lambda and EC2). Upgrade path: flip `enable_nat_gateway = true` in the VPC module for managed multi-AZ NAT Gateway (~$32/mo per AZ).
- One more EC2 to operate (the bastion). t4g.nano is ~$3/mo, runs AL2023 with automatic security updates, and has no application payload — patching surface is tiny. Acceptable cost for the consistent ops pattern across `cargochain` / `whyhow-ai` / this repo.
- Bastion's `bastion_sg` accepts `0.0.0.0/0:22` (key-auth-only). Locking it down to known admin CIDRs is a tfvar-level change if/when an admin IP list is maintained.

## Consequences

### Pros

- **Zero handler-code change.** `adapters/workers/*` is untouched. The same handler registers on `EventRouter`, gets dispatched the same way, takes the same context type.
- **No worker infrastructure to operate.** No systemd, no docker-compose lifecycle for workers in normal operation, no per-host disk monitoring. AWS handles scaling, retries, and DLQ delivery.
- **Pay-per-invocation.** Idle workers cost nothing. Spiky listings projector load (which the EC2 would have to be sized for) is now elastic.
- **Real fallback story.** The compose-profile services give an operator a runnable recovery path on the same EC2 that hosts the API — no special infrastructure needed.
- **Single-tag CI pin.** SHA-tagged Lambda updates are idempotent and traceable; a deploy maps one-to-one to a git commit.

### Cons

- **Per-invocation container construction.** ~50-200 ms of pool/client setup per invocation. For a 12-min extraction job, this is noise; for a 200 ms listings projection, it's perceptible. Not on a user-blocking path today.
- **Two consumer code paths to maintain.** Lambda entrypoints and `worker.py` / `events_worker.py`. They share handler code so divergence risk is low, but the entrypoint files themselves are duplicated.
- **15-minute Lambda timeout cap.** Enrichment runs comfortably under that today; an outlier longer job would fail and DLQ. Watch CloudWatch for timeouts.
- **No persistent client reuse.** A persistent module-level event loop would shave the per-invocation setup cost but introduce cross-loop binding bugs and stale-TLS recovery, so we explicitly reject it (see Alternatives).

### Neutral

- The `SQSWorker` and its heartbeat machinery stay in the tree — they're load-bearing for local dev and the fallback path. No code to remove.
- ADR-002's hybrid (EC2 API + Lambda workers) is preserved end-to-end; the lambda code was always intended to be there.

## Alternatives considered

- **Persistent event loop reused across warm invocations.** Would shave ~50-200 ms per invocation by caching async clients. Rejected — introduces "Future attached to a different loop" bugs unless every cache is keyed by the current loop, plus stale-TLS recovery (Supabase / Pinecone drop the TCP after 15-30 min idle, the cached client doesn't know). Not worth the complexity until invocation latency is shown to matter.
- **`batch_size > 1` with `batchItemFailures` partial response.** Adds plumbing for negligible throughput gain at expected volumes. Reconsider if invocation count becomes a meaningful cost line.
- **EventBridge instead of SNS** to native-route to Lambda. Rejected — SNS topology is already in place, working, and documented in ADR-008.
- **Step Functions for enrichment** to bypass the 15-min cap. Not needed — real runs stay well under 15 min.
- **Lambda outside the VPC.** Initially proposed for lower cold-start latency, but reversed in favour of inside-VPC (§9 above). The defense-in-depth and future-VPC-access wins outweighed the ENI-attach cost, especially given Hyperplane ENI reuse across warm invocations.
- **Lambda + shadow queues running alongside docker-compose workers** for parallel verification. Rejected — listings projector handlers aren't idempotent enough to tolerate double-writes (would double Pinecone upserts and OpenAI embedding spend).
- **Provisioned concurrency on the listings projector.** Could remove cold-start latency on the search-index update path. Deferred — cold-start cost isn't user-visible today.

## Open follow-ups

- CloudWatch alarm on `ApproximateNumberOfMessagesNotVisible` per queue as a leading indicator of stuck workers — useful, not on the critical path for v1.
- Logfire instrumentation of Lambda invocations — would need `logfire.configure(...)` in `lambda_bootstrap.py` (after env load) plus `logfire.force_flush()` before each invocation returns. Skipped until CloudWatch Logs is shown to be insufficient.
- Audit `aws_secretsmanager_secret.app_secrets` contents against every field in `src/shared/config.py:Settings` — missing keys silently fall back to defaults. Best done as part of enabling the first event source mapping.
- Migrate the remaining workers (bookings events, screening extraction, contract-intelligence ingestion) once their EC2 deployments stabilize.
- Decommission the docker-compose fallback services after Lambda has run cleanly for ≥1 quarter without a rollback.

## Addendum: zip packaging (post-ship correction, 2026-05-12)

The "Same container image" decision in §2 / "Why this design" was reversed before any deploy, in favour of **zip + Lambda layer**. Both Lambda packaging modes were viable; the rest of this ADR is unchanged (function topology, IAM, networking, batch_size=1, feature flags, fallback story, CI pin).

### Why we flipped

- The repo's `Dockerfile` is FastAPI/uvicorn-only — `python:3.13-slim` base with no Lambda Runtime Interface Client. Reusing it as a Lambda container would require either a dual-mode entrypoint (`awslambdaric` + a script that branches on `AWS_LAMBDA_RUNTIME_API`) or switching to `public.ecr.aws/lambda/python:3.13` (and re-validating the FastAPI path on a Lambda base). Both options are workable, both add ongoing maintenance.
- Production deps measure ~150-170 MB unzipped (without dev deps). The Lambda zip+layer cap is 250 MB combined — comfortably under.
- Cold start is faster with the managed Python 3.13 runtime than with a custom container image (no ENI + image-layer fetch).
- One deps layer is shared across all three functions — built once per push, attached by ARN to each.

### What the deploy pipeline actually does

```
push to main → .github/workflows/deploy.yml
  ├─ uv sync --no-dev          (resolves Linux x86_64 wheels on ubuntu-latest)
  ├─ build  lambda-deps.zip    (layer/python/lib/python3.13/site-packages/)
  ├─ build  lambda-app.zip     (src/ contents at the zip root)
  ├─ aws lambda publish-layer-version → capture LayerVersionArn
  ├─ for each function:
  │    ├─ aws lambda update-function-code  --zip-file lambda-app.zip
  │    ├─ aws lambda wait function-updated
  │    ├─ aws lambda update-function-configuration --layers <ARN>
  │    └─ aws lambda wait function-updated
  └─ ssm send-command → EC2 docker compose pull + up -d
```

### What terraform owns vs CI owns

| | Terraform | CI |
|---|---|---|
| Function shape (memory, timeout, vpc_config, IAM, env, handler) | Yes | No |
| `package_type = "Zip"`, `runtime`, `architectures` | Yes | No |
| Function code body (`filename` / `source_code_hash`) | Placeholder only | Updates via `update-function-code` |
| Layer attachment (`layers`) | Ignored | Updates via `update-function-configuration` |
| Layer version lifecycle | Not managed (no `aws_lambda_layer_version` resource) | `publish-layer-version` per deploy |

Terraform points each function at `data.archive_file.lambda_placeholder` — a one-file zip that raises if invoked. `lifecycle { ignore_changes = [filename, source_code_hash, layers] }` keeps terraform from fighting CI. Old layer versions accumulate in AWS (each `publish-layer-version` is a new revision); occasional cleanup is a follow-up.

### Tradeoff accepted

- Two deploy artifacts: Docker image for EC2, zip+layer for Lambda. They're independent paths anyway — the EC2 deploy and the Lambda deploy don't share state. The single-image goal was an "if it's free" preference, not a hard requirement; it cost too much in Dockerfile complexity.

## Addendum — 2026-05-13: Coolify as the active runtime

Spec `2026-05-coolify-compose-prod` (paired with `2026-05-rabbitmq-transport-adapter`) supersedes this ADR's runtime choice. **Production now runs on Coolify** via `deploy/docker-compose.prod.yml`: nginx + api + three always-on long-running workers (`extraction-worker`, `enrichment-worker`, `listings-events-worker`) + rabbitmq + redis. Workers consume from RabbitMQ via the shared `EventBusWorker` poll loop on top of `RabbitMQMessageConsumer` (see [ADR-008 addendum](008-event-bus-ports-and-fanout.md#addendum--2026-05-13-rabbitmq-as-the-active-transport)).

**What's dormant but kept:**

- The Lambda entrypoints in `src/**/lambda_*.py` and the shared `lambda_handler.py` / `lambda_bootstrap.py`.
- `terraform/production/lambda*.tf`, the SQS event-source-mappings, SNS topics + per-context queues.
- The `.github/workflows/deploy.yml` CI pipeline (zip + layer publish + EC2 SSM redeploy).
- `deploy/user_data.sh.tpl` (EC2 boot template).
- The SNS+SQS adapter classes at `src/shared/events/adapters/sns_event_publisher.py` / `sqs_command_publisher.py` / `sqs_message_consumer.py`.

To revert to the Lambda path, the operator restores the bootstrap import swap (replace RabbitMQ imports with SNS+SQS), re-enables the `aws_lambda_event_source_mapping` `enabled` terraform vars, and stops the Coolify deploy. The reverse-revert is a single import swap.

**Why move off Lambda:** single-tenant deploy, cost + ops surface of running SNS + SQS + Lambda + EC2 + ALB doesn't justify the elasticity Lambda provides at this scale. Coolify's docker-compose runtime is one host, persistent volumes for RabbitMQ + Redis, and a much smaller AWS footprint (S3 only). Lambda + EC2 + Terraform are kept as an emergency escape hatch only.
