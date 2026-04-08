# TLDR: SQS Worker Architecture — Why SQS, How It Works, and Where It Falls Short

## Context

estate-os-service runs two bounded contexts that process async work via SQS workers:

| Context | Queues | What it does |
|---------|--------|--------------|
| **contract_intelligence** | `contract-ingestion`, `contract-analysis`, `contract-ingestion-dlq`, `contract-analysis-dlq` | OCR + AI analysis of rental contracts |
| **screening** | `applicant-extraction`, `applicant-screening` | Document extraction + AI screening of applicants |

Each worker is a standalone Python process (`asyncio.run`) that long-polls SQS, processes one message at a time, and deletes it. The contract_intelligence worker is more mature — it has visibility timeout heartbeats, per-message error handling, DLQ support, and processing duration logging. The screening worker lacks all of these.

### Current message flow

```
                  ┌─────────────────────────────────────────────────────┐
                  │              contract_intelligence                  │
                  │                                                     │
  API upload      │   ┌──────────┐    SQS     ┌──────────┐    SQS     │
  ──────────────►─┼──►│ ingestion│───────────►│ analysis │             │
                  │   │  worker  │            │  worker  │             │
                  │   └────┬─────┘            └──────────┘             │
                  │        │ on failure (maxReceiveCount exceeded)      │
                  │        ▼                                           │
                  │   ┌──────────┐                                     │
                  │   │   DLQ    │  marks document as FAILED           │
                  │   │  worker  │                                     │
                  │   └──────────┘                                     │
                  └─────────────────────────────────────────────────────┘

                  ┌─────────────────────────────────────────────────────┐
                  │                    screening                        │
                  │                                                     │
  Form submit     │   ┌──────────┐    SQS     ┌──────────┐            │
  ──────────────►─┼──►│extraction│───────────►│screening │            │
                  │   │  worker  │            │  worker  │            │
                  │   └──────────┘            └──────────┘            │
                  └─────────────────────────────────────────────────────┘
```

Each worker process handles exactly one queue. A single pod runs a single worker process.

## Why SQS (and not Kafka or RabbitMQ)

We have **<10 DAU**. We process a handful of contract analyses and applicant screenings per day. The queue system exists for **decoupling and reliability**, not throughput.

### Comparison at our scale

```
                        SQS                 RabbitMQ              Kafka
                   ─────────────       ─────────────────     ──────────────────
 Ops overhead      Zero (managed)      Medium (deploy,       High (cluster,
                                       monitor Erlang)       partitions, ZK/KRaft)

 Cost at           ~$0/month           ~$15-50/mo minimum    ~$170/mo minimum
 our volume        (1M free req/mo)    (always-on instance)  (MSK) or similar
                                                             for self-hosted

 Scale to zero     Yes (pay per req)   No (broker runs)      No (broker runs)

 Delivery          At-least-once       At-least-once         At-least-once
                   (FIFO: exactly-     (manual ack)          (configurable)
                   once, 300 TPS cap)

 Message replay    No                  No (without plugins)  Yes (log retention)

 Routing           Simple queue +      Exchanges: direct,    Topic + partitions,
                   optional SNS        topic, fanout,        consumer groups
                   fan-out             headers

 Client library    aioboto3 (we        aio-pika              aiokafka
                   already use it)

 When to use it    Simple async jobs,  Complex routing,      Stream processing,
                   decoupling, low     multi-consumer        event sourcing,
                   volume              patterns              high throughput
```

### Why not Kafka

Kafka's value is **ordered log retention** and **stream processing**. We don't replay events. We don't need ordered delivery. We don't do stream joins or windowed aggregations. Kafka would cost us $170+/mo to process ~50 messages/day, plus ongoing cluster management. It solves problems we don't have.

### Why not RabbitMQ

RabbitMQ's value is **sophisticated routing** (topic exchanges, headers-based routing, priority queues). Our routing is trivial: one queue per job type. RabbitMQ would add an always-on broker we need to monitor, patch, and scale. CloudAMQP has a free tier but it's limited and adds a vendor dependency we don't need.

### Why SQS wins here

- **Zero infrastructure** — no broker to deploy, monitor, or patch
- **Zero idle cost** — we pay per API call, and the free tier covers our volume entirely
- **We already use AWS** — aioboto3 session is already wired for S3, adding SQS is one import
- **Visibility timeout + DLQ** — gives us retry and dead-letter semantics out of the box
- **Good enough guarantees** — at-least-once delivery with idempotent processors is sufficient

**When we'd reconsider**: If we needed message replay (audit trail), complex fan-out routing, or sustained >10k msg/s throughput. None of these are on our roadmap.

## Worker reliability scorecard

We scored the **screening** worker (the weaker one) on five metrics:

| # | Metric | Score | Issue |
|---|--------|-------|-------|
| 1 | **Fault tolerance** | 4/10 | No per-message error handling. A crash in `process_event` leaves the message un-deleted (ok), but `_poll` or `json.loads` errors swallow the context. No DLQ awareness. |
| 2 | **Throughput** | 3/10 | `MaxNumberOfMessages=1`, sequential processing, new SQS client per poll and per delete. Max ~3 msg/min (limited by 20s long-poll). |
| 3 | **Observability** | 4/10 | Logs start/processed/error but no duration, no message attributes, no metrics. |
| 4 | **Graceful shutdown** | 6/10 | Flag-based shutdown works, but no heartbeat means long tasks risk double-processing via visibility timeout expiry. |
| 5 | **Resource efficiency** | 4/10 | SQS client created and destroyed on every `_poll()` and `_delete_message()`. TLS handshake + credential resolution on each call. |

**Contract intelligence** scores better (heartbeat, per-message try/except, duration logging, DLQ worker) but still shares the client-per-call and single-message-per-poll issues.

## Scaling strategy

### The wrong approach: multi-process pool inside a pod

Celery's prefork model spawns N OS processes per machine to parallelize synchronous workers. We don't need this — our workers are already async. Spawning multiple processes would add:
- Memory overhead (each process loads the full Python runtime + dependencies)
- IPC complexity for health checks and shutdown coordination
- No benefit — `asyncio` already multiplexes I/O within one process

### The right approach: async concurrency per pod + horizontal scaling

```
                    Kubernetes Cluster
   ┌─────────────────────────────────────────────────┐
   │                                                  │
   │  ┌─────────── Pod 1 ──────────────┐             │
   │  │  1 Python process              │             │
   │  │  ┌──────┐ ┌──────┐ ┌──────┐   │             │
   │  │  │task 1│ │task 2│ │task 3│   │  ◄── asyncio │
   │  │  └──────┘ └──────┘ └──────┘   │      tasks   │
   │  │  Semaphore(5) bounds max       │             │
   │  └────────────────────────────────┘             │
   │                                                  │
   │  ┌─────────── Pod 2 ──────────────┐             │
   │  │  1 Python process              │  ◄── HPA    │
   │  │  ┌──────┐ ┌──────┐ ┌──────┐   │     scales  │
   │  │  │task 1│ │task 2│ │task 3│   │     these   │
   │  │  └──────┘ └──────┘ └──────┘   │             │
   │  └────────────────────────────────┘             │
   │                                                  │
   │  KEDA ScaledObject                               │
   │  ┌──────────────────────────────┐               │
   │  │ polls SQS queue depth        │               │
   │  │ ApproximateMessagesVisible   │               │
   │  │ scales 0 ↔ maxReplicaCount  │               │
   │  └──────────────────────────────┘               │
   └─────────────────────────────────────────────────┘

        ▲
        │ SQS handles distribution server-side
        │ No consumer groups, no partitions
        │ Every ReceiveMessage competes for same pool
        ▼
   ┌──────────┐
   │   SQS    │
   │  Queue   │
   └──────────┘
```

**Why this works with SQS**: SQS has no consumer affinity or partitions. It doesn't matter whether 10 msg/s come from 10 pods or 1 pod with 10 coroutines. SQS distributes messages server-side via `ReceiveMessage` calls.

**Why async, not threads**: Our workers are I/O-bound (waiting on Reducto API, LLM calls, S3, Supabase). `asyncio` handles thousands of concurrent I/O waits in a single thread. Threads would add GIL contention and context-switch overhead for zero benefit.

### KEDA autoscaling

For our low-volume scenario, KEDA with scale-to-zero is ideal:

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: contract-ingestion-scaler
spec:
  scaleTargetRef:
    name: contract-ingestion-worker
  minReplicaCount: 0          # zero pods when queue is empty
  maxReplicaCount: 3          # cap — we don't need more
  pollingInterval: 30         # check queue every 30s
  cooldownPeriod: 300         # wait 5min before scaling to zero
  triggers:
    - type: aws-sqs-queue
      metadata:
        queueURL: <queue-url>
        queueLength: "5"      # target 5 messages per pod
        awsRegion: eu-west-1
        scaleOnInFlight: "true"
```

Workers consume zero resources when idle and spin up within ~30s when messages arrive.

## Concurrency pattern: poller + worker pool

The current worker polls and processes in the same loop. A better pattern separates polling from processing:

```
  ┌─────────────┐         ┌──────────────────────┐
  │   Poller    │         │   Worker Pool         │
  │             │  put()  │                       │
  │ SQS.receive ├────────►│ asyncio.Queue(max=10) │
  │ (batch=10)  │         │                       │
  │             │         │  worker_1 ──► process  │
  │ Backs off   │         │  worker_2 ──► process  │
  │ when queue  │         │  worker_3 ──► process  │
  │ is full     │         │  ...                   │
  └─────────────┘         └──────────────────────┘
                                    │
                          Backpressure: poller blocks
                          when internal queue is full
```

- **Poller**: Fetches up to 10 messages per call, enqueues them in an `asyncio.Queue(maxsize=N)`
- **Workers**: N coroutines dequeue and process. Natural backpressure — when all workers are busy, the internal queue fills up, and the poller blocks on `queue.put()`
- **Bounded concurrency**: N is the semaphore — set it based on how many concurrent AI API calls are reasonable (5-10 for our use case)

## Key takeaway

SQS is the right choice at our scale. The worker architecture needs reliability improvements (see ADR-006) but the queue technology is not the bottleneck — the worker implementation is.
