# ADR-004: gRPC inter-service communication with BFF pattern

## Status

Proposed

## Date

2026-03-18

## Context

Portolar has grown into multiple backend services that need to communicate synchronously:

| Service | Role |
|---------|------|
| **estate-os** (formerly customers-dashboard-service) | BFF — single API entry point for all clients |
| **applicants-intake-service** | Applicant screening, document extraction, intake forms |
| **contract-intelligence-service** | Document intelligence and contract analysis |

Today, inter-service communication is exclusively asynchronous via SQS. This works for background jobs (property extraction, applicant screening) but falls short for synchronous flows. For example, when a client submits an intake request form, estate-os must call applicants-intake-service and return the result — there is no SQS queue for this.

Additionally, each service currently exposes its own HTTP API, requiring either multiple API Gateway deployments (expensive, ~$3.50/million requests + data transfer) or direct client-to-service routing. We want a **single entry point** that clients talk to, with estate-os proxying to backend services internally.

### Why gRPC over REST for internal calls

- **Binary serialization (protobuf)**: smaller payloads, faster serialization than JSON
- **HTTP/2 multiplexing**: multiple concurrent RPCs over a single TCP connection — critical for the BFF pattern where one client request fans out to multiple backend calls
- **Streaming**: server-streaming and bidirectional streaming for future use cases (e.g., real-time extraction progress)
- **Code generation**: strongly-typed clients and servers from `.proto` files — no manual schema drift
- **Deadline propagation**: built-in timeout propagation across service boundaries
- **Lower latency**: benchmarks consistently show 2-10x lower latency vs REST/JSON for internal service calls

### Deployment constraints

- **estate-os**: EC2 behind ALB (ADR-002) — can make outbound gRPC calls natively
- **applicants-intake-service**: currently full Lambda behind API Gateway
- **contract-intelligence-service**: deployment TBD
- **Lambda limitation**: API Gateway and ALB→Lambda targets use HTTP/1.1, which cannot carry native gRPC (HTTP/2). Lambda is inherently request/response with cold start overhead (100ms–2s), making it unsuitable for low-latency synchronous gRPC serving

## Decision

### 1. BFF pattern — estate-os as the single API

All client-facing HTTP traffic goes through estate-os. Backend services (applicants-intake-service, contract-intelligence-service) have **no public-facing API**. They expose only internal gRPC servers accessible within the VPC.

```
                     ┌──────────────────┐
  Clients ──HTTPS──► │  ALB (public)    │
                     └────────┬─────────┘
                              │ :8000
                     ┌────────▼─────────────────────┐
                     │  estate-os (EC2)              │
                     │  ┌─────────────────────────┐  │
                     │  │ FastAPI (BFF)            │  │
                     │  │  ├─ REST routes (public) │  │
                     │  │  └─ gRPC clients         │  │
                     │  └──────┬──────────┬────────┘  │
                     └─────────┼──────────┼───────────┘
                               │          │
                    gRPC :50051│          │gRPC :50052
                               │          │
              ┌────────────────▼┐   ┌─────▼───────────────────┐
              │ applicants-     │   │ contract-intelligence-  │
              │ intake-service  │   │ service                 │
              │ (EC2, internal) │   │ (EC2, internal)         │
              └─────────────────┘   └─────────────────────────┘

     ┌───────────────────┐    ┌───────────────────┐
     │  SQS queues       │    │  SQS queues       │
     └────────┬──────────┘    └────────┬──────────┘
              │ SQS trigger            │ SQS trigger
     ┌────────▼──────────┐    ┌────────▼──────────┐
     │  Lambda workers   │    │  Lambda workers   │
     │  (async jobs)     │    │  (async jobs)     │
     └───────────────────┘    └───────────────────┘
```

### 2. Native gRPC (HTTP/2) for lowest latency

Use native gRPC over HTTP/2 for all synchronous inter-service calls. No gRPC-Web, no Connect protocol, no translation layers.

- **EC2 for gRPC servers**: backend services run their gRPC servers on EC2 instances within the VPC (same approach as estate-os in ADR-002). This avoids Lambda's cold start penalty and HTTP/1.1 limitation.
- **Lambda for async workers only**: SQS-triggered Lambda functions continue handling background jobs (extraction, screening). These are unaffected — they don't serve gRPC.
- **Internal NLB** (Network Load Balancer): routes gRPC traffic to backend EC2 instances. NLB operates at L4 (TCP passthrough), preserving HTTP/2 end-to-end with minimal added latency (~μs). ALB's gRPC support (L7) is an alternative if we need path-based routing or health checks at the gRPC level, but adds ~1-2ms overhead.

### 3. Proto definitions in the monorepo

All `.proto` files live in a shared `proto/` directory at the monorepo root:

```
portolar/
├── proto/
│   ├── applicants/
│   │   └── intake.proto        # IntakeService RPCs
│   ├── contracts/
│   │   └── intelligence.proto  # ContractService RPCs
│   └── buf.yaml                # Buf configuration
├── estate-os/                  # (renamed from customers-dashboard-service)
├── applicants-intake-service/
└── contract-intelligence-service/
```

Code generation:
- **Python**: `grpcio-tools` generates `_pb2.py` and `_pb2_grpc.py` stubs
- **Buf** (`buf.build`) for linting, breaking-change detection, and consistent codegen across services
- Generated code is committed to each service's `adapters/grpc/generated/` directory (avoids build-time codegen dependency)

### 4. Integration with hexagonal architecture

gRPC fits naturally into the existing hexagonal pattern:

```
estate-os (BFF):
  adapters/outbound/grpc/
    ├── intake_client.py          # gRPC client implementing IntakeService port
    └── generated/                # Generated protobuf stubs

applicants-intake-service:
  adapters/inbound/grpc/
    ├── intake_server.py          # gRPC server implementing IntakeServiceServicer
    └── generated/                # Generated protobuf stubs
  domain/ports/
    └── intake_service.py         # Port (Protocol) — unchanged
```

In estate-os, the gRPC client is an outbound adapter that implements a port defined in the application layer. In backend services, the gRPC server is an inbound adapter (like FastAPI routes today) that calls use cases.

### 5. Local development

For local development, services run their gRPC servers directly on localhost:

```bash
# Terminal 1: estate-os (BFF + REST API)
uv run uvicorn shared.main:app --reload --port 8000

# Terminal 2: applicants-intake-service (gRPC server)
uv run python -m applicant_management.entrypoints.grpc_server --port 50051

# Terminal 3: contract-intelligence-service (gRPC server)
uv run python -m contract_intelligence.entrypoints.grpc_server --port 50052
```

Configuration via environment variables:

```env
# estate-os .env
INTAKE_GRPC_HOST=localhost:50051
CONTRACTS_GRPC_HOST=localhost:50052

# Production (via Secrets Manager)
INTAKE_GRPC_HOST=intake-nlb.internal.portolar.com:50051
CONTRACTS_GRPC_HOST=contracts-nlb.internal.portolar.com:50052
```

### 6. Migration path

Phase 1 — **applicants-intake-service** (intake form creation):
1. Define `proto/applicants/intake.proto` with `CreateIntakeRequest` RPC
2. Implement gRPC server in applicants-intake-service as an inbound adapter
3. Implement gRPC client in estate-os as an outbound adapter
4. Deploy applicants-intake-service to EC2 with gRPC server (alongside existing Lambda workers)
5. Add estate-os route: `POST /api/v1/intake-requests` → gRPC → applicants-intake-service

Phase 2 — **contract-intelligence-service**:
1. Define `proto/contracts/intelligence.proto`
2. Same pattern: gRPC server (inbound adapter) + client (outbound adapter)

Phase 3 — **Remove public APIs from backend services**:
1. Decommission API Gateway for applicants-intake-service
2. Backend services only accessible via gRPC within VPC

### 7. Async flows remain on SQS

gRPC replaces only **synchronous** inter-service calls. Existing async flows stay on SQS:

| Flow | Protocol | Reason |
|------|----------|--------|
| Intake form creation | gRPC | Synchronous — client waits for response |
| Contract analysis request | gRPC | Synchronous — client waits for response |
| Property extraction job | SQS | Async — long-running, client polls for status |
| Applicant screening | SQS | Async — long-running, triggers email on completion |
| Domain events (UserRegistered, etc.) | SQS | Fire-and-forget event propagation |

## Alternative considered: Traefik as API gateway

Instead of estate-os acting as a BFF that proxies all traffic, deploy **Traefik** as a reverse proxy / API gateway that routes requests directly to the owning service based on path prefix.

### Architecture

```
                     ┌──────────────────────────────────┐
  Clients ──HTTPS──► │  Traefik (EC2, public)            │
                     │  TLS termination, path routing    │
                     └──┬──────────┬──────────┬─────────┘
                        │          │          │
            /api/v1/    │  /api/v1/│  /api/v1/│
          properties/*  │ intake/* │contracts/│
          users/*       │          │     *    │
          owners/*      │          │          │
                        │          │          │
               ┌────────▼───┐ ┌────▼───────┐ ┌▼──────────────────┐
               │ estate-os  │ │ applicants-│ │ contract-         │
               │ (EC2)      │ │ intake-svc │ │ intelligence-svc  │
               │ :8000      │ │ (EC2)      │ │ (EC2)             │
               │            │ │ :8001      │ │ :8002             │
               └────────────┘ └────────────┘ └───────────────────┘

     ┌───────────────────┐    ┌───────────────────┐
     │  SQS queues       │    │  SQS queues       │
     └────────┬──────────┘    └────────┬──────────┘
              │ SQS trigger            │ SQS trigger
     ┌────────▼──────────┐    ┌────────▼──────────┐
     │  Lambda workers   │    │  Lambda workers   │
     │  (async jobs)     │    │  (async jobs)     │
     └───────────────────┘    └───────────────────┘
```

### How it works

- **Traefik** runs on a single EC2 instance (or as a sidecar container). It terminates TLS, routes by path prefix, and forwards to backend services over HTTP within the VPC.
- **Each service keeps its own REST API** — no gRPC needed for the routing layer. Services are independently deployable and own their API surface.
- **Single domain, single TLS cert**: `api.portolar.com/api/v1/intake/*` → applicants-intake-service, `api.portolar.com/api/v1/properties/*` → estate-os. Clients see one API.
- **Cross-cutting concerns** (JWT auth, rate limiting, CORS, request logging) are handled in Traefik middleware, applied uniformly to all services — no need to duplicate auth logic in each service.
- **gRPC becomes optional**: only needed if services need to call *each other* (e.g., estate-os needs data from applicants-intake-service to render a combined view). Pure routing doesn't require gRPC.

### Local development

For local development, use **nginx** as a lightweight stand-in for Traefik with the same path-based routing:

```nginx
# nginx.dev.conf
upstream estate_os { server localhost:8000; }
upstream intake    { server localhost:8001; }
upstream contracts { server localhost:8002; }

server {
    listen 80;

    location /api/v1/intake        { proxy_pass http://intake; }
    location /api/v1/contracts     { proxy_pass http://contracts; }
    location /                     { proxy_pass http://estate_os; }
}
```

```bash
# Terminal 1: nginx reverse proxy
nginx -c nginx.dev.conf

# Terminal 2-4: services
uv run uvicorn shared.main:app --reload --port 8000             # estate-os
uv run uvicorn applicant_management.main:app --reload --port 8001  # intake
uv run uvicorn contract_intelligence.main:app --reload --port 8002 # contracts
```

Alternatively, Traefik itself can run locally via Docker with file-based configuration (no need for Docker provider), giving exact parity with production routing rules.

### When gRPC is still needed alongside Traefik

Traefik handles client→service routing, but **service→service calls** are a separate concern. Two scenarios:

1. **No inter-service calls needed**: if each service is fully independent (client calls go directly to the owning service via Traefik), gRPC is unnecessary. This is the simplest option.

2. **Orchestration needed**: if estate-os must aggregate data from multiple services for a single client request (e.g., a dashboard view combining properties + intake status + contract analysis), it still needs to call other services. In this case, gRPC (or internal REST) is used for these service→service calls, while Traefik handles the client-facing routing.

### Comparison: BFF + gRPC vs. Traefik gateway

| Dimension | BFF + gRPC (Option A) | Traefik gateway (Option B) |
|-----------|----------------------|---------------------------|
| **Client routing** | All traffic goes through estate-os | Traefik routes to correct service by path |
| **Service APIs** | Backend services have no public API (gRPC only) | Each service keeps its own REST API |
| **Inter-service calls** | Always via gRPC | Only when services need each other's data |
| **Auth** | Centralized in estate-os | Traefik middleware (ForwardAuth) or per-service |
| **New endpoint** | Add route in estate-os + gRPC call + proto update | Add route in owning service, update Traefik config |
| **estate-os coupling** | Knows every backend API, must proxy everything | Only knows its own domain (properties, users, orgs) |
| **Latency (client→service)** | +1 hop (client→estate-os→gRPC→backend) | Direct (client→Traefik→backend), 1 fewer hop |
| **Latency (service→service)** | Low (native gRPC/HTTP2 in VPC) | Same if gRPC used; REST adds JSON overhead |
| **Complexity** | Protobuf/gRPC toolchain, stubs, codegen | Traefik config (YAML/TOML), simpler stack |
| **Team velocity** | Every backend change requires estate-os update | Services deploy independently |
| **Infra cost** | ALB + NLBs per service | Single Traefik instance replaces ALB |
| **Local dev** | Multiple gRPC servers + REST server | nginx/Traefik + multiple REST servers |
| **Observability** | Centralized in estate-os | Traefik access logs + per-service logs |
| **Scaling** | estate-os is bottleneck (all traffic) | Traefik is stateless, trivially scalable |

### Traefik cost analysis

Traefik replaces both the ALB (~$22/month + $0.008/LCU-hour) and API Gateway (~$3.50/million requests) with a single EC2 instance:

- **t3.micro** ($7.60/month): sufficient for current traffic levels, Traefik is very lightweight
- **TLS termination**: Traefik handles this natively with Let's Encrypt auto-renewal or ACM certs
- **No per-request charges**: unlike API Gateway, Traefik has zero per-request cost
- **Estimated savings**: ~$30-50/month at current scale (grows significantly with traffic)

### Recommendation

**Option B (Traefik) is simpler and more scalable for Portolar's current stage** — services stay independent, the stack stays REST-only (no protobuf toolchain), and deployment velocity is higher. gRPC can be added later for specific service→service calls that need it, without rearchitecting the routing layer.

**Option A (BFF + gRPC) is better if** estate-os frequently needs to orchestrate calls across services for a single client request, or if the performance difference between REST and gRPC is measurable at our scale.

A **hybrid path** is also viable: start with Traefik for routing, add gRPC only for the specific inter-service calls that need it (e.g., estate-os calling applicants-intake-service for combined views). This avoids the all-or-nothing choice.

## Consequences

### Pros

- **Single entry point**: clients talk to one API (estate-os), no API Gateway needed for backend services — significant cost savings
- **Lowest latency**: native gRPC over HTTP/2 in the same VPC, NLB adds ~μs overhead
- **Type safety**: protobuf contracts prevent schema drift between services
- **Multiplexing**: one TCP connection carries many concurrent RPCs — efficient for BFF fan-out
- **Clear boundaries**: gRPC enforces explicit service contracts vs. ad-hoc REST calls
- **Fits hexagonal architecture**: gRPC clients/servers are just adapters — domain layer is unaffected

### Cons

- **EC2 for backend services**: applicants-intake-service moves from full Lambda to hybrid EC2+Lambda (same pattern as estate-os in ADR-002), adding infrastructure to manage
- **Protobuf learning curve**: team must learn proto3 syntax, Buf tooling, and gRPC patterns
- **Proto management overhead**: `.proto` changes require regenerating stubs and updating both sides
- **Debugging complexity**: binary protocol is harder to inspect than JSON — need gRPC reflection or tools like `grpcurl`
- **Additional EC2 costs**: backend services need always-on EC2 instances for gRPC servers (mitigated by small instance sizes and offset by API Gateway savings)

### Neutral

- SQS-based async flows are unaffected
- Lambda workers continue unchanged
- Domain layer and use cases require no modifications
- Same Docker image / ECR pattern, different entrypoints (API, gRPC server, Lambda worker)
