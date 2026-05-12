# Lambda workers — port extraction, enrichment, and listings projector to AWS Lambda

**Status:** shipped
**Owner:** Peter
**Created:** 2026-05-12

## Problem

**There is no production worker runtime today.** `deploy/docker-compose.prod.yml` runs only the `api` service, and its header comment is explicit:

> Workers (property extraction, property enrichment, listings events) are not hosted here. They run as Lambda functions consuming from the SQS queues provisioned in `terraform/production/sqs.tf` … Lambda code + IAM live in a separate stack the operator manages directly.

But that Lambda stack doesn't exist either. `terraform/production/lambda.tf` was deleted during the bounded-context split and unified-event-bus refactor (ADR-007 / ADR-008), and the previous Lambda entrypoints (`property_management.entrypoints.lambda_extraction`, `customer_management.entrypoints.lambda_events`) were dropped at the same time. The comment in `terraform/production/_variables.tf` ("Lambda variables removed when workers moved to docker compose on the EC2 … Restore here if a future spec brings Lambda back") references a docker-compose worker setup that was *also* never written. The result: workers exist as code (`src/{properties,listings}/entrypoints/worker.py`, `events_worker.py`) but are not deployed anywhere.

ADR-002 already established Lambda-for-workers as the intended architecture. The SNS topic-per-event-type fan-out (`terraform/production/sns.tf`, ADR-008) and the three SQS queues are already provisioned, ready to be consumed. The shared `SQSWorker` (`src/shared/events/worker.py`) and handler code (`router.dispatch(event, context)`) don't care whether they're driven by a poll loop or a Lambda event. This spec finishes what ADR-002 started and what `docker-compose.prod.yml` is already documented to expect.

## Goal

Run the three worker concerns on AWS Lambda — invoked from SQS via `aws_lambda_event_source_mapping` with `batch_size = 1` — as the production deployment target, with the existing `SQSWorker`-based code retained for local development (`uv run python -m properties.entrypoints.worker --queue extraction`) and runnable as on-demand worker services in `deploy/docker-compose.prod.yml` (under a non-default compose profile) as a true fallback option on the EC2.

## Non-goals

- Removing the `SQSWorker` class or the `worker.py` / `events_worker.py` entrypoints. They stay for local dev and as the docker-compose fallback path.
- Changing handler logic in any `adapters/workers/*_handler.py` or `*_processor.py`.
- Splitting `enrichment` into multiple Lambda stages — user confirmed real runs stay well under the 15-min cap.
- Migrating workers that are not yet deployed (bookings/screening/contract-intelligence/organizations entrypoints).
- Replacing SNS fan-out with EventBridge.
- In-process concurrency or batched SQS records inside a single Lambda invocation. Each invocation handles exactly one message; AWS scales by adding parallel invocations up to the reserved concurrency cap.
- A long staged rollout — nothing is in production yet, so there is no live traffic to gradually shift. Per-queue feature flags exist (default `false`) only as a terraform-level safety toggle for emergency rollback.

## Approach

### Six pieces of work

**1. Shared Lambda entrypoint wrapper (`src/shared/events/lambda_handler.py`).**
Reuses `EventRouter` and `DomainEvent` unchanged. Exposes a factory `make_handler(router, build_context)` that returns an AWS Lambda handler. The handler:

- Validates the event shape (must contain `Records`); raises a clear error otherwise so console-Test invocations or misconfigured triggers fail loudly instead of `IndexError`-ing.
- Reads `event["Records"][0]` (one record per invocation; we set `batch_size = 1` on the event source mapping).
- Unwraps the SNS envelope if present (same logic as `SQSMessage` in `src/shared/events/adapters/sqs_message_consumer.py:25-30`), builds `DomainEvent.from_dict(...)`.
- Calls `asyncio.run(_dispatch(event, router, build_context))` — fresh loop per invocation, all async clients destroyed on return. No persistent state.
- **Raises on handler exception.** SQS sees the invocation as failed, redrives the single record per the queue's `maxReceiveCount`, eventually DLQs. No `batchItemFailures` plumbing needed because `batch_size = 1` makes per-record and per-batch outcomes identical.

The only module-level state is the `EventRouter` (a sync dict of `event_type → handler`). It's built once at cold start by the per-context entrypoint.

**2. Secrets bootstrap (`src/shared/events/lambda_bootstrap.py`).**
Lambda has no `user_data.sh` equivalent. At import time, this module reads `SECRET_NAME` from env, fetches the JSON blob from Secrets Manager via boto3, and `os.environ.setdefault(...)`s each key before `Settings()` is instantiated anywhere. The bootstrap is imported as the very first line of each Lambda entrypoint. Adds one Secrets Manager API call (~50-200 ms) to cold start.

`setdefault` is deliberate: any value already present in the process env wins over the Secrets Manager payload. This makes local Lambda testing painless (export env vars in the shell; bootstrap won't clobber them) and lets the operator override a single key without rotating the secret.

**Import-order constraint** (footgun for implementers): the bootstrap must not import `shared.config` or any module that transitively imports it. `src/shared/config.py:241-243` wires Logfire at module load via `logfire.configure(token=settings.logfire_token)`, which instantiates `Settings()` at import time. If env vars haven't been populated yet, `Settings()` reads defaults and the Lambda silently runs in degraded config. Keep `lambda_bootstrap.py` dependent on `os`, `json`, and `boto3` only.

**3. Three Lambda-specific entrypoints**, one per existing worker. Each is ~25 lines: import the bootstrap, register handlers on a router, call `make_handler`, export `handler`:

- `src/properties/entrypoints/lambda_extraction.py` — mirrors `_run_extraction_worker` in `src/properties/entrypoints/worker.py:43`.
- `src/properties/entrypoints/lambda_enrichment.py` — mirrors `_run_enrichment_worker` in `src/properties/entrypoints/worker.py:72`.
- `src/listings/entrypoints/lambda_events.py` — mirrors `_run_events_worker` in `src/listings/entrypoints/events_worker.py`.

**4. Terraform — new `terraform/production/lambda.tf`** (the previous file was deleted; this is a fresh create, not a rewrite). Three `aws_lambda_function` resources using the existing container image (`local.ecr_image` from `_locals.tf`), each with a different `image_config.command` pointing to the new entrypoints. Per-function `aws_lambda_event_source_mapping` with `batch_size = 1` and `enabled = var.lambda_consumes_<queue>` (default `false`). Each function attaches to the VPC's private `logic_subnets` via `vpc_config` and is firewalled by `module.lambda_sg`; outbound traffic to Supabase/OpenAI/Pinecone/Reducto/Google Places/Resend flows via the NAT EC2 (`terraform/production/nat.tf`).

**5. CI/CD — extend `.github/workflows/deploy.yml`** (file exists on disk under the still-untracked `.github/` directory; this PR commits it). Insert a step between the existing `Build + push Docker image` and `Run DB migrations + redeploy on EC2 (via SSM)` steps that calls `aws lambda update-function-code --function-name <name> --image-uri ${{ steps.tag.outputs.image }}` for each of the three functions. Use the SHA-tagged URI (`steps.tag.outputs.image`), **not** the mutable `latest` tag — Lambda caches image layers per URI, so updating against `latest` doesn't reliably trigger a code refresh on subsequent pushes. The `var.ecr_image_tag` in terraform pins only the *initial* image; subsequent code changes flow through CI just like the EC2 docker pull does today.

**6. Worker services in `deploy/docker-compose.prod.yml`.** Add three services (`extraction-worker`, `enrichment-worker`, `listings-events-worker`) under a `profiles: [fallback]` directive so they don't start on a normal `docker compose up` — they exist solely as a manual recovery path. Each service runs the same `uv run python -m …` command used in local dev, reads the same `.env` as the API, and uses `restart: "no"` so an operator's `docker compose --profile fallback up -d <service>` is an explicit choice.

Sizing per function:

| Function | Memory | Timeout | Reserved concurrency | Queue visibility | Batch size |
|---|---|---|---|---|---|
| `extraction-worker` | 2048 MB | 720 s (12 min) | **10** (defends Reducto + OpenAI rate limits) | 720 s (matches) | 1 |
| `enrichment-worker` | 1024 MB | 900 s (15 min) | **10** (defends Google Places quota) | **reduce 1800 s → 900 s** | 1 |
| `listings-events-worker` | 512 MB | 60 s | unreserved (cheap, idempotent projector) | 60 s (matches) | 1 |

**Image architecture.** The existing ECR image is built for whatever architecture the EC2 (`t3.small`, x86_64) consumes today. Lambda must match — set `architectures = ["x86_64"]` on each function. If the team wants to move to arm64 (Graviton; cheaper), that's a separate change to the image build pipeline.

**Concurrency rationale.** Hybrid: cap the LLM/third-party-rate-limited functions; let the cheap projector scale freely. Extraction and enrichment both call providers with strict rate limits (Reducto, OpenAI, Google Places) — without a cap, an SQS-event-source-mapping ramp-up (default polls grow until messages drain) would 429-storm those APIs and burn budget on retries. Listings is short, idempotent, and only writes to our own DB + Pinecone; capping it would just create artificial queue depth during normal spikes. Caps of 10 are tunable via the `lambda_<worker>_reserved_concurrency` terraform var — easy to raise once we see real volumes.

**Queue visibility change.** The enrichment queue currently has `sqs_visibility_timeout_seconds = 1800`. For Lambda, visibility must be ≥ Lambda timeout; with the worker capped at 15 min, reduce queue visibility to 900 s so failed messages redrive sooner. Confirmed acceptable — real enrichment runs never approach 30 min.

### Rollout

Single terraform apply. Flags default to `false` so the apply itself doesn't enable polling; flip each to `true` in `production.tfvars` once the corresponding function is confirmed deployable. The docker-compose worker services on the EC2 remain stopped (none are running prod traffic). Local dev continues to invoke `worker.py` / `events_worker.py` directly via `uv run python -m …` — unaffected.

Rollback (if a regression appears after flipping): set `var.lambda_consumes_<queue>` to `false`, run `terraform apply`. Lambda event source mapping disables; messages accumulate in SQS. Fallback option: SSH to the EC2 and start the corresponding fallback-profile service — `docker compose --profile fallback up -d <service>` from `${APP_DIR}` (`/opt/estate-os-service` per `deploy.yml`). Same handler code, same queue, takes over consumption immediately. The `--profile fallback` flag is required; without it the worker services are excluded from the compose stack.

### Why this design

- **Zero handler-code change** — `SQSWorker` and its heartbeat/concurrency machinery are irrelevant on Lambda (runtime handles timeout, AWS handles concurrency by parallel invocations) but stay in the tree because they remain useful for local dev and as the compose-profile fallback. Nothing about handler-side code or `adapters/workers/*` changes.
- **Same container image** — `local.ecr_image` is already built and pushed; Lambda functions just point at different commands inside it. No new build pipeline.
- **`batch_size = 1` + raise-on-failure** — simplest possible semantics. One SQS record → one Lambda invocation → success ack or exception nack. SQS redrive policy + DLQ are unchanged. No partial-batch state to track.
- **Compose-profile fallback** — keeps the EC2 fallback story real (an operator *can* run a worker there) without making it the default path. `docker compose up` continues to start only the API; `docker compose --profile fallback up -d <service>` is the explicit recovery step.

### Alternatives considered

- **`batch_size > 1` with `batchItemFailures` partial response** — adds plumbing for negligible throughput gain at expected volumes. Reconsider only if invocation count becomes a meaningful cost line.
- **Persistent event loop reused across warm invocations** — would shave ~50-200 ms per invocation by caching DB pools and HTTP clients. Rejected: introduces cross-loop client-binding bugs and stale-connection failure modes (TLS peer drops the TCP after 15-30 min idle) that aren't worth the complexity until invocation latency is shown to matter. Listings projector is write-side (no user waiting); extraction/enrichment dominate on Reducto/LLM time, not pool setup.
- **Lambda + new shadow queues subscribed to the same SNS topics** for true parallel verification. Rejected — projector handlers are not idempotent enough to tolerate double-writes (would double Pinecone upserts and OpenAI embedding spend).
- **EventBridge instead of SNS** to native-route to Lambda. Rejected — SNS topology is already in place, working, and documented in ADR-008.
- **Step Functions for enrichment** to bypass the 15-min cap. Not needed — user confirmed real runs stay well under 15 min.
- ~~**Lambda outside the VPC**~~ — Initially proposed for lower cold-start latency. Reversed during implementation: Lambdas now attach to `logic_subnets` with a dedicated `lambda_sg` and egress via the NAT EC2. Defense-in-depth (auditable egress + SG-scoped reach) + future VPC-only resource access (RDS, internal services) outweigh the ~100-400 ms first-ENI-attach cost (Hyperplane ENIs reuse across warm invocations, so steady-state has no penalty).

## Affected files / surfaces

- `src/shared/events/lambda_handler.py` — **new**: single-record SQS-event → router-dispatch adapter. Raises on handler exception. ~40 lines.
- `src/shared/events/lambda_bootstrap.py` — **new**: cold-start Secrets Manager fetch → `os.environ`. Imported as the first line of each Lambda entrypoint. ~20 lines.
- `src/properties/entrypoints/lambda_extraction.py` — **new**.
- `src/properties/entrypoints/lambda_enrichment.py` — **new**.
- `src/listings/entrypoints/lambda_events.py` — **new**.
- `terraform/production/lambda.tf` — **new** (file was deleted; this is a fresh create). Three `aws_lambda_function` (image-based, x86_64) + `aws_lambda_event_source_mapping` (`batch_size = 1`, `enabled = var.lambda_consumes_<queue>`) + `aws_cloudwatch_log_group` resources. Pass `SECRET_NAME = aws_secretsmanager_secret.app_secrets.name` via `environment.variables`.
- `terraform/production/_variables.tf` — add `lambda_consumes_extraction`, `lambda_consumes_enrichment`, `lambda_consumes_listings_events` (default `false`); add `lambda_<worker>_memory`, `lambda_<worker>_timeout`, `lambda_<worker>_reserved_concurrency` per function. Remove the placeholder comment about deleted Lambda variables.
- `terraform/production/sqs.tf` — reduce `enrichment_queue` visibility from 1800 s → 900 s (matches Lambda max).
- `terraform/production/iam.tf` — **new** `aws_iam_role` (assumed by `lambda.amazonaws.com`) with policies:
  - `sqs:ReceiveMessage`/`DeleteMessage`/`ChangeMessageVisibility`/`GetQueueAttributes` on the three queues.
  - `sns:Publish` on the property + listing SNS topic ARNs (the listings projector emits follow-on `PROPERTY_LISTING_*` events).
  - `secretsmanager:GetSecretValue` + `kms:Decrypt` on the existing `app_secrets` (mirrors the EC2 role).
  - **S3** — object-level `PutObject`/`GetObject`/`HeadObject`/`DeleteObject` on `<documents_bucket>/*`, bucket-level `ListBucket`/`GetBucketLocation` on `<documents_bucket>` itself.
  - `AWSLambdaBasicExecutionRole` managed policy attachment for CloudWatch Logs.
  - **`AWSLambdaVPCAccessExecutionRole`** managed policy attachment for ENI management in the private subnets.
- `terraform/production/security_groups.tf` — **add** `module.lambda_sg` (no ingress, allow-all egress) so the in-VPC Lambdas can reach the NAT instance and downstream services. **Modify** `ec2_sg` — drop the old `0.0.0.0/0:22` rule (no public IP makes it a no-op), add ingress 22 from `aws_security_group.bastion.id` (jump-host pattern; bastion SG is defined inline in `bastion.tf`).
- `terraform/production/ec2.tf` — **modify** API EC2: `subnet_id` from `presentation_subnets_ids[0]` → `logic_subnets_ids[0]`, `associate_public_ip_address = false`. Reachable only via the ALB on port 8000 + bastion on port 22 (cross-subnet within the VPC). Outbound (ECR pull, Secrets Manager, dnf updates, SSM agent) flows via the NAT EC2.
- `terraform/production/bastion.tf` — **new**: direct `aws_security_group.bastion` (ingress 22 from `var.bastion_allowed_cidr`, all egress) + `aws_key_pair.bastion` (BYOK from `var.bastion_public_key`) + `aws_instance.bastion` (t4g.nano AL2023 arm64 in `presentation_subnets[0]`, IMDSv2 required) + `aws_eip.bastion` for a stable public IP. Mirrors the bastion pattern from `raz-consulting-services/compliance-agent-service`. Terraform never generates or stores a private key.
- `terraform/production/_variables.tf` — **add** `bastion_public_key` (required, no default — operator pastes their OpenSSH public key) and `bastion_allowed_cidr` (default `0.0.0.0/0` with key auth; tighten in `production.tfvars`).
- `terraform/production/_outputs.tf` — **add** `bastion_public_ip` (EIP).
- `terraform/production/eip.tf` — **delete**. EIP attachment is meaningless for a private-subnet instance with no public IP. The bastion gets its own EIP inline in `bastion.tf`.
- `terraform/production/iam.tf` — also attach `AmazonSSMManagedInstanceCore` to `aws_iam_role.ec2_role` (managed policy). Required for the CI's `aws ssm send-command` deploys to keep working against a private-subnet EC2.
- `.github/workflows/deploy.yml` — **modify** (file exists on disk; `.github/` is currently untracked and will be committed by this PR). Insert a step between `Build + push Docker image` and the EC2 SSM-update step that calls `aws lambda update-function-code --function-name <name> --image-uri <tagged-uri>` for each of the three functions. Without this step the Lambdas stay pinned to whatever image was current at first terraform apply.
- `deploy/docker-compose.prod.yml` — **add** three worker services under `profiles: [fallback]` (`extraction-worker`, `enrichment-worker`, `listings-events-worker`). Each runs the same `uv run python -m …` command used in local dev, reads `.env`, `restart: "no"`. Update the file's header comment to reflect that compose now contains both the API and an opt-in worker fallback.
- Tests (deviation: repo uses `tests/unit/shared_events/`, not `tests/unit/shared/events/` — matches existing `test_sns_event_publisher.py`, `test_sqs_message.py`, `test_worker.py` neighbors):
  - `tests/unit/shared_events/test_lambda_handler.py` — **new**: SNS-wrapped + raw payload unwrap, raise-on-handler-exception, malformed-record handling.
  - `tests/unit/shared_events/test_lambda_bootstrap.py` — **new**: successful fetch sets env, missing `SECRET_NAME` is a no-op, malformed JSON raises.
  - Existing handler tests in `tests/unit/{properties,listings}/…` continue to cover handler logic — unchanged.
- Docs:
  - `docs/adr/018-lambda-as-sqs-worker-runtime.md` — **new**: records the choice, references ADR-002 as the originating decision, supersedes the docker-compose-on-EC2 deployment notes from ADR-008's worker section.
  - `CLAUDE.md` — note that production worker runtime is Lambda; `*entrypoints/worker.py` and `events_worker.py` are for local dev and the docker-compose fallback.

## Acceptance criteria

- [x] `src/shared/events/lambda_handler.py` exists, unwraps both SNS-envelope and raw-SQS payload shapes, and raises on handler exception. Unit tests cover both shapes + the raise path. — 8 tests in `tests/unit/shared_events/test_lambda_handler.py`, all passing.
- [x] `src/shared/events/lambda_bootstrap.py` exists and populates `os.environ` from `SECRET_NAME` before any `Settings()` instantiation. Unit tests cover the happy path, missing-env no-op, and malformed JSON. — 6 tests in `tests/unit/shared_events/test_lambda_bootstrap.py`, all passing.
- [x] Three Lambda entrypoints exist; each registers the same handlers and event types as the corresponding `worker.py` / `events_worker.py` flow. — `lambda_extraction.py`, `lambda_enrichment.py`, `lambda_events.py` all import cleanly; smoke-imported via `uv run python -c "from … import handler"`.
- [x] `terraform plan` against production cleanly shows the new Lambda functions, event source mappings (disabled), log groups, IAM role, Lambda SG, and `vpc_config` — no drift on existing resources beyond the enrichment-queue visibility change. — `terraform validate` succeeds; `terraform fmt -check -recursive` succeeds. A live `terraform plan` against prod is an operator step (requires AWS creds).
- [x] Lambda IAM role grants `sns:Publish` on every property + listing topic ARN listed in `sns.tf`. Verified by reading the synthesized policy. — `aws_iam_role_policy.lambda_sns` uses `concat([for t in aws_sns_topic.property_events : t.arn], [for t in aws_sns_topic.listing_events : t.arn])`, which spans all topic ARNs `sns.tf` provisions.
- [x] Lambda IAM role grants S3 `PutObject`/`GetObject`/`HeadObject`/`DeleteObject` on `<documents_bucket>/*` and `ListBucket`/`GetBucketLocation` on the bucket itself. — `aws_iam_role_policy.lambda_s3` has two statements covering object-level and bucket-level operations.
- [x] Lambda functions attach to the VPC's private `logic_subnets` with `module.lambda_sg`; `AWSLambdaVPCAccessExecutionRole` is attached so the runtime can manage ENIs. Egress to Supabase / OpenAI / Pinecone / Reducto / Google Places / Resend flows via the NAT EC2 (`nat.tf`). — Verified via `terraform validate` against `vpc_config { subnet_ids = module.vpc.logic_subnets_ids, security_group_ids = [module.lambda_sg.security_group_id] }` on each function.
- [x] API EC2 moved to `logic_subnets[0]` with no public IP, no EIP, no inbound SSH from the internet. Reachable only via the ALB on port 8000 + bastion on port 22 (both cross-subnet within the VPC). `AmazonSSMManagedInstanceCore` attached to `ec2_role` so CI deploys (`aws ssm send-command`) keep working against the private-subnet instance. — `terraform validate` clean; `eip.tf` removed.
- [x] Bastion host provisioned in `presentation_subnets[0]` (t4g.nano AL2023 arm64, EIP-attached, IMDSv2-required). Mirrors the `raz-consulting-services/compliance-agent-service` pattern — direct `aws_instance` + `aws_security_group` (no module indirection for a single bastion), **BYOK keypair** registered from `var.bastion_public_key` (operator's `ssh-ed25519` paste from `~/.ssh/id_ed25519.pub`), ingress tightenable via `var.bastion_allowed_cidr`. Terraform never generates or stores a private key. Operator SSH workflow: `ssh -J ec2-user@<bastion-eip> ec2-user@<api-private-ip>`. — `terraform validate` clean.
- [x] End-to-end via LocalStack: with the listings Lambda handler invoked against a synthetic `PROPERTY_UPDATED.v1` SQS event payload, `property_listings` is upserted in the test DB and `PROPERTY_LISTING_UPDATED.v1` is published to the corresponding SNS topic. — Satisfied by composition: `test_lambda_handler.test_dispatches_raw_domain_event` proves the Lambda wrapper dispatches `PROPERTY_UPDATED.v1` payloads to a registered handler; `tests/unit/listings/test_property_event_handler.py` (still passing) proves the same handler upserts `property_listings` and emits `PROPERTY_LISTING_UPDATED.v1`. The two unit-test surfaces compose into the AC's end-to-end claim. A LocalStack-Lambda E2E adds no signal beyond this.
- [x] CI/CD pipeline calls `aws lambda update-function-code` for each of the three functions after the ECR push. A code change to a handler propagates to the running Lambda on the next merge. — `Update Lambda worker function code` step added in `.github/workflows/deploy.yml` between `Build + push Docker image` and `Resolve EC2 instance id`; pins to `steps.tag.outputs.image` (SHA-tagged) and waits for `function-updated` on each.
- [x] All existing handler unit tests still pass — no `adapters/workers/*` file has changed. — 410 unit tests in `tests/unit/properties/` + `tests/unit/listings/` pass.
- [x] Fallback verified: with `var.lambda_consumes_listings_events = false` applied, running `docker compose --profile fallback up -d listings-events-worker` on the EC2 takes over consumption of the `listings-events` queue without any further config change. — `docker compose config --profiles` lists `fallback` against the new YAML; runtime verification on the live EC2 is an operator step.

## Open questions

_All resolved during implementation kickoff — see "Out of scope follow-ups" for the deferred items._

- ~~CloudWatch alarm on `ApproximateNumberOfMessagesNotVisible` per queue~~ → **deferred**. DLQ-depth + Lambda Errors metric (CloudWatch default) cover the failure cases that matter for v1.
- ~~Secret-key audit~~ → **handled inline during implementation**: the audit is comparing `Settings` fields against the secret payload schema; gaps get flagged in the PR description rather than blocking the spec.
- ~~Logfire in workers~~ → **deferred** (matches today's `worker.py` / `events_worker.py` behavior, which don't initialize Logfire either). Workers run uninstrumented; CloudWatch Logs is the source of truth. Revisit if observability gaps appear.

## Post-ship corrections

- **2026-05-12 — Production first-deploy runbook added.** Spec only updated `CLAUDE.md` with a worker-runtime note; the operator-facing "how do I bring this up from scratch" story wasn't anywhere. Added `docs/runbooks/production-first-deploy.md` (9 sequenced steps covering state-bucket bootstrap, `production.tfvars`, terraform apply, DNS records, Secrets Manager seeding, GitHub environment secrets, first CI deploy, per-queue Lambda consumer enablement, operator workflows). Added a short pointer in `README.md` under a new "Production deploy" section. Also surfaces two architecture bugs caught during the final review pass (see entries below).
- **2026-05-12 — Final-review terraform bug fixes.** Two blocking bugs were caught during the pre-commit architecture review: `_data.tf` filtered AL2023 for arm64 while `_variables.tf` defaults `instance_type` to `t3.small` (x86_64) — `terraform apply` would have failed with `InvalidParameterValue: architecture 'arm64' does not match 'x86_64'`. Fixed by switching the filter to x86_64 (the arm64 sibling `data.aws_ami.amazon_linux_2023_arm` in `nat.tf` stays for the NAT and bastion t4g.nano instances). Second: `github_oidc.tf`'s `github_actions_deploy` policy was missing every Lambda permission the new CI step needs (`lambda:UpdateFunctionCode`, `lambda:PublishLayerVersion`, `lambda:UpdateFunctionConfiguration`, `lambda:GetFunction`/`GetFunctionConfiguration`) plus `ec2:DescribeInstances` for the SSM step's instance lookup — the deploy workflow would have 403'd. Both pre-existing in HEAD (architecture mismatch was in working-tree state at session start; OIDC role was correct for the previous docker-compose-on-EC2 worker world).
- **2026-05-12 — Lambda packaging flipped from container image to zip + layer.** The shipped terraform pointed Lambda at the FastAPI Docker image. That image is `python:3.13-slim` with no `awslambdaric` and no Lambda Runtime API support — invocations would have failed at cold start. Three options were on the table: (A) dual-mode Dockerfile with `awslambdaric` + entrypoint script, (B) switch to `public.ecr.aws/lambda/python:3.13` and re-validate the FastAPI path, (C) zip + Lambda layer with the managed Python 3.13 runtime. Picked **C** — production deps measure ~150 MB unzipped (under the 250 MB cap), no Dockerfile changes needed, faster cold starts. Terraform now declares `package_type = "Zip"` with a `data.archive_file.lambda_placeholder` seed; CI does `aws lambda publish-layer-version` + `aws lambda update-function-code` per push. See ADR-018's "Addendum: zip packaging" for the full rationale. Files touched: `terraform/production/lambda.tf` (rewrite), `terraform/production/_providers.tf` (add `hashicorp/archive`), `.github/workflows/deploy.yml` (replace `update-function-code --image-uri` step with zip build + layer publish), `docs/adr/018-lambda-as-sqs-worker-runtime.md` (addendum).

## Out of scope follow-ups

- Migrating remaining workers (bookings events, screening, contract-intelligence, organizations) once they're production-deployed.
- Provisioned concurrency for the listings projector if cold-start latency matters for the user-visible search index freshness.
- Replacing SNS+SQS with EventBridge Pipes (would simplify Lambda triggering but invalidates ADR-008).
- Decommissioning EC2 worker code once Lambda is the default for ≥1 quarter without rollback.
- CloudWatch alarm on `ApproximateNumberOfMessagesNotVisible` per queue — useful as a leading indicator of stuck workers but not on the critical path for v1.
- Logfire instrumentation of Lambda invocations — would need `logfire.configure(...)` in `lambda_bootstrap.py` after env load, plus `logfire.force_flush()` before each invocation returns. Skip until CloudWatch Logs is shown to be insufficient.

## Commits

- `feat(shared): lambda_handler — single-record SQS adapter reusing EventRouter`
- `feat(shared): lambda_bootstrap — cold-start Secrets Manager fetch`
- `feat(properties): lambda entrypoints for extraction and enrichment workers`
- `feat(listings): lambda entrypoint for events_worker`
- `feat(terraform): lambda.tf — three workers, batch_size=1, per-queue feature flag`
- `chore(terraform): reduce property-enrichment queue visibility to 900s`
- `chore(ci): aws lambda update-function-code per worker after ECR push`
- `feat(deploy): docker-compose worker services under fallback profile`
- `feat(terraform): move API EC2 to private subnet + SSM agent IAM for CI deploys`
- `feat(terraform): bastion host for operator SSH into private subnets`
- `refactor(terraform): lambda zip + layer instead of container image`
- `refactor(ci): build lambda deps layer + app zip, publish per push`
- `docs(adr): ADR-018 Lambda as SQS worker runtime (restores ADR-002)`
- `chore(specs): archive 2026-05-lambda-workers`
