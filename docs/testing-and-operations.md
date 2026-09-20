# Testing & Operations

## Development checks

```bash
uv run ruff check .
uv run pytest -v
```

CI additionally checks package build and Docker runtime behavior.

## Test coverage

The test suite covers, among other areas:

- API retry and pagination behavior
- SSRF/public-network validation
- schema evolution
- incremental state
- business-key semantics
- quality contracts
- PostgreSQL helpers
- dbt sources/models/tests/artifacts
- incremental dbt decisions
- lineage
- ETL-agent orchestration
- SQL-agent governance
- SQL safety
- FastAPI boundary behavior
- health/readiness separation
- sanitized readiness errors
- API authentication
- busy/concurrency behavior
- execution timeout semantics
- lock release after success/failure
- request/run correlation IDs
- safe structured HTTP observability

## End-to-end scripts

```text
scripts/phase_2i_e2e.py
scripts/phase_2j_e2e.py
scripts/phase_2k_e2e.py
```

Phase 2K verifies the containerized path:

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

The Railway deployment has also been validated manually through the public HTTPS boundary.

## CI

GitHub Actions runs on pushes and pull requests to `main`.

```text
Ruff
  ↓
pytest
  ↓
uv build
  ↓
Docker build
  ↓
container boot
  ↓
Docker health
  ↓
/health smoke test
  ↓
non-root runtime check
  ↓
resolved DATA_ROOT check
```

Real provider/database secrets are not embedded in CI.

## Observability

### HTTP-level logs

Structured JSON events are emitted to stdout, including:

```text
http_request.completed
agent_run.started
agent_run.completed
agent_run.failed
agent_run.busy
agent_run.http_timeout
```

### Correlation

```text
X-Request-ID
X-Run-ID
```

allow responses to be matched to runtime events.

### Durable execution records

Agent-level run records are persisted under:

```text
data/_runs/
```

ETL and SQL execution records contain bounded operational metadata such as status, duration, validated relations, and result counts where appropriate.

### dbt evidence

dbt artifacts and deterministic metadata provide model-execution evidence without exposing secrets through the public API.

A separate Prometheus/Grafana/OpenTelemetry stack is intentionally not required for portfolio v1.

## HTTP error semantics

| Situation | HTTP behavior |
|---|---|
| API process alive | `GET /health` → `200` |
| Storage + PostgreSQL ready | `GET /ready` → `200` |
| Dependency unavailable | `GET /ready` → `503` |
| Missing/wrong service API key | `POST /query` → `401` |
| Another agent run is active | `POST /query` → `503` + `Retry-After` |
| HTTP execution deadline reached | `POST /query` → `504` |
| Internal agent execution error | `POST /query` → sanitized `500` |
| Invalid request body | FastAPI validation → `422` |
