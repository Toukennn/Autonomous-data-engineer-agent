# Autonomous Data Engineer Agent

[![CI](https://github.com/Toukennn/Autonomous-data-engineer-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/Toukennn/Autonomous-data-engineer-agent/actions/workflows/ci.yml)

A safety-oriented **agentic data engineering platform** that turns natural-language intent into governed ETL pipelines and read-only warehouse analytics across external APIs, PostgreSQL, dbt, and SQLGlot.

> **LLMs decide what should happen. Deterministic code decides how it is allowed to happen.**

The project combines LangGraph-based specialist agents with deterministic execution boundaries for networking, persistence, schema evolution, data quality, dbt model generation, SQL validation, authentication, concurrency, and runtime state.

## Live demo

**Interactive portfolio demo:**  
https://autonomous-data-engineer-agent-production.up.railway.app/

Also available:

- **Swagger / OpenAPI:** https://autonomous-data-engineer-agent-production.up.railway.app/docs
- **Liveness:** https://autonomous-data-engineer-agent-production.up.railway.app/health
- **Readiness:** https://autonomous-data-engineer-agent-production.up.railway.app/ready
- **General agent API:** `POST /query`

The deployment runs on Railway with a private managed PostgreSQL service and persistent application storage.

### Demo experience

The browser demo exposes two explicit specialist workflows:

```text
Ask a question
    ↓
SQL Analyst
    ↓
governed catalog
    ↓
generated PostgreSQL
    ↓
SQLGlot + relation allowlist
    ↓
read-only PostgreSQL
    ↓
result table + natural-language answer
```

and:

```text
Ingest an API
    ↓
public JSON API
    ↓
deterministic record discovery
    ↓
Bronze
    ↓
PostgreSQL
    ↓
dbt Silver
    ↓
dbt Gold
    ↓
governed analytics catalog
    ↓
available to SQL Analyst
```

The demo is designed to show the engineering work rather than hide it behind a chat interface:

- **generated SQL is visible** before the query result
- **execution stages update while the run is progressing**
- **guardrails are surfaced explicitly** when SQL safety, schema evolution, or data-quality checks block work
- **Ask** and **Ingest** call the corresponding specialist directly, avoiding an unnecessary routing LLM call
- a successful ingestion exposes the resulting Gold relation so the visitor can immediately query it
- public JSON APIs are inspected deterministically to locate their record collection before ETL orchestration
- the demo key is stored only in browser `sessionStorage`, never `localStorage`
- portfolio demo authentication uses a dedicated `DEMO_API_KEY`, separate from the service-level `SERVICE_API_KEY`
- **keyless recorded runs from real cloud executions** let visitors inspect representative results even without live demo credentials

The live ingestion form intentionally stays small: the visitor supplies a public JSON API URL and describes, in natural language, what the Gold mart should provide.

---

## What the platform demonstrates

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
LLM-generated analytical SQL
    ↓
SQLGlot validation
    ↓
read-only PostgreSQL
    ↓
bounded result + answer
```

Key engineering capabilities include:

- resilient API ingestion with retries, pagination limits, response limits, redirect controls, and SSRF/public-destination validation
- persistent watermark-based incremental ingestion
- deterministic schema-evolution policy
- Medallion Bronze / Silver / Gold architecture
- business-key-aware Bronze merge and PostgreSQL upsert behavior
- generated dbt Silver and Gold models from typed transformation plans
- data-quality contracts and dbt tests
- lineage and durable execution records
- governed natural-language SQL analytics
- SQLGlot AST validation and physical-relation allowlisting
- read-only PostgreSQL execution with statement and row limits
- request/run correlation IDs and safe structured logs
- FastAPI authentication, concurrency control, and execution timeouts
- non-root Docker execution
- Docker Compose reproduction
- GitHub Actions CI
- Railway deployment with persistent storage and managed PostgreSQL
- restart persistence validated in the deployed environment

---

## Architecture

The application has three main agents:

- **Data Engineer Agent** — general top-level router used by `/query`
- **ETL Analyst Agent** — API ingestion and governed Medallion/dbt orchestration
- **SQL Analyst Agent** — governed analytical SQL generation and execution

The interactive portfolio demo calls the ETL and SQL specialists directly because the user explicitly selects the mode.

```text
                          FastAPI
                 ┌──────────┴──────────┐
                 │                     │
             /query                 /demo/*
                 │                     │
        Data Engineer Router      explicit mode
          ┌──────┴──────┐         ┌────┴────┐
          ▼             ▼         ▼         ▼
     ETL Analyst    SQL Analyst   ETL       SQL
          │             │
          ▼             ▼
    API → Bronze    governed catalog
          │             │
          ▼             ▼
     PostgreSQL      SQL generation
          │             │
          ▼             ▼
      dbt Silver     SQLGlot
          │             │
          ▼             ▼
       dbt Gold     read-only DB
          │             │
          └──────┬──────┘
                 ▼
       lineage / run records
```

For the detailed system design, see:

- [Architecture](docs/architecture.md)
- [Safety Model](docs/safety-model.md)
- [Testing & Operations](docs/testing-and-operations.md)
- [Running & Configuration](docs/running-and-configuration.md)
- [Limitations & Roadmap](docs/limitations-and-roadmap.md)

A full documentation index is available at [docs/README.md](docs/README.md).

---

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
| [2R](docs/phases/phase-2r-final-validation-release.md) | Final validation + release polish | v1 milestone |

---

## Safety model

LLM output is treated as **untrusted input**.

The model may decide supported high-level intent and produce typed plans, but deterministic code owns the physical execution boundary.

Examples:

```text
LLM transformation plan
        ↓
Pydantic validation
        ↓
deterministic Python / dbt compiler
```

```text
LLM-generated SQL
        ↓
SQLGlot AST validation
        ↓
governed relation allowlist
        ↓
read-only database execution
```

The model does not receive unrestricted Python execution, shell access, filesystem access, arbitrary PostgreSQL writes, arbitrary dbt commands, unrestricted Jinja, or direct control over checkpoint and merge semantics.

---

## Quick start

### Docker Compose

```bash
cp .env.example .env
docker compose up -d --build
```

Verify:

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/ready
```

### Local Python

```bash
uv sync --locked --python 3.12
uv run uvicorn app.api:app --host 0.0.0.0 --port 8000
```

Open the local demo:

```text
http://127.0.0.1:8000/
```

Full configuration details are in [docs/running-and-configuration.md](docs/running-and-configuration.md).

---

## Authentication

The application separates three credential concerns:

```text
SERVICE_API_KEY
    → protects the general /query service API

DEMO_API_KEY
    → protects live /demo execution endpoints

API_AUTH_TOKEN
    → optional outbound authentication for external APIs
```

The portfolio page never embeds either inbound key in HTML or JavaScript.

For the interactive demo, the entered key is kept only in `sessionStorage`, so it survives a refresh in the same browser session but is not persisted through `localStorage`.

Never commit real credentials to the repository.

---

## Testing

Run the development validation locally with:

```bash
uv run ruff check .
uv run pytest -v
```

GitHub Actions additionally validates packaging and Docker behavior, including container startup, health checks, non-root execution, and runtime storage.

The current `main` branch is passing CI.

---

## Tech stack

**Python 3.12 · LangGraph · LangChain · FastAPI · Pydantic · Pandas · PostgreSQL · dbt-postgres · SQLGlot · Docker · Railway · uv · pytest · Ruff · GitHub Actions**

---

## v1 scope

Version 1 is intentionally a **single-instance, single-active-run** system.

The following are deliberately deferred rather than presented as production-complete features:

- distributed task queues
- horizontal multi-replica coordination
- advanced CDC deletion/tombstone semantics
- SCD Type 2 modeling
- heavy centralized metrics/tracing infrastructure
- broader enterprise security and orchestration features

The current portfolio version focuses on one coherent, deployed end-to-end system with explicit safety boundaries and reproducible execution.

See [Limitations & Roadmap](docs/limitations-and-roadmap.md).

---

## License

See the repository license for usage terms.
