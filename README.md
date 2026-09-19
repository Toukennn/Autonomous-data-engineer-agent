# Autonomous Data Engineer Agent

A safety-oriented agentic data engineering system for **API ingestion**, **deterministic ETL workflows**, **Medallion architecture**, **PostgreSQL warehousing**, **dbt transformations**, **data-quality contracts**, **lineage**, **runtime observability**, and **governed natural-language SQL analytics**.

The project uses LangGraph to route requests to specialized ETL and SQL agents while keeping sensitive operations under deterministic application control.

> **LLMs decide what should happen. Deterministic tools decide how it happens.**

The LLM may choose a supported workflow and create typed transformation or quality plans, but it does not receive arbitrary Python execution, arbitrary filesystem access, direct checkpoint control, schema-policy control, unrestricted dbt execution, or unrestricted database access.

---

# Overview

The system contains three main agents:

- **Data Engineer Agent** — routes requests to the correct specialist.
- **ETL Analyst Agent** — orchestrates bounded API → Bronze → Silver → Gold workflows using either the file-backed Pandas path or the PostgreSQL/dbt path.
- **SQL Analyst Agent** — converts natural-language analytical questions into governed, read-only PostgreSQL queries against approved Silver/Gold warehouse relations.

The warehouse-backed path is:

```text
External API
    │
    ▼
Python deterministic ingestion
    │
    ▼
Bronze filesystem dataset
    │
    ▼
PostgreSQL bronze.<dataset>
    │
    ▼
dbt
 ┌──┴───────────────┐
 ▼                  ▼
Silver views     Gold marts
    │                  │
    ├──── dbt tests ───┤
    │                  │
    └──── lineage / observability
                       │
                       ▼
              governed analytics catalog
                       │
                       ▼
                  SQL Analyst
                       │
                       ▼
              SQLGlot AST validation
                       │
                       ▼
             read-only PostgreSQL
                       │
                       ▼
                analytical answer
```

At a higher level:

```text
                               User Request
                                    │
                                    ▼
                          Data Engineer Router
                          ┌─────────┴─────────┐
                          ▼                   ▼
                     ETL Analyst          SQL Analyst
                          │                   │
             ┌────────────┴────────────┐      │
             ▼                         ▼      ▼
      file-backed path              dbt path  governed catalog
             │                         │      │
      Bronze → Silver → Gold       Bronze FS │
                                       ↓     │
                                  PostgreSQL │
                                       ↓     │
                                   dbt Silver│
                                       ↓     │
                                    dbt Gold │
                                       │     │
                               quality/tests │
                                       │     │
                          lineage/observability
                                             │
                                             ▼
                                     SQL generation
                                             │
                                             ▼
                                      SQLGlot AST
                                             │
                                             ▼
                                  relation/schema allowlist
                                             │
                                             ▼
                                   read-only execution
```

---

# Core Design Principle

The project deliberately separates **planning** from **execution**.

```text
LLM:
    decides WHAT should happen

Deterministic application code:
    decides HOW it may happen
```

Examples:

- the LLM may request a supported transformation operation
- deterministic code validates the typed plan and compiles it
- the LLM may generate analytical SQL
- deterministic SQLGlot validation decides whether it may execute
- the LLM may describe a quality requirement
- deterministic quality code decides pass/fail
- the LLM may name a logical dataset
- application code controls physical paths, schemas, model names, selectors, credentials, and execution boundaries

The system treats all LLM output as untrusted input.

---

# Architecture

## Data Engineer Router

The top-level LangGraph agent classifies each request as either:

```text
etl
```

or:

```text
sql
```

and delegates it to the corresponding specialist.

![Data Engineer Graph](data_engineer_graph.png)

The router does not execute ETL or SQL itself.

---

## ETL Agent

The ETL agent is a bounded ReAct-style orchestrator with a deliberately small tool surface.

It currently exposes six tools:

```text
extract_load_tool
bronze_to_silver_tool
silver_to_gold_tool
dbt_bronze_to_silver_tool
dbt_silver_to_gold_tool
configure_quality_contract_tool
```

### File-backed deterministic path

```text
External API
    ↓
Bronze file
    ↓
bronze_to_silver_tool
    ↓
Silver file
    ↓
silver_to_gold_tool
    ↓
Gold file
```

This path uses typed `TransformPlan` objects plus deterministic Pandas operations.

### PostgreSQL + dbt path

```text
External API
    ↓
extract_load_tool
    ↓
Bronze filesystem dataset
    ↓
dbt_bronze_to_silver_tool
    ├─ synchronize Bronze → PostgreSQL
    ├─ create typed DBTTransformPlan
    ├─ deterministically compile dbt SQL
    ├─ create Silver model
    ├─ synchronize dbt quality tests
    └─ execute bounded dbt build
    ↓
dbt Silver
    ↓
dbt_silver_to_gold_tool
    ├─ create typed DBTTransformPlan
    ├─ deterministically compile dbt SQL
    ├─ create Gold model
    ├─ synchronize dbt quality tests
    └─ execute bounded dbt build
    ↓
dbt Gold
```

The agent cannot directly choose:

- arbitrary input/output filesystem paths
- arbitrary PostgreSQL schemas or physical table names
- direct Bronze → Gold transitions
- arbitrary Python code
- arbitrary SQL or Jinja for dbt model generation
- arbitrary dbt selectors or CLI arguments
- dbt project/profile paths
- database credentials
- quality-check bypasses
- direct mutation or weakening of an existing quality contract

For dependent multi-stage requests, execution is sequential. A failed required stage stops the workflow before downstream stages run.

![ETL Analyst Graph](etl_analyst_graph.png)

---

## SQL Analyst

The SQL Analyst is a governed analytical interface over approved dbt Silver and Gold relations.

Its current flow is:

```text
natural-language question
        ↓
question curation
        ↓
load one governed analytics catalog snapshot
        ↓
build SQL-generation prompt from that snapshot
        ↓
LLM generates one PostgreSQL query
        ↓
SQLGlot AST validation
        ↓
scope-aware relation/schema allowlisting
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

The same in-memory catalog snapshot is used for both:

```text
LLM prompt context
        =
deterministic SQL validation
```

This avoids prompt-time / validation-time catalog drift within one SQL-agent run.

![SQL Analyst Graph](sql_analyst_graph.png)

---

# Planner LLM vs Deterministic Executor

## File-backed Transformation Planner

The planner receives the user request plus dataset metadata and returns a validated Pydantic `TransformPlan`.

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

Trusted Python code in `ETLTools` controls execution.

## dbt Transformation Planner

Warehouse-backed transformations use a separate typed `DBTTransformPlan`.

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

The planner does **not** write arbitrary SQL.

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

Silver plans do not allow aggregation. Gold plans may use supported aggregation operations.

## Data-Quality Planner

When the user explicitly requests quality requirements, a planner creates a validated `DataQualityContract`.

Supported rules currently include:

```text
not_null
unique
accepted_values
range
row_count
```

The planner is instructed not to invent quality constraints.

---

# Phase 2A — Reliable API Ingestion ✅

Phase 2A moved HTTP behavior out of the agent layer into a deterministic `APIClient`.

Implemented capabilities include:

- top-level JSON arrays
- nested record paths
- controlled JSON validation
- retries and exponential backoff
- `Retry-After`
- handling of `429` and transient `5xx` responses
- token authentication
- configurable auth header/scheme
- configurable user agent
- response/page/record limits
- pagination-loop detection
- redirect limits
- normalized external API errors
- SSRF/public-destination validation
- redirect destination validation
- restricted authenticated cross-origin redirects

Authenticated requests must use HTTPS.

---

# Phase 2B — Persistent Incremental Ingestion ✅

Phase 2B introduced durable watermark-based ingestion.

```text
LLM chooses:
    state_key
    watermark_param
    watermark_field

Deterministic code controls:
    previous watermark_value
    checkpoint loading
    checkpoint advancement
```

`utils/incremental_state.py` persists checkpoints under:

```text
data/_state/
```

Retry safety currently uses exact-row deduplication.

The checkpoint advances only after the required durable writes succeed.

Checkpoint metadata binds state to the source/configuration so one state key cannot silently be reused for a different incremental pipeline.

---

# Phase 2C — Schema Evolution ✅

Source schema transitions are decided deterministically:

```text
same schema                 → ACCEPT
added columns only          → ACCEPT
removed columns             → REJECT
logical type changes        → REJECT
```

Implemented features include:

- schema drift detection
- additive schema evolution
- logical dtype normalization
- schema fingerprints
- schema history
- breaking-change rejection reports
- stable rejection fingerprints

Bronze schema history is persisted with the dataset.

---

# Phase 2D — Medallion Architecture, Agent Integration, and Lineage ✅

```text
2D.1  Deterministic Bronze layer          ✅
2D.2  Silver transformation layer         ✅
2D.3  Gold curated/output layer           ✅
2D.4  Agent integration + lineage         ✅
```

The file-backed Medallion path is:

```text
External API
    ↓
 Bronze
    ↓
 Silver
    ↓
  Gold
```

## Bronze

```text
data/bronze/<dataset>/
    extracted_data.<format>
    extraction_metadata.json
    schema_history.json
    schema_change_rejections.json   # when required
```

## Silver

```text
data/silver/<dataset>/
    transformed_data.<format>
    transformation_metadata.json
```

Silver consumes Bronze only.

## Gold

```text
data/gold/<dataset>/
    curated_data.<format>
    curation_metadata.json
```

Gold consumes Silver only.

## Lineage

`utils/lineage.py` persists deterministic lineage under:

```text
data/_lineage/lineage.json
```

Lineage events include:

```text
extract
transform
curate
warehouse_sync
dbt_build
```

Lineage is written by deterministic application code, not by the LLM.

---

# Phase 2E — Agent Runtime Reliability, Observability, and CI ✅

```text
2E.1  Deterministic agent orchestration tests   ✅
2E.2  Failure-stop and loop/runtime guards      ✅
2E.3  Structured execution observability        ✅
2E.4  GitHub Actions CI                         ✅
```

The ETL state tracks:

```text
run_id
tool_call_count
workflow_failed
failure_reason
```

`ETL_MAX_TOOL_CALLS` bounds tool execution in one ETL-agent run.

Default:

```text
ETL_MAX_TOOL_CALLS=8
```

`ExecutionRunStore` persists structured run records under:

```text
data/_runs/
```

Execution events use allowlisted operational metadata rather than raw prompts or unrestricted tool payloads.

GitHub Actions runs Ruff, pytest, and package build checks.

---

# Phase 2F — Data Quality, Dataset Contracts, and Quality Governance ✅

```text
2F.1  Deterministic quality-rule engine        ✅
2F.2  Persisted dataset quality contracts      ✅
2F.3  Silver / Gold quality gates              ✅
2F.4  Agent integration + quality reporting    ✅
2F.5  Quality observability + lineage linkage  ✅
```

Core principle:

> **The LLM may describe what quality is expected. Deterministic code decides whether the data passes.**

Contracts are stored under:

```text
data/_contracts/<layer>/<dataset>.json
```

For file-backed Silver/Gold:

```text
candidate dataframe
        ↓
quality contract
        ↓
deterministic evaluation
   ┌────┴────┐
   ▼         ▼
 reject     pass
   │         │
 preserve    atomic promotion
 last good
 output
```

Phase 2H synchronizes the same contract model into dbt tests for warehouse-backed datasets.

---

# Phase 2G — PostgreSQL Warehouse Bridge ✅

```text
2G.1  Deterministic PostgreSQL writer       ✅
2G.2  Bronze dataset → PostgreSQL bridge    ✅
2G.3  Warehouse metadata + lineage          ✅
```

`utils/warehouse.py` implements `PostgresWarehouseLoader`.

Important controls include:

- application-controlled `bronze` schema
- logical dataset-name validation
- PostgreSQL 63-byte identifier guards
- quoted identifiers via Psycopg
- deterministic Pandas → PostgreSQL type mapping
- transactional writes
- rollback on failure
- normalized warehouse exceptions

The LLM never chooses the physical Bronze schema.

## Dependency-safe refresh

Existing Bronze tables are refreshed in place:

```text
inspect existing table
      ↓
validate physical schema
      ↓
add allowed new columns
      ↓
TRUNCATE in transaction
      ↓
INSERT refreshed rows
      ↓
COMMIT
```

The loader does **not** use `DROP TABLE ... CASCADE`, preserving downstream dbt dependencies.

Successful sync persists:

```text
data/bronze/<dataset>/warehouse_sync_metadata.json
```

and then refreshes the generated dbt source registry and records `warehouse_sync` lineage.

---

# Phase 2H — dbt Integration ✅

```text
2H.1  dbt project + PostgreSQL adapter        ✅
2H.2  Dynamic Bronze dbt sources              ✅
2H.3  Silver dbt models                       ✅
2H.4  Gold dbt marts                          ✅
2H.5  dbt tests + quality governance          ✅
2H.6  Bounded dbt execution                   ✅
2H.7  Typed dbt planner + agent integration   ✅
2H.8  dbt artifacts → lineage/observability   ✅
```

The implemented dbt path is:

```text
Bronze filesystem
      ↓
PostgreSQL Bronze
      ↓
generated dbt source registry
      ↓
DBTTransformPlan
      ↓
DBTSQLCompiler
      ↓
generated Silver / Gold models
      ↓
dbt build
      ↓
dbt tests
      ↓
manifest.json + run_results.json
      ↓
lineage + execution observability
```

## Dynamic Bronze sources

`DBTSourceRegistry` generates:

```text
dbt/models/sources/bronze_sources.yml
```

from successfully warehouse-synchronized Bronze datasets.

## Silver models

Generated Silver models use names such as:

```text
stg_<dataset>
```

and are materialized as views in:

```text
dbt_dev_silver
```

with the default target schema.

## Gold marts

Generated Gold models use names such as:

```text
mart_<dataset>
```

and are materialized as tables in:

```text
dbt_dev_gold
```

Gold generation requires an existing governed Silver dbt model and its persisted metadata.

## dbt quality tests

Quality contracts are deterministically translated into dbt tests.

Mappings include:

```text
NotNull        → dbt not_null
Unique         → quality_unique_combination
AcceptedValues → quality_accepted_values
Range          → quality_range
RowCount       → quality_row_count
```

Custom generic tests live under:

```text
dbt/tests/generic/quality_contract_tests.sql
```

## Bounded dbt execution

`DBTExecutor` controls:

- project directory
- profiles directory
- database environment
- target schema
- thread count
- model-file validation
- selectors
- execution locking
- `dbtRunner`
- exception normalization

The LLM cannot choose arbitrary dbt CLI arguments or selectors.

## Safe dbt artifacts

`utils/dbt_artifacts.py` reads a bounded subset of:

```text
dbt/target/manifest.json
dbt/target/run_results.json
```

Allowed artifact metadata includes:

- invocation ID
- model unique ID
- model name
- model status
- timing
- relation identity
- dependencies
- executed model IDs
- dbt test status/failure counts

It excludes:

- compiled SQL
- raw dbt output
- adapter responses
- credentials
- CLI dictionaries
- filesystem paths

---

# Phase 2I — Governed Warehouse Analytics ✅

Phase 2I connects the SQL Analyst to warehouse-backed Silver/Gold outputs without giving the LLM unrestricted database access.

```text
2I.1  Safe Silver/Gold analytics catalog       ✅
2I.2  SQL AST relation/schema allowlisting     ✅
2I.3  SQL Analyst → governed dbt warehouse     ✅
2I.4  SQL execution observability              ✅
2I.5  Full ETL → dbt → analytics E2E           ✅
```

The security boundary is:

```text
LLM decides WHAT analytical query is needed
                 ↓
deterministic catalog decides WHAT EXISTS
                 ↓
SQLGlot decides WHAT MAY BE QUERIED
                 ↓
PostgreSQL executes read-only
```

## 2I.1 — Governed analytics catalog

`DatabaseUtil.analytics_catalog()` builds a deterministic metadata-only catalog for exactly:

```text
<DBT_TARGET_SCHEMA>_silver
<DBT_TARGET_SCHEMA>_gold
```

For the default configuration:

```text
dbt_dev_silver
dbt_dev_gold
```

The catalog contains:

- schema names
- layer (`silver` / `gold`)
- relation names
- relation type (`table` / `view`)
- column names
- column data types

It does **not** fetch or expose sample rows.

Bronze, `public`, `information_schema`, `pg_catalog`, and other unrelated schemas are excluded.

## 2I.2 — Scope-aware SQL relation/schema allowlisting

`utils/sql_safety.py` revalidates the catalog and uses SQLGlot scopes to distinguish:

- physical PostgreSQL relations
- CTEs
- subqueries

Governed SQL must satisfy all of the following:

- exactly one parsed query
- read-only AST
- no forbidden DML/DDL
- every physical relation is schema-qualified
- every physical schema exists in the governed catalog
- every physical relation exists in the governed catalog
- no cross-database references
- no Bronze
- no `public`
- no `information_schema`
- no `pg_catalog`
- no `pg_*` system schemas
- at least one approved Silver or Gold physical relation is referenced

CTEs may be referenced without schema qualification, but physical relations inside them must still be governed.

The validator returns the approved physical relation identities as:

```text
referenced_relations
```

for downstream observability.

## 2I.3 — One catalog snapshot for prompting and validation

The SQL Agent loads one governed analytics catalog snapshot at prompt-building time.

That same snapshot is stored in graph state and passed to `SQLSafetyValidator`.

```text
catalog loaded once
      │
      ├── serialize for LLM prompt
      │
      └── enforce in SQL validator
```

The validator does not perform a second catalog lookup.

This keeps the LLM-visible schema context aligned with the deterministic enforcement boundary for that run.

## 2I.4 — SQL execution observability

`ExecutionRunStore` is shared by the ETL and SQL agents.

SQL runs record safe structured events such as:

```text
sql_safety
sql_execution
```

Successful safety metadata may include:

```text
relation_count
referenced_relations
```

Successful execution metadata may include:

```text
relation_count
referenced_relations
row_count
column_count
truncated
duration
```

Failure metadata records only safe information such as:

```text
error_type
```

SQL observability deliberately excludes:

- user questions
- curated questions
- generated SQL text
- prompt text
- result row values
- raw database error messages
- credentials

Regression tests verify these privacy guarantees.

## 2I.5 — Full end-to-end validation

`phase_2i_e2e.py` exercises the complete stack using the Open Library public API.

The test pipeline is:

```text
Open Library Search API
        ↓
record_path = docs
        ↓
Bronze: books_phase2i
        ↓
bronze.books_phase2i
        ↓
Silver: books_phase2i_clean
        ↓
dbt_dev_silver.stg_books_phase2i_clean
        ↓
Gold: books_phase2i_modern
        ↓
dbt_dev_gold.mart_books_phase2i_modern
        ↓
governed catalog
        ↓
natural-language analytical question
        ↓
generated SQL
        ↓
SQLGlot + relation allowlist
        ↓
read-only PostgreSQL
        ↓
natural-language answer
```

The current E2E request uses:

```text
https://openlibrary.org/search.json?q=machine%20learning&fields=key,title,first_publish_year,edition_count&limit=20&page=1
```

with records under:

```text
docs
```

The Gold transformation keeps books where:

```text
first_publish_year >= 2000
edition_count >= 5
```

and the analytical question asks for the books ordered by highest edition count.

A successful validation run confirmed:

- 20 Bronze rows
- 20 Silver rows
- 4 Gold rows in that live API response
- the SQL Agent selected `dbt_dev_gold.mart_books_phase2i_modern`
- the SQL safety validator approved that exact governed relation
- read-only execution returned the Gold rows
- SQL observability recorded safe relation/row/column metadata

Because Open Library is a live external API, exact row contents and counts can change over time.

Run the E2E locally with:

```bash
uv run python phase_2i_e2e.py
```

Inspect the warehouse with:

```bash
uv run python inspect_warehouse.py
```

---

# Current Durability Model

## Incremental Bronze ingestion

```text
load checkpoint
      ↓
extract API data
      ↓
normalize records
      ↓
merge with durable Bronze data
      ↓
validate source schema transition
      ↓
atomic Bronze dataset save
      ↓
schema history persistence
      ↓
atomic extraction metadata save
      ↓
lineage persistence
      ↓
checkpoint commit
```

## File-backed Silver / Gold promotion

```text
load source layer
      ↓
apply validated TransformPlan
      ↓
candidate dataframe
      ↓
load target quality contract
      ↓
deterministic quality evaluation
      │
      ├── fail → rejection report → STOP
      │
      └── pass / no contract
                 ↓
          atomic dataset save
                 ↓
              metadata
                 ↓
              lineage
```

## Warehouse-backed dbt promotion

```text
Bronze filesystem
      ↓
refresh Bronze PostgreSQL relation in place
      ↓
persist warehouse sync metadata
      ↓
refresh generated dbt source registry
      ↓
warehouse_sync lineage
      ↓
typed DBTTransformPlan
      ↓
deterministic SQL compilation
      ↓
persist model + model metadata
      ↓
synchronize dbt quality tests
      ↓
bounded dbt build
      ↓
validate manifest/run_results
      ↓
dbt_build lineage
      ↓
safe execution observability
```

Observability failure does not invalidate an otherwise successful data commit because observability is diagnostic rather than part of the data-commit contract.

---

# Runtime Persistence and Generated Artifacts

```text
data/_state/
    → incremental checkpoints

data/_contracts/
    → persisted Silver/Gold quality contracts

data/_lineage/
    → durable dataset / warehouse / dbt lineage

data/_runs/
    → ETL and SQL execution observability

data/bronze/<dataset>/
    → Bronze data, extraction metadata, schema history,
      schema rejection reports, warehouse sync metadata

data/silver/<dataset>/
    → file-backed Silver outputs

data/gold/<dataset>/
    → file-backed Gold outputs

dbt/generated_metadata/
    → validated generated model metadata + plan fingerprints

dbt/target/
    → ephemeral dbt execution artifacts consumed safely
```

---

# PostgreSQL Warehouse Layout

With the default target schema:

```text
bronze
└── <dataset>                    # PostgreSQL base table

dbt_dev_silver
└── stg_<dataset>                # dbt view

dbt_dev_gold
└── mart_<dataset>               # dbt table
```

The Silver/Gold schema prefix is controlled by:

```env
DBT_TARGET_SCHEMA=dbt_dev
```

---

# Read-Only SQL Execution

`DatabaseUtil` is intentionally separate from the warehouse writer.

The analytical path uses read-only PostgreSQL sessions with:

```text
generated SQL
      ↓
SQLGlot validation
      ↓
governed relation validation
      ↓
read-only transaction
      ├── statement timeout
      ├── result row limit
      └── rollback
      ↓
ReadOnlyQueryResult
```

`ReadOnlyQueryResult` contains:

```text
columns
rows
row_count
truncated
```

Only safe aggregate execution metadata is persisted to observability.

---

# Project Structure

```text
Autonomous-data-engineer-agent/
│
├── .github/
│   └── workflows/
│       └── ci.yml
│
├── agents/
│   ├── data_engineer.py
│   ├── etl_analyst.py
│   └── sql_analyst.py
│
├── config/
│   └── settings.py
│
├── dbt/
│   ├── dbt_project.yml
│   ├── profiles.yml
│   ├── models/
│   │   ├── sources/
│   │   ├── staging/
│   │   └── marts/
│   └── tests/
│       └── generic/
│           └── quality_contract_tests.sql
│
├── models/
│   ├── data_quality.py
│   └── schema.py
│
├── utils/
│   ├── api_client.py
│   ├── data_layers.py
│   ├── data_quality.py
│   ├── data_quality_contracts.py
│   ├── database.py
│   ├── dbt_artifacts.py
│   ├── dbt_execution.py
│   ├── dbt_model_metadata.py
│   ├── dbt_models.py
│   ├── dbt_quality.py
│   ├── dbt_sources.py
│   ├── dbt_sql.py
│   ├── etl_tools.py
│   ├── exceptions.py
│   ├── execution_observability.py
│   ├── incremental_state.py
│   ├── lineage.py
│   ├── llm_pick.py
│   ├── schema_evolution.py
│   ├── sql_safety.py
│   └── warehouse.py
│
├── tests/
│   ├── test_api_client.py
│   ├── test_data_layers.py
│   ├── test_data_quality.py
│   ├── test_data_quality_contracts.py
│   ├── test_database.py
│   ├── test_dbt_artifacts.py
│   ├── test_dbt_execution.py
│   ├── test_dbt_models.py
│   ├── test_dbt_project.py
│   ├── test_dbt_quality.py
│   ├── test_dbt_sources.py
│   ├── test_dbt_sql.py
│   ├── test_etl_agent.py
│   ├── test_etl_tools.py
│   ├── test_incremental_state.py
│   ├── test_lineage.py
│   ├── test_schema_evolution.py
│   ├── test_settings.py
│   ├── test_sql_agent.py
│   ├── test_sql_safety.py
│   └── test_warehouse.py
│
├── data_engineer_graph.png
├── etl_analyst_graph.png
├── sql_analyst_graph.png
├── inspect_warehouse.py
├── phase_2i_e2e.py
├── main.py
├── pyproject.toml
└── uv.lock
```

---

# Tech Stack

- Python 3.12+
- LangGraph / LangChain
- OpenAI / Anthropic
- Pandas / PyArrow
- PostgreSQL / Psycopg
- dbt Core / dbt-postgres
- Requests / urllib3
- SQLGlot
- Pydantic / Pydantic Settings
- pytest / Ruff / uv
- GitHub Actions

---

# Installation

```bash
git clone https://github.com/Toukennn/Autonomous-data-engineer-agent.git
cd Autonomous-data-engineer-agent
uv sync --locked
```

Copy `.env.example` to `.env` and configure the required LLM/database credentials.

Never commit a real `.env` file.

---

# Runtime Configuration

Important environment variables include:

```env
OPENAI_API_KEY=...
ANTHROPIC_API_KEY=...

DB_HOST=localhost
DB_PORT=5432
DB_USER=...
DB_PASSWORD=...
DB_NAME=...

SQL_STATEMENT_TIMEOUT_MS=10000
SQL_MAX_ROWS=1000

HTTP_TIMEOUT_SECONDS=30
API_MAX_RESPONSE_BYTES=20000000
API_MAX_TOTAL_RESPONSE_BYTES=100000000
API_MAX_PAGES=50
API_MAX_RECORDS=100000
API_RETRY_TOTAL=4
API_RETRY_BACKOFF_SECONDS=0.5
API_MAX_REDIRECTS=5

ETL_MAX_TOOL_CALLS=8

DBT_TARGET_SCHEMA=dbt_dev
DBT_THREADS=4
```

See `.env.example` for the full configuration.

---

# Running the System

Run the top-level router:

```bash
uv run python main.py
```

Run individual agents:

```bash
uv run python -m agents.data_engineer
uv run python -m agents.etl_analyst
uv run python -m agents.sql_analyst
```

Run the full Phase 2I integration scenario:

```bash
uv run python phase_2i_e2e.py
```

Inspect warehouse contents:

```bash
uv run python inspect_warehouse.py
```

---

# Testing

Coverage includes:

- SSRF/public-destination validation
- redirect safety
- pagination and retry behavior
- response/page/record limits
- authenticated API behavior
- watermark-based incremental extraction
- checkpoint durability and source/config binding
- schema drift classification
- additive schema evolution
- breaking-schema rejection
- deterministic transformation plans
- quality-rule evaluation
- persisted quality contracts
- Silver/Gold promotion gates
- ETL orchestration order
- failure-stop behavior
- ETL tool-call limits
- Bronze → PostgreSQL loading
- PostgreSQL identifier safety
- dependency-safe Bronze refresh
- dynamic dbt source generation
- generated Silver models
- generated Gold marts
- deterministic `DBTTransformPlan` compilation
- SQLGlot validation of generated dbt SQL
- dbt model metadata fingerprints
- dbt quality synchronization
- bounded dbt execution
- dbt artifact parsing
- dbt build → lineage linkage
- dbt build → observability linkage
- governed analytics catalog
- exclusion of sample rows from SQL LLM context
- SQL AST write protection
- relation/schema allowlisting
- cross-database rejection
- scope-aware CTE validation
- governed relation reporting
- single-snapshot catalog propagation
- read-only query execution
- SQL execution observability
- SQL observability privacy guarantees
- exclusion of generated SQL, prompts, row values, and raw DB errors from SQL run logs

Run the full test suite:

```bash
uv run pytest -v
```

Run Ruff:

```bash
uv run ruff check .
```

Build:

```bash
uv build
```

Complete local quality gate:

```bash
uv sync --locked
uv run ruff check .
uv run pytest -v
uv build
```

---

# Current Safety Model

The project treats LLM output as untrusted input.

The LLM does not directly control:

- arbitrary Python execution
- arbitrary local filesystem paths
- physical Bronze/Silver/Gold paths
- API authentication tokens
- previous checkpoint cursor values
- checkpoint persistence timing
- source-schema compatibility decisions
- schema-rejection policy
- PostgreSQL credentials
- arbitrary warehouse schemas
- arbitrary Bronze table names outside the logical dataset mapping
- destructive Bronze table replacement
- dbt project/profile paths
- arbitrary dbt selectors
- arbitrary dbt CLI arguments
- arbitrary dbt SQL/Jinja generation
- dbt artifact contents
- lineage file contents
- direct Bronze → Gold transitions
- unlimited ETL tool loops
- continuation after failed required ETL stages
- deterministic quality pass/fail decisions
- direct quality-contract file paths
- quality-contract fingerprints
- quality bypass
- replacement/weakening of a conflicting quality contract
- analytical access to Bronze
- analytical access to `public`
- analytical access to PostgreSQL system schemas
- arbitrary analytical relations not present in the governed catalog
- cross-database analytical references
- SQL execution outside read-only PostgreSQL sessions

For dbt transformations:

```text
LLM → validated DBTTransformPlan → deterministic SQL compiler → dbt
```

For analytical SQL:

```text
LLM → governed catalog → SQLGlot AST + relation allowlist → read-only PostgreSQL
```

---

# Current Limitations

- incremental retry idempotency still uses exact-row equality rather than business-key upserts
- Bronze warehouse synchronization currently uses full-table refresh-in-place rather than business-key incremental merge/upsert
- dbt Gold models are currently rebuilt as tables rather than application-governed incremental models
- breaking source schema changes are rejected rather than automatically migrated
- optional fields disappearing from a whole batch may appear as schema removal
- response-size limits are not yet enforced while streaming the HTTP body
- quality rules are currently limited to `not_null`, `unique`, `accepted_values`, `range`, and `row_count`
- file-backed Pandas and warehouse-backed dbt transformation paths coexist
- dbt model generation uses a bounded typed operation set rather than unrestricted SQL modeling
- generated dbt model metadata is file-backed
- lineage uses a single JSON history and is not intended for highly concurrent distributed writers
- execution observability is local file-backed rather than centralized tracing/metrics
- dbt execution uses an in-process lock rather than distributed coordination
- quality rejections preserve aggregate diagnostics but do not provide row-level quarantine datasets
- live-LLM evaluation and cost monitoring are not yet implemented
- the Phase 2I E2E uses a live public API, so external API availability/content can change independently of the repository

---

# Roadmap

## Completed

### Phase 2A — Reliable API Ingestion

- ✅ deterministic `APIClient`
- ✅ pagination
- ✅ retries / rate-limit handling
- ✅ authenticated APIs
- ✅ extraction limits
- ✅ SSRF / redirect hardening

### Phase 2B — Incremental Ingestion

- ✅ persistent checkpoints
- ✅ watermark-based extraction
- ✅ atomic persistence
- ✅ retry idempotency
- ✅ agent-safe incremental configuration
- ✅ checkpoint/source binding

### Phase 2C — Schema Evolution

- ✅ schema drift detection
- ✅ additive evolution
- ✅ schema fingerprints/history
- ✅ breaking-change rejection reports
- ✅ rejection-event idempotency

### Phase 2D — Medallion Architecture and Lineage

- ✅ deterministic Bronze/Silver/Gold routing
- ✅ safe logical dataset names
- ✅ deterministic transformation execution
- ✅ multi-stage ETL orchestration
- ✅ durable lineage
- ✅ schema/plan fingerprints

### Phase 2E — Agent Runtime Reliability and CI

- ✅ deterministic orchestration tests
- ✅ one-tool-per-turn enforcement
- ✅ bounded ETL tool loop
- ✅ failure-stop routing
- ✅ execution observability
- ✅ GitHub Actions CI

### Phase 2F — Data Quality and Contracts

- ✅ typed deterministic quality rules
- ✅ persisted contracts
- ✅ Silver/Gold quality gates
- ✅ last-known-good preservation
- ✅ agent-facing contract configuration
- ✅ quality-aware lineage/observability

### Phase 2G — PostgreSQL Warehouse Bridge

- ✅ deterministic warehouse writer
- ✅ Bronze → PostgreSQL sync
- ✅ additive physical schema evolution
- ✅ dependency-safe refresh-in-place
- ✅ warehouse metadata
- ✅ warehouse lineage
- ✅ generated Bronze dbt sources

### Phase 2H — dbt Integration

- ✅ dbt project + PostgreSQL adapter
- ✅ dynamic Bronze sources
- ✅ generated Silver models
- ✅ generated Gold marts
- ✅ dbt quality tests
- ✅ bounded dbt execution
- ✅ typed `DBTTransformPlan`
- ✅ deterministic SQL compilation
- ✅ model metadata + fingerprints
- ✅ safe dbt artifact reader
- ✅ dbt lineage
- ✅ dbt observability

### Phase 2I — Governed Warehouse Analytics

- ✅ metadata-only Silver/Gold analytics catalog
- ✅ no sample rows in SQL-generation schema context
- ✅ scope-aware SQL relation/schema allowlisting
- ✅ Bronze/public/system-schema rejection
- ✅ cross-database rejection
- ✅ exact governed catalog snapshot reused for prompting + validation
- ✅ governed Silver/Gold SQL generation
- ✅ read-only PostgreSQL execution
- ✅ structured SQL execution observability
- ✅ SQL observability privacy regression tests
- ✅ full API → Bronze → dbt Silver/Gold → governed analytics E2E

---

## Next Planned Work

### Phase 2J — Incremental Warehouse Processing

The next planned phase extends incremental behavior beyond file-backed Bronze ingestion and into the warehouse/dbt path.

Proposed direction:

```text
2J.1  Typed business-key contracts
2J.2  Incremental PostgreSQL Bronze merge/upsert
2J.3  Warehouse/checkpoint consistency
2J.4  Governed dbt incremental materialization
2J.5  Incremental lineage + observability
2J.6  Two-run incremental E2E validation
```

Target architecture:

```text
External API
      ↓
watermark extraction
      ↓
durable Bronze state
      ↓
validated business key
      ↓
PostgreSQL merge/upsert
      ├── insert new rows
      ├── update changed rows
      └── preserve unchanged rows
      ↓
dbt Silver
      ↓
governed incremental Gold
      ↓
governed SQL analytics
```

The same project principle remains:

> **The LLM may decide which supported incremental workflow is needed. Deterministic code owns key validation, merge semantics, checkpoint durability, physical SQL, and dbt materialization configuration.**

### Later Candidates

- richer semantic/data contracts
- row-level quarantine datasets
- centralized tracing and metrics
- external workflow orchestration
- Docker/container deployment
- richer lineage backends
- distributed dbt execution coordination
- streamed response-size enforcement
- live LLM evaluation
- LLM cost monitoring

---

# License

This project is released under the MIT License.
