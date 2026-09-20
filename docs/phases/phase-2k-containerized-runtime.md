# Phase 2K — Containerized Runtime & Deployment Foundation ✅

## Goal

Move the project from a local Python application into a reproducible containerized service boundary.

## Implemented

```text
2K.1  FastAPI HTTP runtime                    ✅
2K.2  API boundary tests                      ✅
2K.3  Production-oriented Docker image        ✅
2K.4  Non-root container execution            ✅
2K.5  Docker liveness health check             ✅
2K.6  PostgreSQL + application Compose stack   ✅
2K.7  Persistent Docker volumes               ✅
2K.8  Full containerized E2E                   ✅
2K.9  Docker build/smoke gate in CI            ✅
```

## FastAPI boundary

Primary endpoints:

| Endpoint | Purpose | Authentication |
|---|---|---|
| `GET /health` | process liveness | public |
| `GET /ready` | dependency readiness | public |
| `POST /query` | governed agent execution | `X-API-Key` |

LLM construction is lazy so infrastructure probes do not need to contact the model provider.

## Docker image

The image:

- uses Python 3.12 slim
- installs dependencies with `uv`
- runs the application as UID/GID `10001`
- exposes port `8000`
- runs one Uvicorn worker
- stores durable runtime state under `/app/runtime`
- provides a writable runtime home under `/app/runtime/home`

One worker is deliberate because current locking and generated runtime state are process-local.

## Health check

Docker checks:

```text
GET /health
```

rather than `/ready`, keeping process liveness separate from PostgreSQL dependency availability.

## Containerized E2E

`scripts/phase_2k_e2e.py` validates:

```text
HTTP
  ↓
Agent
  ↓
External API
  ↓
Bronze
  ↓
PostgreSQL
  ↓
dbt Silver
  ↓
dbt Gold
  ↓
governed SQL
```

## CI gate

The Docker CI path validates image build, container boot, health, non-root execution, and runtime-storage resolution.
