# Autonomous Data Engineer Agent

[![CI](https://github.com/Toukennn/Autonomous-data-engineer-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/Toukennn/Autonomous-data-engineer-agent/actions/workflows/ci.yml)

A safety-oriented, production-minded **agentic data engineering platform** for reliable API ingestion, incremental processing, PostgreSQL warehousing, dbt transformations, data-quality governance, lineage, observability, and governed natural-language SQL analytics.

The system uses **LangGraph** to route requests to specialized ETL and SQL agents while keeping sensitive operations under deterministic application control.

> **LLMs decide what should happen. Deterministic code decides how it is allowed to happen.**

The LLM may choose a supported workflow and produce typed plans, but it does **not** receive arbitrary Python execution, unrestricted filesystem access, unrestricted database access, unrestricted dbt execution, direct checkpoint control, or control over physical warehouse merge semantics.

---

## Live Deployment

The portfolio deployment is running on **Railway** with a private managed PostgreSQL service and persistent application storage.

- **Swagger / OpenAPI:** https://autonomous-data-engineer-agent-production.up.railway.app/docs
- **Liveness:** https://autonomous-data-engineer-agent-production.up.railway.app/health
- **Readiness:** https://autonomous-data-engineer-agent-production.up.railway.app/ready
- **Agent endpoint:** `POST https://autonomous-data-engineer-agent-production.up.railway.app/query`

`/health` and `/ready` are public infrastructure endpoints. `/query` is protected by an `X-API-Key` header.

The deployed PostgreSQL service is intentionally **not exposed through a public domain**.

### Deployed request example

```bash
curl \
  -X POST \
  https://autonomous-data-engineer-agent-production.up.railway.app/query \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $SERVICE_API_KEY" \
  -d '{
    "message": "How many rows are in the Gold dataset dbt_dev_gold.mart_<dataset>?"
  }'
```

Successful agent executions include separate correlation headers:

```text
X-Request-ID: <uuid4>
X-Run-ID: <uuid4>
```

Never commit or publish the real `SERVICE_API_KEY`.

---

## Why this project exists

Many agentic data systems give the model too much authority over execution. This project explores a different design:

```text
Natural-language intent
        ↓
      LLM
  decides WHAT
        ↓
typed / validated plan
        ↓
deterministic application code
  decides HOW
        ↓
bounded execution
```

The result combines agentic orchestration with core data-engineering concerns:

- resilient API ingestion
- persistent incremental state
- schema evolution
- Medallion architecture
- business-key-aware merge/upsert
- PostgreSQL warehousing
- dynamically generated dbt models
- dbt tests and quality contracts
- governed SQL generation
- AST-based SQL safety
- lineage
- execution observability
- containerization
- CI
- cloud deployment
- API authentication
- liveness/readiness separation
- bounded concurrency and request time
- request/run correlation IDs
- structured safe application logs

---

# Cloud Architecture

The production portfolio deployment runs as a single Railway application service backed by private PostgreSQL and one persistent application volume.

```text
                            Internet
                               │
                               │ HTTPS
                               ▼
                        Railway Edge
                               │
                               ▼
                        FastAPI Service
                ┌──────────────┼──────────────┐
                ▼              ▼              ▼
            /health         /ready          /query
            public          public      X-API-Key protected
                │              │              │
                │              │              ├── request ID
                │              │              ├── run ID
                │              │              ├── single-run guard
                │              │              └── HTTP timeout
                │              │
                │              ├── persistent runtime storage
                │              └── private Railway PostgreSQL
                │
                └── process liveness
                                               │
                                               ▼
                                    Data Engineer Router
                                    ┌──────────┴──────────┐
                                    ▼                     ▼
                               ETL Analyst            SQL Analyst
                                    │                     │
                                    ▼                     ▼
                              External API          Governed catalog
                                    │                     │
                                    ▼                     ▼
                           Durable Bronze FS        SQL generation
                                    │                     │
                                    ▼                     ▼
                           PostgreSQL Bronze        SQLGlot AST
                                    │                     │
                                    ▼                     ▼
                                dbt Silver          allowlist checks
                                    │                     │
                                    ▼                     ▼
                                dbt Gold       read-only PostgreSQL
                                    │                     │
                                    └──────────┬──────────┘
                                               ▼
                                    lineage / observability
```

The deployed application keeps durable runtime state under one Railway volume:

```text
/app/runtime
├── data
│   ├── bronze
│   ├── silver
│   ├── gold
│   ├── _state
│   ├── _lineage
│   └── _runs
├── dbt
│   ├── generated_metadata
│   └── models
└── home
```

Inside the image:

```text
/app/data  → /app/runtime/data
/app/dbt   → /app/runtime/dbt
HOME       → /app/runtime/home
```

The writable runtime home is required so the non-root API/dbt process can operate correctly in the cloud environment.

---

# Verified Cloud End-to-End Demo

The deployed system has been tested through the **real public HTTPS boundary**, not only inside Docker or CI.

A representative cloud validation used:

```text
https://randomuser.me/api/?results=5
```

with the record collection under:

```text
results
```

The requested pipeline was:

```text
Random User API
      ↓
5 source records
      ↓
Durable Bronze filesystem
      ↓
PostgreSQL Bronze
      ↓
dbt Silver
      ↓
dbt Gold
      ↓
Gold schema:
gender
email
phone
      ↓
Governed SQL Analyst
```

The deployment successfully verified:

- authenticated `POST /query` over public HTTPS
- `200` response with distinct `X-Request-ID` and `X-Run-ID`
- external API extraction
- durable Bronze persistence
- PostgreSQL Bronze synchronization
- dbt Silver execution
- dbt Gold execution
- a Gold relation containing exactly `gender`, `email`, and `phone`
- exactly **5 Gold rows**
- governed SQL validation
- read-only SQL execution
- natural-language row-count analytics
- retrieval of actual Gold values
- persisted SQL execution records
- successful application restart followed by continued access to the same warehouse data

That validates the deployed path:

```text
HTTPS
  ↓
FastAPI
  ↓
LangGraph Router
  ↓
ETL Agent
  ↓
External API
  ↓
Persistent Bronze
  ↓
Private PostgreSQL
  ↓
dbt Silver
  ↓
dbt Gold
  ↓
Governed Catalog
  ↓
SQL Agent
  ↓
SQLGlot Validation
  ↓
Read-Only PostgreSQL
  ↓
HTTPS Response
```

---

# Core Safety Model

The project treats all LLM output as **untrusted input**.

The model may:

- classify a request as ETL or SQL
- choose among supported tools
- create a typed transformation plan
- create a typed data-quality plan
- generate one analytical SQL query

Deterministic code controls:

- physical paths
- dataset promotion rules
- checkpoint reads/writes
- schema-change policy
- business-key enforcement
- merge/upsert behavior
- PostgreSQL schemas
- dbt project/profile locations
- model materialization
- dbt selectors
- quality enforcement
- SQL parsing and allowlisting
- SQL execution mode
- API authentication
- concurrency
- request timeouts
- error sanitization
- runtime observability metadata

The model cannot directly execute arbitrary Python, shell commands, unrestricted filesystem mutations, arbitrary write SQL, arbitrary Jinja, unrestricted dbt commands, or unrestricted database writes.

## SQL safety boundary

Natural-language analytics use a governed catalog containing only approved Silver and Gold relations.

Generated SQL must:

1. parse as exactly one PostgreSQL query
2. be read-only
3. use schema-qualified physical relations
4. reference only relations present in the governed catalog
5. avoid Bronze, `public`, `information_schema`, and `pg_catalog`
6. pass SQLGlot AST and relation-scope validation
7. execute through the read-only database path
8. respect statement timeouts and row limits

If validation fails, SQL is **not executed**.

This provides a deterministic enforcement boundary even when the model proposes an incorrect or unsupported query.

---

# Agent Architecture

The application contains three primary agents.

## Data Engineer Router

The top-level LangGraph router classifies a user request into:

```text
etl
sql
```

and delegates to the appropriate specialist.

![Data Engineer Graph](data_engineer_graph.png)

## ETL Analyst

The ETL Analyst is a bounded ReAct-style orchestrator with a deliberately small tool surface.

Current tool surface:

```text
extract_load_tool
bronze_to_silver_tool
silver_to_gold_tool
dbt_bronze_to_silver_tool
dbt_silver_to_gold_tool
configure_quality_contract_tool
```

### File-backed path

```text
External API
    ↓
Bronze
    ↓
Silver
    ↓
Gold
```

Typed `TransformPlan` objects are executed by trusted deterministic Pandas code.

### PostgreSQL + dbt path

```text
External API
    ↓
extract_load_tool
    ↓
Durable Bronze filesystem
    ↓
PostgreSQL Bronze synchronization
    ↓
typed DBTTransformPlan
    ↓
deterministic SQL compilation
    ↓
dbt Silver
    ↓
dbt quality tests
    ↓
dbt Gold
```

Dependent stages execute sequentially. A failed required stage prevents downstream stages from running.

![ETL Analyst Graph](etl_analyst_graph.png)

## SQL Analyst

The SQL Analyst exposes governed natural-language analytics over approved dbt Silver and Gold relations.

```text
natural-language question
        ↓
question curation
        ↓
governed analytics catalog snapshot
        ↓
LLM generates one PostgreSQL query
        ↓
SQLGlot AST validation
        ↓
scope-aware schema/relation allowlist
        │
        ├── reject → no execution
        │
        └── accept
                ↓
        read-only PostgreSQL
                ↓
        bounded result set
                ↓
        natural-language answer
```

The same governed catalog snapshot is used for prompt context and deterministic SQL validation.

![SQL Analyst Graph](sql_analyst_graph.png)

---

# Planner vs Executor

## File-backed transformations

The LLM receives the request plus dataset metadata and produces a validated Pydantic `TransformPlan`.

Supported operations include:

- column selection/removal
- renaming
- filtering
- duplicate removal
- sorting
- missing-value handling
- casting
- string transformations
- grouped aggregations

Trusted Python executes the plan.

## dbt transformations

Warehouse transformations use a typed `DBTTransformPlan`.

Supported logical operations include:

```text
select_columns
rename_columns
filter_rows
fill_missing
cast_columns
string_transform
groupby_aggregate
```

The planner does not write arbitrary dbt SQL or Jinja.

```text
User request
    ↓
Planner LLM
    ↓
validated DBTTransformPlan
    ↓
deterministic DBTSQLCompiler
    ↓
SQLGlot validation
    ↓
generated dbt model
```

## Data-quality planning

A typed `DataQualityContract` supports rules including:

```text
not_null
unique
accepted_values
range
row_count
```

Contracts are stored and enforced by deterministic application code.

---

# Data Platform Architecture

The warehouse-backed path is:

```text
External API
    │
    ▼
Deterministic ingestion
    │
    ▼
Durable Bronze filesystem snapshot
    │
    ├── watermark checkpoint
    ├── business-key contract
    └── dataset fingerprint
    │
    ▼
PostgreSQL bronze.<dataset>
    │
    ├── refresh_in_place
    └── merge_upsert
    │
    ▼
dbt
 ┌──┴──────────────────────────────┐
 ▼                                 ▼
Silver views                    Gold marts
                                  │
                                  ├── table fallback
                                  └── governed incremental
    │                                 │
    ├──────── dbt tests ──────────────┤
    │                                 │
    └──────── lineage / observability
                                      │
                                      ▼
                             governed analytics catalog
                                      │
                                      ▼
                                  SQL Analyst
                                      │
                                      ▼
                              SQLGlot validation
                                      │
                                      ▼
                            read-only PostgreSQL
```

---

# Development Phases

## Phase 2A — Reliable API Ingestion ✅

Implemented:

- top-level JSON arrays
- nested record paths
- controlled JSON validation
- retries and exponential backoff
- `Retry-After`
- transient `429` / `5xx` handling
- optional outbound token authentication
- configurable auth header/scheme
- response/page/record limits
- pagination-loop detection
- redirect limits
- SSRF/public-destination validation
- authenticated redirect restrictions
- normalized external API errors

Authenticated outbound requests require HTTPS.

## Phase 2B — Persistent Incremental Ingestion ✅

Watermark checkpoints are persisted under:

```text
data/_state/
```

Checkpoint state advances only after required durable writes succeed.

Retry/merge semantics support:

```text
no business key
    → exact-row deduplication

business key configured
    → incoming rows replace historical rows with the same key
```

## Phase 2C — Schema Evolution ✅

Schema transitions are decided deterministically:

```text
same schema          → ACCEPT
added columns only   → ACCEPT
removed columns      → REJECT
logical type change  → REJECT
```

Implemented:

- drift detection
- additive schema evolution
- logical dtype normalization
- schema fingerprints
- schema history
- deterministic rejection reports

## Phase 2D — Medallion Architecture + Lineage ✅

```text
data/bronze/<dataset>/
data/silver/<dataset>/
data/gold/<dataset>/
```

Deterministic lineage is persisted under:

```text
data/_lineage/lineage.json
```

## Phase 2E — Agent Runtime Reliability + CI ✅

Implemented:

- deterministic agent tests
- failure-stop behavior
- tool-call limits
- structured execution records
- GitHub Actions CI

Execution records are persisted under:

```text
data/_runs/
```

## Phase 2F — Data Quality + Contracts ✅

Quality rules are represented as typed contracts rather than free-form LLM instructions.

Contracts can be synchronized into deterministic checks and dbt tests.

## Phase 2G — PostgreSQL Warehouse Bridge ✅

Durable Bronze data can be synchronized into:

```text
bronze.<dataset>
```

Two loading modes are supported:

```text
refresh_in_place
merge_upsert
```

`merge_upsert` is selected only when a trusted business-key contract exists.

## Phase 2H — dbt Integration ✅

Implemented:

- dynamic Bronze source generation
- generated Silver models
- generated Gold marts
- bounded dbt execution
- synchronized dbt tests
- safe artifact parsing
- deterministic model metadata
- controlled selectors and project/profile paths

Generated model SQL comes from validated typed plans rather than arbitrary LLM-generated dbt code.

## Phase 2I — Governed Warehouse Analytics ✅

Implemented:

- governed analytics catalog
- Silver/Gold relation discovery
- SQL generation from catalog context
- SQLGlot AST validation
- schema/relation allowlisting
- read-only execution
- result-row limits
- SQL execution observability
- end-to-end governed analytics validation

## Phase 2J — Incremental Warehouse Processing ✅

Implemented:

```text
2J.1   Typed business-key contracts
2J.2   PostgreSQL Bronze merge/upsert
2J.3   Checkpoint ↔ Bronze consistency binding
2J.4   Governed dbt incremental materialization
2J.5   Incremental lineage and observability
2J.6A  Business-key-aware durable Bronze merge
2J.6B  Two-run incremental E2E validation
```

## Phase 2K — Containerized Runtime & Deployment Foundation ✅

Implemented:

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

The image:

- uses Python 3.12 slim
- installs with `uv`
- runs the application as UID/GID `10001`
- exposes port `8000`
- uses one Uvicorn worker
- keeps durable state under `/app/runtime`
- provides a writable runtime home under `/app/runtime/home`

## Phase 2L — Production API Hardening ✅

Implemented:

```text
2L.1  Liveness vs readiness separation      ✅
2L.2  Explicit busy/concurrency handling     ✅
2L.3  Bounded request execution wait         ✅
2L.4  Inbound API-key authentication         ✅
2L.5  Request/run correlation IDs            ✅
2L.6  Safe structured HTTP observability     ✅
```

### Liveness vs readiness

`GET /health` is intentionally cheap and does not contact PostgreSQL, the LLM, or external APIs.

`GET /ready` verifies:

```text
runtime storage writable?
        +
PostgreSQL reachable?
        ↓
ready
```

### Busy/concurrency behavior

The current runtime intentionally permits one agent execution at a time.

```text
execution slot free
      ↓
request starts

execution slot occupied
      ↓
503 Service Unavailable
Retry-After: 5
```

### HTTP execution timeout

```text
AGENT_REQUEST_TIMEOUT_SECONDS=600
```

The timeout bounds how long HTTP waits. It does not unsafely terminate an arbitrary Python worker.

### Authentication

`POST /query` requires:

```text
X-API-Key: <SERVICE_API_KEY>
```

Inbound service authentication is deliberately separate from outbound external-API authentication.

### Correlation IDs

Every request receives:

```text
X-Request-ID
```

Agent executions additionally receive:

```text
X-Run-ID
```

### Safe HTTP observability

Structured JSON events are emitted to stdout.

The logger deliberately excludes:

- request bodies
- user prompts
- LLM responses
- `X-API-Key`
- arbitrary HTTP headers
- database credentials
- raw exception messages

## Phase 2M — Real Cloud Deployment ✅

The application is now deployed on Railway with:

```text
public HTTPS application
        +
private managed PostgreSQL
        +
persistent application volume
```

Completed cloud validation includes:

```text
2M.1   Single-volume cloud persistence             ✅
2M.2   Railway project                             ✅
2M.3   Managed PostgreSQL                          ✅
2M.4   Runtime variables and secret configuration  ✅
2M.5   Persistent /app/runtime volume              ✅
2M.6   /health deployment health check             ✅
2M.7   Public HTTPS domain                         ✅
2M.8   Remote /health + /ready + auth validation   ✅
2M.9   Real remote ETL + governed SQL demo         ✅
2M.10  Restart/persistence validation              ✅
```

The deployed application survived a service restart and continued querying the previously created warehouse data.

---

# HTTP API

## Liveness

Local:

```bash
curl http://127.0.0.1:8000/health
```

Cloud:

```bash
curl https://autonomous-data-engineer-agent-production.up.railway.app/health
```

Expected:

```json
{"status":"ok"}
```

## Readiness

Local:

```bash
curl http://127.0.0.1:8000/ready
```

Cloud:

```bash
curl https://autonomous-data-engineer-agent-production.up.railway.app/ready
```

Expected when dependencies are ready:

```json
{"status":"ready"}
```

## Agent query

Local:

```bash
curl \
  -X POST \
  http://127.0.0.1:8000/query \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $SERVICE_API_KEY" \
  -d '{"message":"Build a warehouse-backed pipeline from an external API."}'
```

Cloud:

```bash
curl \
  -X POST \
  https://autonomous-data-engineer-agent-production.up.railway.app/query \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $SERVICE_API_KEY" \
  -d '{"message":"How many rows are in my Gold dataset? Use the governed warehouse analytics path."}'
```

---

# Runtime Persistence

Persistent application state lives below `DATA_ROOT`.

Local default:

```text
<project>/data
```

Docker/cloud logical path:

```text
/app/data
```

In the current image, `/app/data` resolves into:

```text
/app/runtime/data
```

Important durable areas include:

```text
data/
├── bronze/
├── silver/
├── gold/
├── _state/
├── _lineage/
└── _runs/
```

The generated dbt project/runtime state also lives under the persistent `/app/runtime` tree in the deployed container.

---

# PostgreSQL Layout

The warehouse uses controlled schemas.

Conceptually:

```text
bronze
    ↓
<dbt target>_silver
    ↓
<dbt target>_gold
```

With the default target schema:

```text
bronze
    ↓
dbt_dev_silver
    ↓
dbt_dev_gold
```

Natural-language SQL analytics are restricted to the governed analytical catalog built from approved Silver and Gold relations.

---

# Project Structure

```text
.
├── agents/
│   ├── data_engineer.py
│   ├── etl_analyst.py
│   └── sql_analyst.py
│
├── app/
│   └── api.py
│
├── config/
│   └── settings.py
│
├── dbt/
│   ├── dbt_project.yml
│   ├── profiles.yml
│   ├── generated_metadata/
│   ├── models/
│   ├── target/
│   └── tests/
│
├── models/
│   ├── data_quality.py
│   ├── schema.py
│   └── warehouse_keys.py
│
├── scripts/
│   ├── container_entrypoint.py
│   ├── phase_2i_e2e.py
│   ├── phase_2j_e2e.py
│   └── phase_2k_e2e.py
│
├── tests/
│   └── ...
│
├── utils/
│   ├── api_client.py
│   ├── business_keys.py
│   ├── data_layers.py
│   ├── data_quality.py
│   ├── data_quality_contracts.py
│   ├── database.py
│   ├── dbt_artifacts.py
│   ├── dbt_execution.py
│   ├── dbt_incremental.py
│   ├── dbt_model_metadata.py
│   ├── dbt_models.py
│   ├── dbt_quality.py
│   ├── dbt_sources.py
│   ├── dbt_sql.py
│   ├── etl_tools.py
│   ├── exceptions.py
│   ├── execution_observability.py
│   ├── http_observability.py
│   ├── incremental_state.py
│   ├── lineage.py
│   ├── llm_pick.py
│   ├── schema_evolution.py
│   ├── sql_safety.py
│   └── warehouse.py
│
├── .github/
│   └── workflows/
│       └── ci.yml
│
├── .dockerignore
├── .env.example
├── Dockerfile
├── compose.yaml
├── pyproject.toml
├── uv.lock
└── README.md
```

---

# Tech Stack

- **Python 3.12**
- **LangGraph / LangChain**
- **FastAPI**
- **Pydantic / pydantic-settings**
- **Pandas**
- **PostgreSQL**
- **dbt / dbt-postgres**
- **SQLGlot**
- **Docker / Docker Compose**
- **Railway**
- **uv**
- **pytest**
- **Ruff**
- **GitHub Actions**

---

# Installation

## Option A — Docker Compose

Docker Compose is the recommended way to reproduce the full application + PostgreSQL runtime.

Copy the example environment file:

```bash
cp .env.example .env
```

Configure at minimum:

```env
OPENAI_API_KEY=...
ANTHROPIC_API_KEY=...

DB_USER=...
DB_PASSWORD=...
DB_NAME=...

SERVICE_API_KEY=...
```

Generate a strong inbound service key:

```bash
uv run python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Then:

```bash
docker compose up -d --build
```

Check:

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/ready
```

Stop:

```bash
docker compose down
```

Remove the stack and named volumes:

```bash
docker compose down -v
```

Use `-v` carefully because it removes persisted PostgreSQL/application state.

## Option B — Local Python runtime

Install/sync dependencies:

```bash
uv sync --locked --python 3.12
```

Run the API:

```bash
uv run uvicorn app.api:app --host 0.0.0.0 --port 8000
```

PostgreSQL and the required environment configuration must be available separately.

---

# Configuration

The project uses environment-backed Pydantic settings.

Start from:

```text
.env.example
```

Important groups include:

## LLM providers

```env
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
```

## PostgreSQL

```env
DB_HOST=localhost
DB_PORT=5432
DB_USER=
DB_PASSWORD=
DB_NAME=
```

## SQL safety

```env
SQL_STATEMENT_TIMEOUT_MS=10000
SQL_MAX_ROWS=1000
```

## Outbound API ingestion

```env
HTTP_TIMEOUT_SECONDS=30
API_MAX_RESPONSE_BYTES=20000000
API_MAX_TOTAL_RESPONSE_BYTES=100000000
API_MAX_PAGES=50
API_MAX_RECORDS=100000
API_RETRY_TOTAL=4
API_RETRY_BACKOFF_SECONDS=0.5
API_USER_AGENT=autonomous-data-engineer-agent/0.1

API_AUTH_TOKEN=
API_AUTH_HEADER=Authorization
API_AUTH_SCHEME=Bearer
API_MAX_REDIRECTS=5
```

`API_AUTH_*` is for **outbound external API authentication**.

## Agent runtime safety

```env
ETL_MAX_TOOL_CALLS=8
AGENT_REQUEST_TIMEOUT_SECONDS=600
```

## dbt

```env
DBT_TARGET_SCHEMA=dbt_dev
DBT_THREADS=4
```

## Inbound service authentication

```env
SERVICE_API_KEY=replace_with_a_random_secret_at_least_32_characters
```

`SERVICE_API_KEY` protects `POST /query`.

Never commit the real `.env`.

---

# Container Persistence

The application stores durable runtime state in one volume mounted at:

```text
/app/runtime
```

Both the application data path and dbt project are routed through that persistent root.

The container entrypoint:

1. creates required runtime directories
2. copies version-controlled dbt seed/project files into the runtime dbt tree
3. preserves generated models and metadata
4. prepares volume ownership when started with elevated runtime permissions
5. drops privileges to UID/GID `10001`
6. starts Uvicorn

The image sets:

```text
HOME=/app/runtime/home
```

so dbt and other runtime tools have a writable home after the process drops privileges.

---

# Testing

For normal development:

```bash
uv run ruff check .
uv run pytest -v
```

CI additionally checks a package build and Docker runtime behavior.

Important coverage includes:

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

Phase 2K verifies the containerized API → agent → pipeline → warehouse → governed SQL path.

The Railway deployment has additionally been validated manually through the public HTTPS boundary.

---

# CI

GitHub Actions runs on pushes and pull requests to `main`.

The workflow validates:

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

---

# Observability

The project already provides lightweight operational observability suitable for the current portfolio-scale deployment.

## HTTP-level observability

Structured JSON events are emitted to stdout and collected by the deployment platform.

Examples include:

```text
http_request.completed
agent_run.started
agent_run.completed
agent_run.failed
agent_run.busy
agent_run.http_timeout
```

## Correlation

```text
X-Request-ID
X-Run-ID
```

allow HTTP responses to be correlated with runtime events.

## Durable execution records

Agent-level execution records are persisted under:

```text
data/_runs/
```

ETL and SQL execution records include bounded operational metadata such as status, duration, validated relations, and result counts where appropriate.

## dbt evidence

dbt artifacts and deterministic metadata are used to record model execution state without exposing compiled SQL or secrets through the public API.

A separate Prometheus/Grafana/OpenTelemetry stack is intentionally **not required for portfolio v1**. Centralized observability can be added later if the project evolves into a multi-instance or production-operated service.

---

# Error and Boundary Semantics

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

Internal exception text, credentials, provider errors, and stack traces are not returned to callers.

---

# Current Durability Model

The portfolio deployment combines:

- a Railway persistent application volume
- managed PostgreSQL
- generated dbt runtime files
- persistent checkpoints, lineage, and run records

This is intentionally designed for a **single-instance deployment**.

The application runs one Uvicorn worker because coordination is currently process-local.

A future horizontally scaled deployment would require distributed coordination and more fully externalized operational state.

---

# Current Limitations

The current version is intentionally bounded:

- one application process / one Uvicorn worker
- one active agent execution at a time
- synchronous `/query` execution
- HTTP timeout does not forcibly cancel an already-running Python worker
- checkpoints, lineage, execution records, and generated dbt state rely on one persistent application volume
- no distributed task queue
- no horizontal multi-replica coordination
- no advanced CDC deletion/tombstone semantics
- no SCD Type 2 history modeling
- no heavy centralized metrics/trace stack
- explicit deterministic catalog validation exists, but semantic grounding of arbitrary user-supplied dataset names can still be strengthened further

These are explicit scope boundaries for portfolio v1 rather than hidden production claims.

---

# Roadmap

## Completed

| Phase | Scope | Status |
|---|---|---|
| 2A | Reliable API ingestion | ✅ |
| 2B | Persistent incremental ingestion | ✅ |
| 2C | Schema evolution | ✅ |
| 2D | Medallion architecture + lineage | ✅ |
| 2E | Agent runtime reliability + CI | ✅ |
| 2F | Data quality + contracts | ✅ |
| 2G | PostgreSQL warehouse bridge | ✅ |
| 2H | dbt integration | ✅ |
| 2I | Governed warehouse analytics | ✅ |
| 2J | Incremental warehouse processing | ✅ |
| 2K | FastAPI + Docker + Compose + container CI | ✅ |
| 2L | Production API hardening | ✅ |
| 2M | Railway cloud deployment + remote E2E validation | ✅ |

## Portfolio v1 — Final milestone

### Phase 2R — Final Validation + Release Polish

Remaining portfolio-polish work:

- final README and architecture presentation
- optional short GIF/video demo
- final regression run
- small semantic-grounding cleanup where useful
- `v1.0.0` release/tag

## Deferred / optional post-v1 work

Useful extensions that are deliberately **not blockers**:

- centralized metrics/tracing stack
- LLM cost dashboards
- asynchronous job queue / worker model
- externally coordinated distributed state
- multi-replica execution
- deletion/tombstone handling
- SCD Type 2 history
- row-level quarantine datasets
- richer lineage backends
- external workflow orchestration
- deeper enterprise security controls

---

# Portfolio / CV Summary

This repository demonstrates an end-to-end data-engineering system combining traditional data-platform engineering with guarded LLM orchestration:

```text
resilient ingestion
    +
incremental state
    +
schema evolution
    +
Medallion architecture
    +
PostgreSQL
    +
dbt
    +
quality contracts
    +
lineage / observability
    +
governed SQL
    +
FastAPI
    +
Docker
    +
GitHub Actions
    +
Railway deployment
    +
managed PostgreSQL
```

The central design decision is that **LLMs remain planners and routers while deterministic code owns sensitive physical execution**.

---

# License

See the repository license for usage terms.
