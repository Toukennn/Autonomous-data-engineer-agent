# Autonomous Data Engineer Agent

[![CI](https://github.com/Toukennn/Autonomous-data-engineer-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/Toukennn/Autonomous-data-engineer-agent/actions/workflows/ci.yml)

A safety-oriented, production-minded **agentic data engineering platform** for reliable API ingestion, incremental processing, PostgreSQL warehousing, dbt transformations, data-quality governance, lineage, observability, and governed natural-language SQL analytics.

> **LLMs decide what should happen. Deterministic code decides how it is allowed to happen.**

The project uses **LangGraph** to route requests between specialized ETL and SQL agents while deterministic application code controls sensitive execution boundaries such as filesystem access, checkpoints, PostgreSQL writes, dbt execution, SQL validation, authentication, concurrency, and runtime persistence.

## Live deployment

- **Swagger / OpenAPI:** https://autonomous-data-engineer-agent-production.up.railway.app/docs
- **Liveness:** https://autonomous-data-engineer-agent-production.up.railway.app/health
- **Readiness:** https://autonomous-data-engineer-agent-production.up.railway.app/ready
- **Agent endpoint:** `POST https://autonomous-data-engineer-agent-production.up.railway.app/query`

`/health` and `/ready` are public infrastructure endpoints. `/query` is protected with `X-API-Key`. The deployed PostgreSQL service remains private.

## What the project demonstrates

```text
External API
    ↓
resilient deterministic ingestion
    ↓
persistent Bronze + incremental state
    ↓
PostgreSQL Bronze
    ↓
dbt Silver
    ↓
dbt Gold
    ↓
governed analytics catalog
    ↓
LLM-generated SQL
    ↓
SQLGlot validation
    ↓
read-only PostgreSQL
    ↓
natural-language answer
```

The platform also includes schema evolution, business-key-aware upserts, quality contracts, lineage, execution records, FastAPI, Docker, CI, cloud deployment, persistent runtime storage, request/run correlation IDs, and restart persistence.

## Architecture

The application contains three primary agents:

- **Data Engineer Agent** — top-level router
- **ETL Analyst Agent** — governed ingestion and transformation orchestration
- **SQL Analyst Agent** — governed natural-language analytics over approved Silver/Gold relations

For the complete architecture and execution boundaries, see [Architecture](docs/architecture.md) and [Safety Model](docs/safety-model.md).

## Development phases

| Phase | Scope | Status |
|---|---|---|
| [2A](docs/phases/phase-2a-reliable-api-ingestion.md) | Reliable API ingestion | ✅ |
| [2B](docs/phases/phase-2b-persistent-incremental-ingestion.md) | Persistent incremental ingestion | ✅ |
| [2C](docs/phases/phase-2c-schema-evolution.md) | Schema evolution | ✅ |
| [2D](docs/phases/phase-2d-medallion-lineage.md) | Medallion architecture + lineage | ✅ |
| [2E](docs/phases/phase-2e-runtime-reliability-ci.md) | Agent runtime reliability + CI | ✅ |
| [2F](docs/phases/phase-2f-data-quality-contracts.md) | Data quality + contracts | ✅ |
| [2G](docs/phases/phase-2g-postgresql-warehouse-bridge.md) | PostgreSQL warehouse bridge | ✅ |
| [2H](docs/phases/phase-2h-dbt-integration.md) | dbt integration | ✅ |
| [2I](docs/phases/phase-2i-governed-warehouse-analytics.md) | Governed warehouse analytics | ✅ |
| [2J](docs/phases/phase-2j-incremental-warehouse-processing.md) | Incremental warehouse processing | ✅ |
| [2K](docs/phases/phase-2k-containerized-runtime.md) | Containerized runtime & deployment foundation | ✅ |
| [2L](docs/phases/phase-2l-production-api-hardening.md) | Production API hardening | ✅ |
| [2M](docs/phases/phase-2m-real-cloud-deployment.md) | Railway cloud deployment + remote E2E | ✅ |
| [2R](docs/phases/phase-2r-final-validation-release.md) | Final validation + release polish | Final v1 milestone |

A documentation index is available at [docs/README.md](docs/README.md).

## Quick start

### Docker Compose

```bash
cp .env.example .env
docker compose up -d --build
```

Then verify:

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/ready
```

### Local Python

```bash
uv sync --locked --python 3.12
uv run uvicorn app.api:app --host 0.0.0.0 --port 8000
```

See [Running & Configuration](docs/running-and-configuration.md) for the full setup.

## Testing

```bash
uv run ruff check .
uv run pytest -v
```

GitHub Actions additionally validates packaging, Docker build/boot, container health, non-root runtime behavior, and resolved runtime storage.

See [Testing & Operations](docs/testing-and-operations.md).

## Tech stack

**Python 3.12 · LangGraph · LangChain · FastAPI · Pydantic · Pandas · PostgreSQL · dbt-postgres · SQLGlot · Docker · Railway · uv · pytest · Ruff · GitHub Actions**

## v1 scope

Version 1 is intentionally a **single-instance, single-active-run** deployment. Distributed workers, multi-replica coordination, advanced CDC/deletion semantics, SCD Type 2, and heavy centralized metrics/tracing are deferred rather than hidden behind unsupported assumptions.

See [Limitations & Roadmap](docs/limitations-and-roadmap.md).

## License

See the repository license for usage terms.
