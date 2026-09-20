# Autonomous Data Engineer Agent

[![CI](https://github.com/Toukennn/Autonomous-data-engineer-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/Toukennn/Autonomous-data-engineer-agent/actions/workflows/ci.yml)

A safety-oriented, production-minded **agentic data engineering platform** for reliable API ingestion, incremental processing, PostgreSQL warehousing, dbt transformations, data-quality governance, lineage, observability, and governed natural-language SQL analytics.

The system uses **LangGraph** to route requests to specialized ETL and SQL agents while keeping sensitive operations under deterministic application control.

> **LLMs decide what should happen. Deterministic code decides how it is allowed to happen.**

The LLM may choose a supported workflow and produce typed plans, but it does **not** receive arbitrary Python execution, arbitrary filesystem access, unrestricted database access, unrestricted dbt execution, direct checkpoint control, or control over physical warehouse merge semantics.

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

The result is an agentic system that still demonstrates core data-engineering concerns:

- resilient API ingestion
- persistent incremental state
- schema evolution
- Medallion architecture
- business-key-aware merge/upsert
- PostgreSQL warehousing
- dynamically generated dbt models
- dbt tests and contracts
- governed SQL generation
- AST-based SQL safety
- lineage
- execution observability
- containerization
- CI
- API authentication
- liveness/readiness separation
- bounded concurrency and HTTP wait time
- request/run correlation IDs
- structured safe application logs

---

# System Architecture

The application contains three primary agents:

- **Data Engineer Agent** — top-level router.
- **ETL Analyst Agent** — orchestrates governed ingestion and transformation workflows.
- **SQL Analyst Agent** — translates analytical questions into validated read-only PostgreSQL queries.

The production-oriented HTTP/container boundary added in Phases **2K** and **2L** now wraps the agent system:

```text
                           Client
                             │
                             │ HTTPS / HTTP
                             ▼
                         FastAPI
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
          /health         /ready          /query
          liveness       readiness       API-key protected
              │              │              │
              │              │              ├── request ID
              │              │              ├── run ID
              │              │              ├── single-run guard
              │              │              └── HTTP timeout
              │              │
              │              ├── runtime storage
              │              └── PostgreSQL
              │
              └── process only
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
- SQL allowlisting
- SQL execution mode
- API authentication
- concurrency
- request timeouts
- error sanitization
- runtime observability metadata

The model cannot directly execute arbitrary Python, shell commands, filesystem mutations, arbitrary SQL, arbitrary Jinja, unrestricted dbt commands, or unrestricted database writes.

---

# Agent Architecture

## Data Engineer Router

The top-level LangGraph router classifies each request into one of two workflows:

```text
etl
sql
```

and delegates execution to the appropriate specialist.

![Data Engineer Graph](data_engineer_graph.png)

---

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

---

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

The same catalog snapshot is used for prompt context and deterministic SQL validation, reducing prompt-time / validation-time drift.

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

The planner does not write arbitrary SQL or Jinja.

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

# Development Phases

## Phase 2A — Reliable API Ingestion ✅

HTTP behavior was moved out of the agent layer and into a deterministic API client.

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

---

## Phase 2B — Persistent Incremental Ingestion ✅

Watermark checkpoints are persisted under:

```text
data/_state/
```

The LLM may identify logical incremental fields, but deterministic code owns checkpoint loading and advancement.

Checkpoint state advances only after required durable writes succeed.

Retry/merge semantics support:

```text
no business key
    → exact-row deduplication

business key configured
    → incoming rows replace historical rows with the same key
```

---

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

---

## Phase 2D — Medallion Architecture + Lineage ✅

File-backed Medallion structure:

```text
data/bronze/<dataset>/
data/silver/<dataset>/
data/gold/<dataset>/
```

Bronze stores source data and extraction/schema metadata. Silver consumes Bronze only. Gold consumes Silver only.

Deterministic lineage is persisted under:

```text
data/_lineage/lineage.json
```

Supported lineage event types include extraction, transformation, curation, warehouse synchronization, and dbt builds.

---

## Phase 2E — Agent Runtime Reliability + CI ✅

Implemented:

- deterministic agent tests
- failure-stop behavior
- tool-call limits
- structured execution records
- GitHub Actions CI

`ExecutionRunStore` persists agent-level runtime records under:

```text
data/_runs/
```

Default ETL tool-call limit:

```text
ETL_MAX_TOOL_CALLS=8
```

---

## Phase 2F — Data Quality + Contracts ✅

Quality rules are represented as typed contracts instead of free-form LLM instructions.

Contracts can be synchronized into deterministic checks and dbt tests.

The model cannot silently weaken an established contract or bypass required quality checks.

---

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

The application, not the LLM, owns merge SQL and physical uniqueness enforcement.

---

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

Generated model SQL comes from validated typed plans, not arbitrary LLM-produced dbt code.

---

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

---

## Phase 2J — Incremental Warehouse Processing ✅

Phase 2J extended incremental semantics into the PostgreSQL/dbt path.

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

The two-run E2E path verifies that a subsequent run updates/inserts the correct rows without rebuilding the full logical dataset incorrectly.

---

# Phase 2K — Containerized Runtime & Deployment Foundation ✅

Phase 2K moved the project from a local Python application into a reproducible containerized service boundary.

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

## FastAPI runtime

The application is exposed through `app/api.py`.

Primary endpoints:

| Endpoint | Purpose | Authentication |
|---|---|---|
| `GET /health` | cheap process liveness | public |
| `GET /ready` | dependency readiness | public |
| `POST /query` | governed agent execution | `X-API-Key` |

The HTTP boundary keeps LLM construction lazy, allowing infrastructure probes to operate without contacting the LLM.

## Docker image

The Docker image:

- uses Python 3.12 slim
- installs dependencies with `uv`
- pins the copied `uv` binary
- runs as non-root UID/GID `10001`
- keeps application source root-owned
- grants write access only to required runtime/dbt directories
- exposes port `8000`
- runs one Uvicorn worker
- uses `/app/data` as `DATA_ROOT`

The single-worker choice is deliberate because the current runtime contains process-local locks, local durable state, and generated dbt files.

## Docker health check

Docker checks:

```text
GET /health
```

rather than `/ready`.

This means a temporary PostgreSQL outage does not incorrectly classify the API process itself as dead.

## Docker Compose

`compose.yaml` runs:

```text
app
PostgreSQL 17
```

on a private bridge network.

PostgreSQL readiness is checked with `pg_isready`.

Named volumes persist:

- PostgreSQL data
- application durable state
- generated dbt metadata
- generated dbt sources
- generated staging models
- generated marts

## Full containerized E2E

`scripts/phase_2k_e2e.py` validates the real container path:

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

The script also verifies persisted container state and warehouse row counts.

## Container CI gate

The GitHub Actions workflow now has two major gates:

```text
Python quality gate
    ├── Ruff
    ├── pytest
    └── uv build
         ↓
Docker gate
    ├── build image
    ├── start container
    ├── wait for Docker health
    ├── verify /health
    ├── verify non-root UID 10001
    └── verify DATA_ROOT=/app/data
```

No real LLM or database credentials are embedded in CI.

---

# Phase 2L — Production API Hardening ✅

Phase 2L hardened the public HTTP boundary before cloud deployment.

```text
2L.1  Liveness vs readiness separation      ✅
2L.2  Explicit busy/concurrency handling     ✅
2L.3  Bounded request execution wait         ✅
2L.4  Inbound API-key authentication         ✅
2L.5  Request/run correlation IDs            ✅
2L.6  Safe structured HTTP observability     ✅
```

## 2L.1 — Liveness vs readiness

`GET /health` is intentionally cheap:

```text
process alive?
    ↓
200 {"status":"ok"}
```

It does not contact PostgreSQL, the LLM, or external APIs.

`GET /ready` verifies whether the instance can accept governed work:

```text
runtime storage writable?
        +
PostgreSQL reachable?
        ↓
200 {"status":"ready"}
```

Failure is sanitized:

```text
503
{"detail":"Service is not ready."}
```

Database passwords, hostnames, filesystem paths, stack traces, and raw driver errors are not exposed through the HTTP response.

---

## 2L.2 — Explicit busy/concurrency handling

The current runtime intentionally permits one agent execution at a time.

The execution lock is acquired non-blockingly.

```text
execution slot free
      ↓
request starts

execution slot occupied
      ↓
503 Service Unavailable
Retry-After: 5
```

A second caller therefore does not sit in an invisible unbounded in-process queue.

---

## 2L.3 — Bounded HTTP execution wait

Agent HTTP requests have a configurable wait limit:

```text
AGENT_REQUEST_TIMEOUT_SECONDS=600
```

If the HTTP deadline is exceeded:

```text
504
{"detail":"Agent request timed out."}
```

Important: this is an **HTTP deadline, not unsafe thread cancellation**.

Python cannot safely terminate an arbitrary running thread. Therefore, if a request times out while the underlying agent is still finishing durable work, the execution lock remains held until that worker actually terminates.

```text
client waits
    ↓
HTTP deadline reached
    ↓
504 returned
    ↓
underlying worker may still be running
    ↓
execution slot remains BUSY
    ↓
worker really finishes
    ↓
lock released
```

This prevents a timed-out execution from overlapping with a new run and mutating shared state concurrently.

---

## 2L.4 — Inbound API-key authentication

`POST /query` is protected with:

```text
X-API-Key: <SERVICE_API_KEY>
```

The configured key is stored separately from outbound API-ingestion credentials.

```text
API_AUTH_TOKEN
    → outbound authentication
      Agent → external API

SERVICE_API_KEY
    → inbound authentication
      client → this FastAPI service
```

The key is validated with constant-time comparison and must be at least 32 characters.

If inbound authentication is not configured correctly, the service fails closed for protected work.

`/health` and `/ready` remain public so container/orchestrator probes do not need application credentials.

---

## 2L.5 — Request and run correlation IDs

Every HTTP request receives a server-generated request ID:

```text
X-Request-ID
```

An actual agent execution also receives a separate run ID:

```text
X-Run-ID
```

Semantics:

```text
HTTP request
    └── request_id

agent execution starts
    └── run_id
```

A busy request receives an `X-Request-ID` but no `X-Run-ID`, because no agent execution actually began.

These IDs connect HTTP responses to structured runtime logs.

---

## 2L.6 — Safe structured HTTP observability

`utils/http_observability.py` emits newline-delimited structured JSON to stdout.

Example:

```json
{"duration_ms":2.734,"event":"http_request.completed","method":"GET","path":"/health","request_id":"...","status_code":200}
```

Run-level events include:

```text
agent_run.started
agent_run.completed
agent_run.failed
agent_run.busy
agent_run.submission_failed
agent_run.http_timeout
```

The logger uses an explicit metadata allowlist.

It deliberately does **not** log:

- request bodies
- user prompts
- LLM responses
- `X-API-Key`
- arbitrary HTTP headers
- database credentials
- raw exception messages

Observability failures are designed not to fail an otherwise valid workflow.

This stdout-oriented design is intentionally cloud-friendly: a deployment platform can collect container logs without requiring a custom logging backend inside the application.

---

# HTTP API

## Liveness

```bash
curl http://127.0.0.1:8000/health
```

Expected:

```json
{"status":"ok"}
```

## Readiness

```bash
curl http://127.0.0.1:8000/ready
```

Expected when dependencies are ready:

```json
{"status":"ready"}
```

## Agent query

```bash
curl \
  -X POST \
  http://127.0.0.1:8000/query \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $SERVICE_API_KEY" \
  -d '{"message":"Build a warehouse-backed pipeline from the users API."}'
```

Successful responses include correlation headers similar to:

```text
X-Request-ID: <uuid>
X-Run-ID: <uuid>
```

---

# Runtime Persistence

Persistent application state lives below `DATA_ROOT`.

Local default:

```text
<project>/data
```

Docker:

```text
/app/data
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

Generated dbt runtime state is stored under controlled dbt directories and persisted through named Docker volumes in the Compose environment.

---

# PostgreSQL Layout

The warehouse uses controlled schemas, including a Bronze ingestion schema and dbt-managed analytical schemas.

Conceptually:

```text
bronze
    ↓
<dbt target>_silver
    ↓
<dbt target>_gold
```

Natural-language SQL analytics are restricted to the governed analytical catalog.

---

# Read-Only SQL Execution

Generated analytical SQL is treated as untrusted.

Before execution it is:

1. parsed with SQLGlot
2. checked for allowed query structure
3. checked against the governed relation catalog
4. restricted to approved schemas/relations
5. executed through a read-only database path
6. bounded by statement timeout and row limits

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

Generate a strong inbound service key with:

```bash
uv run python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Then start the stack:

```bash
docker compose up -d --build
```

Check it:

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/ready
```

Stop it with:

```bash
docker compose down
```

To remove the stack **and its named volumes**:

```bash
docker compose down -v
```

Use `-v` carefully because it removes persisted PostgreSQL/application state.

---

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

Important configuration groups include:

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

`SERVICE_API_KEY` protects this application's `POST /query` endpoint.

Never commit the real `.env`.

---

# Running the System

## Local API

```bash
uv run uvicorn app.api:app --host 0.0.0.0 --port 8000
```

## Docker

```bash
docker compose up -d --build
```

## Logs

Application and structured HTTP logs can be viewed with:

```bash
docker compose logs -f app
```

Structured safe events are written to stdout alongside the runtime logs.

---

# Testing

For normal development:

```bash
uv run ruff check .
uv run pytest -v
```

A package build is also checked by CI:

```bash
uv build
```

## Important test coverage

The test suite covers, among other things:

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

Phase 2K verifies the real containerized path through API → agent → data pipeline → warehouse → governed SQL.

---

# CI

GitHub Actions runs on pushes and pull requests to `main`.

The workflow currently validates:

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
non-root UID check
  ↓
DATA_ROOT check
```

The application container is intentionally smoke-tested without real database/LLM secrets because `/health` is a dependency-free liveness endpoint.

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

The project currently combines:

- local persistent application files
- named Docker volumes
- PostgreSQL
- generated dbt runtime files

This is appropriate for a **single-instance deployment**.

The application intentionally runs one Uvicorn worker because coordination is currently process-local.

A future horizontally scaled deployment would need distributed coordination and externalized state.

---

# Current Limitations

The current version is intentionally bounded.

- One application process / one Uvicorn worker is supported.
- Only one agent execution is allowed at a time.
- An HTTP timeout does not forcibly cancel a running Python worker.
- Checkpoints, lineage, execution records, and generated dbt state are still local-volume-backed.
- The project does not yet use a distributed task queue.
- It does not yet implement horizontal multi-replica coordination.
- It has not yet been deployed to a public cloud environment as part of the repository milestone.
- Structured HTTP logs are emitted to stdout but are not yet shipped to a centralized observability backend.
- Advanced CDC/deletion/tombstone semantics are outside the current v1 scope.
- SCD Type 2/history modeling is outside the current v1 scope.

These limitations are explicit rather than hidden behind unsupported concurrency assumptions.

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

## Portfolio v1 — Remaining milestones

### Phase 2M — Real Cloud Deployment

Planned goals:

- deploy the existing container
- use managed PostgreSQL
- HTTPS/TLS
- runtime secret management
- deployment-specific configuration
- verify `/health` and `/ready` in the deployed environment
- demonstrate the real remote API boundary

### Phase 2N — Centralized Observability

Planned goals:

- collect structured application logs centrally
- basic error/latency metrics
- request/run ID searchability
- deployment-level alerts
- LLM usage/cost visibility where practical

### Phase 2R — Final Validation + Release Polish

Planned goals:

- deployed end-to-end validation
- restart/persistence tests
- moderate load/boundary testing
- final architecture diagram
- concise demo
- clean setup/deployment documentation
- `v1.0.0` release

## Optional post-v1 work

Useful extensions that are deliberately **not blockers** for the portfolio release:

- asynchronous job queue / worker model
- externally coordinated distributed state
- multi-replica execution
- deletion/tombstone handling
- SCD Type 2 history
- row-level quarantine datasets
- richer lineage backends
- deeper security/operational controls
- external workflow orchestration

---

# Portfolio / CV Summary

This repository demonstrates an end-to-end data-engineering system that combines traditional data-platform engineering with guarded LLM orchestration:

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
CI/CD foundations
    +
API hardening
```

The central design decision is that **LLMs remain planners and routers while deterministic code owns sensitive physical execution**.

---

# License

See the repository license for usage terms.
