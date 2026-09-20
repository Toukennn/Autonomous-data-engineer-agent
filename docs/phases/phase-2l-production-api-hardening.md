# Phase 2L — Production API Hardening ✅

## Goal

Harden the public HTTP boundary before cloud deployment.

## Implemented

```text
2L.1  Liveness vs readiness separation      ✅
2L.2  Explicit busy/concurrency handling     ✅
2L.3  Bounded request execution wait         ✅
2L.4  Inbound API-key authentication         ✅
2L.5  Request/run correlation IDs            ✅
2L.6  Safe structured HTTP observability     ✅
```

## Liveness vs readiness

`GET /health` is intentionally cheap and does not contact PostgreSQL, the LLM, or external APIs.

`GET /ready` verifies:

```text
runtime storage writable?
        +
PostgreSQL reachable?
        ↓
ready
```

## Concurrency

The current runtime allows one agent execution at a time.

```text
execution slot free
      ↓
request starts

execution slot occupied
      ↓
503 Service Unavailable
Retry-After: 5
```

## HTTP wait timeout

```text
AGENT_REQUEST_TIMEOUT_SECONDS=600
```

The HTTP deadline does not unsafely terminate an arbitrary Python thread. If the underlying worker is still running, the execution lock remains held until it really finishes.

## Authentication

Protected work requires:

```text
X-API-Key: <SERVICE_API_KEY>
```

Inbound service authentication is separate from outbound external-API authentication.

## Correlation IDs

Every HTTP request receives:

```text
X-Request-ID
```

An actual agent execution additionally receives:

```text
X-Run-ID
```

## Safe structured logs

Structured JSON events are emitted to stdout. Sensitive request bodies, prompts, LLM responses, API keys, database credentials, arbitrary headers, and raw exception text are deliberately excluded.
