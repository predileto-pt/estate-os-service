# ADR-002: Hybrid deployment — EC2 for API, Lambda for SQS workers

## Status

Accepted (supersedes original full-EC2 proposal)

## Date

2026-03-17

## Context

The `customers-dashboard-service` runs on AWS Lambda with three functions: an HTTP API (FastAPI via Mangum + API Gateway), an SQS extraction worker, and an SQS events worker.

The API suffers from several Lambda limitations:

- **Cold starts**: Python 3.13 with heavy dependencies (OpenAI, Reducto, SQLAlchemy, Supabase) leads to slow cold starts that degrade user experience.
- **Timeout constraints**: The 30s API Gateway timeout is too tight for presigned URL flows and complex queries.
- **Mangum overhead**: The ASGI-to-Lambda adapter adds latency and complexity.
- **No persistent connections**: The Supabase client is recreated per invocation, preventing connection pooling.

However, the **SQS workers do not share these problems**. They are asynchronous — users don't wait for their results. Cold starts are invisible, and Lambda's SQS event source mapping provides automatic scaling, retries, and DLQ handling with zero polling infrastructure.

The `applicants-intake-service` already has reusable Terraform modules for EC2, ALB, VPC, security groups, ACM, ECR, and EIP. These modules have been copied into this project.

## Decision

Deploy the API on a single EC2 instance behind an Application Load Balancer. Keep the SQS workers as Lambda functions triggered by SQS event source mappings.

### Architecture

```
                    ┌─────────┐
Internet ──HTTPS──► │   ALB   │
                    └────┬────┘
                         │ :8000
                    ┌────▼────────────────────┐
                    │  EC2 (t3.small)          │
                    │  ┌────────────────────┐  │
                    │  │ api (uvicorn :8000) │  │
                    │  └────────────────────┘  │
                    └──────────────────────────┘

     ┌──────────────────┐         ┌──────────────────┐
     │  extraction-queue │         │  events-queue     │
     └────────┬─────────┘         └────────┬─────────┘
              │ SQS trigger                │ SQS trigger
     ┌────────▼─────────┐         ┌────────▼─────────┐
     │  Lambda:          │         │  Lambda:          │
     │  extraction-worker│         │  events-worker    │
     │  (15 min timeout) │         │  (2 min timeout)  │
     └──────────────────┘         └──────────────────┘
```

### Key choices

- **EC2 for API only**: The API benefits from persistent connections, no cold starts, and no timeout constraints. A `t3.small` (2 vCPU, 2 GB RAM) is sufficient.
- **Lambda for workers**: SQS event source mappings handle polling, scaling, retries, and DLQ — no infrastructure to manage. The 15-minute Lambda timeout accommodates most extraction jobs; failures are retried via SQS visibility timeout + DLQ.
- **Same ECR image**: Both EC2 and Lambda use the same Docker image, just with different entrypoints.
- **Local dev uses polling workers**: The `worker.py` entrypoints (long-polling SQS) remain for local development where there's no Lambda trigger. Production uses `lambda_extraction.py` and `lambda_events.py`.

## Consequences

### Pros

- No cold starts on the API — the app is always warm for user-facing requests
- Persistent database connections via Supabase client reuse (API)
- No timeout constraints on the API
- No polling infrastructure to maintain for workers — Lambda + SQS handles it
- Workers scale automatically with queue depth
- Workers are pay-per-invocation — no cost when idle

### Cons

- Must manage the EC2 instance (OS patching, monitoring, restarts) for the API
- Two deployment targets (EC2 + Lambda) instead of one
- Lambda cold starts still apply to workers (acceptable since they're async)
- 15-minute Lambda timeout limits very long extraction jobs (mitigated by SQS retries + DLQ)

### Neutral

- Keep ECR for Docker images (same build pipeline)
- Keep same CI/CD OIDC pattern for GitHub Actions (SSM for EC2, UpdateFunctionCode for Lambda)
- Keep SQS queues with existing DLQ configuration
- Keep Secrets Manager for configuration
