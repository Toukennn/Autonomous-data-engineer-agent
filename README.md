# Autonomous Data Engineer Agent

A safety-oriented agentic data engineering system for **API ingestion**, **deterministic ETL workflows**, **Medallion architecture**, **PostgreSQL warehousing**, **dbt transformations**, **data-quality contracts**, **lineage**, **runtime observability**, and **natural-language SQL analytics**.

The project uses LangGraph to route user requests to specialized ETL and SQL agents while keeping sensitive operations under deterministic application control.

> **LLMs decide what should happen. Deterministic tools decide how it happens.**

The LLM may select a supported workflow and create typed transformation or quality plans, but it does not receive arbitrary Python execution, arbitrary filesystem access, direct checkpoint control, schema-policy control, lineage-write control, quality-gate bypass control, unrestricted dbt execution, or unrestricted SQL execution.

---

# Overview

The system contains three main agents:

- **Data Engineer Agent** — routes requests to the correct specialist.
- **ETL Analyst Agent** — orchestrates bounded API → Bronze → Silver → Gold workflows, including both the legacy Pandas/file-backed path and the PostgreSQL/dbt path.
- **SQL Analyst Agent** — converts natural-language questions into PostgreSQL queries and safely executes read-only analytics.

The warehouse-backed dbt path is:

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
                         │                   ▼
                         │              SQL generation
                         │                   │
                         │                   ▼
                         │              SQLGlot AST
                         │              validation
                         │                   │
                         │                   ▼
                         │              read-only
                         │              PostgreSQL
                         │
                         ▼
                    ETL orchestration
                         │
          ┌──────────────┴──────────────┐
          ▼                             ▼
   file-backed path                dbt path
          │                             │
    Bronze → Silver → Gold       Bronze filesystem
                                      ↓
                                 bronze PostgreSQL
                                      ↓
                                   dbt Silver
                                      ↓
                                   dbt Gold
                                      │
                              quality / artifacts
                                      │
                         lineage + execution records
```

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

and delegates execution to the corresponding specialist.

![Data Engineer Graph](data_engineer_graph.png)

The router does not execute ETL or SQL itself.

---

## ETL Agent

The ETL agent is a ReAct-style orchestrator with a deliberately small tool surface.

It currently exposes six tools:

```text
extract_load_tool
bronze_to_silver_tool
silver_to_gold_tool
dbt_bronze_to_silver_tool
dbt_silver_to_gold_tool
configure_quality_contract_tool
```

The agent can therefore choose between two supported Medallion execution paths.

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

- arbitrary input or output filesystem paths
- arbitrary PostgreSQL schemas or physical table names
- direct Bronze → Gold transitions
- unrestricted Python code
- arbitrary SQL or Jinja
- arbitrary dbt selectors or CLI arguments
- dbt project/profile paths
- database credentials
- quality-check bypasses
- direct mutation or weakening of an existing quality contract

For multi-stage requests, execution occurs sequentially so every stage is validated before the next dependent stage begins.

A required tool failure stops the workflow deterministically. The LLM is not allowed to continue to a dependent downstream stage after failure.

![ETL Analyst Graph](etl_analyst_graph.png)

---

## Planner LLM vs Deterministic Executor

Transformation planning and execution are intentionally separated.

### File-backed Transformation Planner

The planner receives the user transformation request plus dataset context and returns a validated Pydantic `TransformPlan`.

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

Trusted Python code in `ETLTools` controls how the plan is executed.

### dbt Transformation Planner

Warehouse-backed Silver and Gold transformations use a separate typed `DBTTransformPlan`.

The planner may choose supported logical operations such as:

```text
select_columns
rename_columns
filter_rows
fill_missing
cast_columns
string_transform
groupby_aggregate
```

The planner does **not** write SQL.

Instead:

```text
User request
    ↓
Planner LLM
    ↓
validated DBTTransformPlan
    ↓
deterministic DBTSQLCompiler
    ↓
validated PostgreSQL/dbt SQL
    ↓
generated dbt model
```

Silver plans do not allow aggregation. Gold plans may use supported aggregation operations.

The dbt compiler owns quoting, literal encoding, relation resolution, column validation, operation order, and SQLGlot validation before generated SQL is written.

### Data-Quality Planner

When a user explicitly requests quality expectations, a dedicated planner creates a validated `DataQualityContract`.

Supported quality rules currently include:

```text
not_null
unique
accepted_values
range
row_count
```

The planner is instructed not to invent quality requirements. Contract identity and version remain application-controlled.

There is no arbitrary `exec(...)`, unrestricted generated Python, unrestricted generated SQL execution, or unrestricted dbt command execution.

---

# Phase 2A — Reliable API Ingestion ✅

Phase 2A moved HTTP behavior out of the agent layer and into a deterministic `APIClient`.

## 2A.1 — Dedicated API Client

`utils/api_client.py` owns API communication and returns an `APIExtractionResult` containing records and metadata.

Important behavior includes:

- top-level JSON arrays
- nested record paths
- relative pagination URLs
- controlled JSON validation
- normalized external API errors
- metadata independent from agent reasoning

## 2A.2 — Retry, Backoff, Rate Limits, and Authentication

The API client supports bounded retries for transient failures such as `429`, `500`, `502`, `503`, and `504`.

It also supports exponential backoff, `Retry-After`, token authentication, configurable auth header/scheme, configurable user agent, and redirect limits.

Authenticated requests must use HTTPS.

## 2A.3 — Bounded Extraction

Extraction is bounded by:

- request timeout
- maximum response bytes
- maximum total bytes across pagination
- maximum pages
- maximum records
- maximum redirects
- pagination-loop detection

## 2A.4 — SSRF and Redirect Hardening

Destination validation rejects unsafe targets including localhost, loopback, private, link-local, unspecified, multicast, and other non-public destinations.

Redirect destinations are validated before being followed, and authenticated cross-origin behavior is restricted.

---

# Phase 2B — Persistent Incremental Ingestion ✅

Phase 2B introduced durable watermark-based ingestion while preserving:

> **Checkpoint state belongs to deterministic code, not the LLM.**

## 2B.1 — Persistent Checkpoint Store

`utils/incremental_state.py` implements `IncrementalStateStore` under `data/_state/`.

The store provides restricted state keys, containment checks, atomic JSON persistence, controlled corrupted-state handling, and UTC timestamps.

## 2B.2 — Watermark-Aware Extraction

Incremental extraction uses:

```text
watermark_param
watermark_field
watermark_value
```

Ownership is intentionally split:

```text
LLM chooses:
    state_key
    watermark_param
    watermark_field

Deterministic code loads/calculates:
    watermark_value
```

The LLM never supplies the previous cursor value.

## 2B.3 — Atomic and Idempotent Persistence

Retry safety currently uses exact-row deduplication. The checkpoint advances only after required durable writes succeed.

## 2B.4 — Agent-Safe Incremental Configuration

Checkpoint metadata binds state to its source and incremental configuration so a state key cannot silently be reused for a different pipeline.

---

# Phase 2C — Schema Evolution ✅

Phase 2C added deterministic schema comparison, safe additive evolution, schema history, and durable breaking-change reports.

The source-ingestion policy is:

```text
same schema                 → ACCEPT
added columns only          → ACCEPT
removed columns             → REJECT
logical type changes        → REJECT
```

The LLM does not decide whether a source schema transition is compatible.

## 2C.1 — Schema Drift Detection

`utils/schema_evolution.py` compares logical schemas and records added columns, removed columns, and type changes.

Pandas dtypes are normalized to `boolean`, `number`, `datetime`, `string`, and `object`.

## 2C.2 — Additive Evolution

New columns are accepted safely. Historical rows receive nulls for newly introduced columns while existing column order is preserved.

## 2C.3 — Schema History and Fingerprints

Each Bronze dataset can maintain `schema_history.json` with stable SHA-256 schema fingerprints and monotonically increasing schema versions.

## 2C.4 — Breaking-Change Rejection

Breaking transitions raise `SchemaEvolutionError` and are persisted to `schema_change_rejections.json`.

Repeated identical breaking transitions use stable rejection fingerprints so duplicate rejection events are avoided.

---

# Phase 2D — Medallion Architecture, Agent Integration, and Lineage ✅

```text
2D.1  Deterministic Bronze layer          ✅
2D.2  Silver transformation layer         ✅
2D.3  Gold curated/output layer           ✅
2D.4  Agent integration + lineage         ✅
```

The original deterministic Medallion architecture is:

```text
External API
    ↓
 Bronze
    ↓
 Silver
    ↓
  Gold
```

## 2D.1 — Deterministic Bronze Layer

`utils/data_layers.py` defines explicit `bronze`, `silver`, and `gold` layers.

The agent chooses logical identifiers such as `orders`, `customers`, and `pokemon`, not physical paths.

Bronze outputs are stored under:

```text
data/bronze/<dataset>/
    extracted_data.<format>
    extraction_metadata.json
    schema_history.json
    schema_change_rejections.json   # when needed
```

If an incremental checkpoint exists but the corresponding Bronze dataset is missing, ingestion is rejected to prevent historical data from being skipped.

## 2D.2 — Silver Transformation Layer

Silver consumes Bronze only.

`_resolve_layer_dataset_file()` resolves exactly one physical dataset file for a logical dataset and rejects missing or ambiguous multi-format states.

Silver outputs are stored under:

```text
data/silver/<dataset>/
    transformed_data.<format>
    transformation_metadata.json
```

## 2D.3 — Gold Curated / Analytics Layer

Gold consumes Silver only.

Gold outputs are stored under:

```text
data/gold/<dataset>/
    curated_data.<format>
    curation_metadata.json
```

Gold is intended for curated analytical outputs, KPIs, business filters, aggregations, and reporting tables.

## 2D.4 — Deterministic Lineage

`utils/lineage.py` implements `LineageStore` under:

```text
data/_lineage/lineage.json
```

Lineage is written by deterministic application code, never directly by the LLM.

The original Medallion events are:

```text
extract
transform
curate
```

Later phases extend lineage with warehouse synchronization and dbt build events.

---

# Phase 2E — Agent Runtime Reliability, Observability, and CI ✅

Phase 2E moved reliability guarantees above the deterministic ETL engine and into the agent runtime itself.

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

A single LLM response may not execute multiple dependent ETL stages at once.

`ETL_MAX_TOOL_CALLS` bounds the number of tool executions in one ETL-agent run.

The default is:

```text
ETL_MAX_TOOL_CALLS=8
```

`utils/execution_observability.py` implements `ExecutionRunStore` under:

```text
data/_runs/
```

Tool events use allowlisted operational metadata. Raw user transformation prompts, raw quality requirements, and raw API URLs are deliberately excluded from execution logs.

`.github/workflows/ci.yml` runs Ruff, pytest, and package build checks on pushes to `main` and pull requests targeting `main`.

---

# Phase 2F — Data Quality, Dataset Contracts, and Quality Governance ✅

```text
2F.1  Deterministic quality-rule engine        ✅
2F.2  Persisted dataset quality contracts      ✅
2F.3  Silver / Gold quality gates              ✅
2F.4  Agent integration + quality reporting    ✅
2F.5  Quality observability + lineage linkage  ✅
```

The core principle is:

> **The LLM may describe what quality is expected. Deterministic code decides whether the data passes.**

Supported rules are:

```text
not_null
unique
accepted_values
range
row_count
```

Contracts are stored under:

```text
data/_contracts/<layer>/<dataset>.json
```

File-backed Silver and Gold evaluate candidate DataFrames before durable replacement. Failed quality gates preserve the last known-good output.

The agent exposes `configure_quality_contract_tool` only when the user explicitly specifies quality expectations.

Phase 2H later synchronizes the same contract model into dbt tests for warehouse-backed Silver and Gold models.

---

# Phase 2G — PostgreSQL Warehouse Bridge ✅

Phase 2G introduced the deterministic bridge between file-backed Bronze ingestion and warehouse-backed dbt execution.

```text
2G.1  Deterministic PostgreSQL writer       ✅
2G.2  Bronze dataset → PostgreSQL bridge    ✅
2G.3  Warehouse metadata + lineage          ✅
```

The resulting boundary is:

```text
External API
    ↓
deterministic Bronze ingestion
    ↓
data/bronze/<dataset>/
    ↓
PostgresWarehouseLoader
    ↓
bronze.<dataset>
```

## 2G.1 — Deterministic PostgreSQL Writer

`utils/warehouse.py` implements `PostgresWarehouseLoader`.

Important controls include:

- fixed application-controlled Bronze schema
- logical dataset-name validation
- PostgreSQL 63-byte identifier guards
- quoted identifiers via Psycopg
- deterministic Pandas → PostgreSQL type mapping
- transaction-based writes
- rollback on failure
- normalized warehouse exceptions

The LLM never supplies a physical PostgreSQL schema or arbitrary table identifier.

## 2G.2 — Bronze Dataset → PostgreSQL

`ETLTools.load_bronze_to_warehouse()`:

1. validates the logical dataset name
2. resolves the application-controlled Bronze file
3. loads the persisted Bronze DataFrame
4. computes schema metadata/fingerprints
5. writes the dataset into `bronze.<dataset>`
6. persists warehouse synchronization metadata

Warehouse connectivity is lazy, so constructing `ETLTools` does not require database connectivity when the current operation does not need PostgreSQL.

## 2G.3 — Dependency-Safe In-Place Refresh

The original warehouse bridge used drop-and-recreate semantics. Once dbt views depended on Bronze tables, that would break persistent dependencies.

The refresh strategy was therefore hardened to preserve relation identity:

```text
existing bronze table
      ↓
inspect physical columns
      ↓
add allowed new columns
      ↓
TRUNCATE in transaction
      ↓
INSERT refreshed rows
      ↓
COMMIT
```

The loader does **not** use `DROP TABLE ... CASCADE`.

This allows an existing relation such as:

```text
bronze.pokemon
      ↑
dbt_dev_silver.stg_pokemon
```

to survive subsequent Bronze refreshes.

The warehouse refresh follows the same additive-only schema philosophy as source schema evolution:

- newly added columns may be added to PostgreSQL
- destructive column removal is rejected
- unsafe physical type mutation is rejected

Warehouse metadata records:

```text
load_mode = refresh_in_place
```

rather than destructive replacement semantics.

## Warehouse Synchronization Metadata and Lineage

Successful Bronze warehouse synchronization persists:

```text
data/bronze/<dataset>/warehouse_sync_metadata.json
```

The ordering is:

```text
PostgreSQL commit
      ↓
warehouse_sync_metadata.json
      ↓
refresh generated dbt Bronze sources
      ↓
warehouse_sync lineage
```

`LineageStore` supports the additional event:

```text
warehouse_sync
```

The repository also includes `inspect_warehouse.py`, a local helper for listing Bronze/Silver/Gold relations and inspecting sample rows in PostgreSQL.

---

# Phase 2H — dbt Integration ✅

Phase 2H turns the PostgreSQL warehouse bridge into a bounded, typed, agent-controlled dbt transformation system.

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

The implemented dbt architecture is:

```text
External API
    ↓
Python deterministic ingestion
    ↓
Bronze filesystem
    ↓
PostgreSQL bronze schema
    ↓
generated dbt sources
    ↓
DBTTransformPlan
    ↓
deterministic DBTSQLCompiler
    ↓
generated dbt Silver / Gold models
    ↓
dbt build
    ↓
dbt tests
    ↓
manifest.json + run_results.json
    ↓
lineage + execution observability
```

## 2H.1 — dbt Project and PostgreSQL Adapter

The repository contains an application-controlled dbt project under:

```text
dbt/
├── dbt_project.yml
├── profiles.yml
├── models/
└── tests/
```

The PostgreSQL profile is environment-driven.

Runtime settings include:

```env
DBT_TARGET_SCHEMA=dbt_dev
DBT_THREADS=4
```

## 2H.2 — Dynamic Bronze dbt Sources

`utils/dbt_sources.py` implements `DBTSourceRegistry`.

The registry discovers only successfully warehouse-synchronized Bronze datasets and generates:

```text
dbt/models/sources/bronze_sources.yml
```

Source generation is deterministic and application-controlled.

The LLM cannot invent a physical Bronze source or path.

## 2H.3 — Silver dbt Models

`utils/dbt_models.py` implements `DBTSilverModelManager`.

Generated models are written under:

```text
dbt/models/staging/generated/
```

and use application-controlled names such as:

```text
stg_<dataset>
```

With the default target schema, Silver models are materialized as views under:

```text
dbt_dev_silver
```

## 2H.4 — Gold dbt Marts

`DBTGoldModelManager` generates Gold models under:

```text
dbt/models/marts/generated/
```

with names such as:

```text
mart_<dataset>
```

Gold requires a valid existing Silver dbt model plus persisted model metadata.

With the default target schema, Gold relations are materialized as tables under:

```text
dbt_dev_gold
```

## 2H.5 — dbt Tests and Quality Governance

`utils/dbt_quality.py` synchronizes existing `DataQualityContract` objects into dbt tests.

Supported mappings include:

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

This preserves the original governance principle:

> **The LLM may describe the quality requirement. Deterministic code decides the contract and dbt decides pass/fail at execution time.**

## 2H.6 — Bounded dbt Execution

`utils/dbt_execution.py` implements `DBTExecutor`.

The executor owns:

- project directory
- profiles directory
- database environment
- target schema
- thread count
- model-file validation
- application-controlled selectors
- execution locking
- `dbtRunner` invocation
- exception normalization

Silver uses an exact model selector.

Gold uses an ancestor-inclusive selector such as:

```text
+mart_orders
```

The LLM cannot supply arbitrary dbt CLI arguments or selectors.

## 2H.7 — Typed dbt Planning and Model Metadata

### DBTTransformPlan

`models/schema.py` defines a dbt-specific typed transformation plan.

The LLM chooses only supported operations. It does not generate arbitrary SQL, Jinja, shell commands, filesystem paths, profiles, selectors, or credentials.

### Deterministic SQL Compiler

`utils/dbt_sql.py` implements `DBTSQLCompiler`.

The compiler validates:

- input/output columns
- PostgreSQL identifier limits
- quoted identifiers
- supported literal types
- finite numeric literals
- filter semantics
- casts
- string transforms
- supported aggregations
- Bronze source references
- Silver model references
- operation ordering

Generated SQL is validated with SQLGlot before model persistence.

### Persisted dbt Model Metadata

`utils/dbt_model_metadata.py` persists safe generated-model metadata under:

```text
dbt/generated_metadata/
├── silver/
└── gold/
```

Metadata includes:

- layer
- logical dataset name
- source dataset
- model name
- source model name where applicable
- input columns
- output columns
- canonical plan fingerprint
- validated plan payload

The metadata store verifies fingerprints on load and uses atomic persistence.

### Agent Integration

The ETL agent exposes:

```text
dbt_bronze_to_silver_tool
dbt_silver_to_gold_tool
```

The dbt-specific workflow is:

```text
extract_load_tool
      ↓
dbt_bronze_to_silver_tool
      ↓
dbt_silver_to_gold_tool
```

Lower-level primitives such as:

```text
load_bronze_to_warehouse
create_dbt_silver_model
create_dbt_gold_model
build_dbt_dataset
```

are not exposed directly to the orchestration LLM.

## 2H.8 — dbt Artifacts, Lineage, and Execution Observability

### Safe Artifact Reader

`utils/dbt_artifacts.py` reads a bounded subset of:

```text
dbt/target/manifest.json
dbt/target/run_results.json
```

The reader extracts only safe execution/lineage information such as:

- invocation ID
- target model unique ID
- target model name
- target status
- execution timing
- relation schema/name
- dependencies
- executed model IDs
- dbt test names/status/failure counts

It deliberately excludes:

- compiled SQL
- raw dbt messages
- adapter responses
- credentials
- CLI argument dictionaries
- filesystem paths

Artifact parsing occurs while the shared dbt execution lock is still held, preventing another build in the same process from overwriting `target/` before the current build is correlated.

### dbt Build Lineage

`LineageStore` supports:

```text
dbt_build
```

events.

A successful dbt lineage event can link:

```text
source logical dataset
target logical dataset
dbt model name
dbt unique_id
physical relation
dependencies
invocation_id
plan fingerprint
quality contract fingerprint
dbt test results
execution timings
```

Successful dbt lineage cannot be written for a failed target model.

### dbt Execution Observability

The high-level dbt tools return an internal typed build report.

The LLM receives only safe textual tool output.

The execution store receives allowlisted structured dbt metadata such as:

```text
invocation_id
model
model_unique_id
relation
target_status
target execution time
total elapsed time
executed model count
test counts/status summary
lineage_event_id
plan fingerprint
quality contract state/fingerprint
```

Failed dbt executions also use an explicit safe field allowlist.

Raw SQL, raw dbt output, credentials, paths, and raw transformation prompts are not persisted in execution observability.

---

# Current ETL Durability Model

## Incremental Bronze Ingestion

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

## File-Backed Silver / Gold Promotion

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

## Warehouse-Backed dbt Promotion

```text
Bronze filesystem
      ↓
refresh bronze PostgreSQL relation in place
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
persist generated model + model metadata
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

Execution-observability failure does not invalidate otherwise successful ETL execution because observability is diagnostic rather than part of the data commit contract.

---

# Runtime Persistence and Generated Artifacts

```text
data/_state/
    → Where should incremental ingestion resume?

data/_contracts/
    → What quality rules govern a Silver or Gold dataset?

data/_lineage/
    → Which source/transformation produced this dataset?
      Which quality contract authorized promotion?
      Which warehouse/dbt execution produced the relation?

data/_runs/
    → What happened during this specific ETL-agent execution?

data/bronze/<dataset>/warehouse_sync_metadata.json
    → Which Bronze relation was synchronized into PostgreSQL?

dbt/generated_metadata/
    → Which validated dbt plan/model metadata belongs to each logical dataset?

dbt/target/
    → Ephemeral dbt execution artifacts used for safe lineage/observability parsing
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

The exact Silver/Gold schema prefix is controlled by:

```env
DBT_TARGET_SCHEMA=dbt_dev
```

To inspect the current database locally:

```bash
uv run python inspect_warehouse.py
```

---

# SQL Agent

The SQL agent converts natural-language analytical questions into PostgreSQL queries.

Generated SQL is not trusted directly.

Before execution, SQL is parsed with SQLGlot and inspected as an AST.

The validation layer:

- allows exactly one statement
- permits read-only query expressions
- rejects DML
- rejects DDL
- rejects multi-statement SQL
- rejects invalid SQL
- inspects nested operations and CTEs for hidden writes

Database execution adds another safety layer:

```text
Generated SQL
      │
      ▼
SQLGlot AST validation
      │
      ▼
Read-only PostgreSQL transaction
      │
      ├── statement timeout
      ├── result row limit
      └── rollback
      │
      ▼
Analytics result
```

![SQL Analyst Graph](sql_analyst_graph.png)

The current SQL Analyst is still separate from the new governed dbt Silver/Gold catalog. Connecting it safely to application-approved warehouse relations is the next planned phase.

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
│   ├── test_dbt_artifacts.py
│   ├── test_dbt_execution.py
│   ├── test_dbt_models.py
│   ├── test_dbt_project.py
│   ├── test_dbt_quality.py
│   ├── test_dbt_sources.py
│   ├── test_dbt_sql.py
│   ├── test_warehouse.py
│   └── ...
│
├── inspect_warehouse.py
├── main.py
├── pyproject.toml
└── uv.lock
```

---

# Tech Stack

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

Important runtime controls include:

```env
ETL_MAX_TOOL_CALLS=8
DBT_TARGET_SCHEMA=dbt_dev
DBT_THREADS=4
```

`ETL_MAX_TOOL_CALLS` bounds the number of ETL tool executions in one agent run.

`DBT_TARGET_SCHEMA` controls the dbt target-schema prefix.

`DBT_THREADS` is validated and bounded before dbt execution.

---

# Running the System

Run the top-level router:

```bash
uv run python main.py
```

Or individual agents:

```bash
uv run python -m agents.data_engineer
uv run python -m agents.etl_analyst
uv run python -m agents.sql_analyst
```

Inspect warehouse contents:

```bash
uv run python inspect_warehouse.py
```

---

# Testing

Important coverage includes:

- API destination validation and SSRF protection
- pagination, retries, limits, and HTTP failure normalization
- watermark-based incremental extraction
- checkpoint durability and source/config binding
- schema drift classification and additive evolution
- breaking-schema rejection reports
- deterministic transformation plans
- deterministic data-quality rules
- multi-stage agent orchestration
- failure-stop routing
- Bronze → PostgreSQL warehouse loading
- PostgreSQL identifier safety
- dependency-safe in-place Bronze refresh
- dynamic dbt Bronze source generation
- Silver dbt model generation
- Gold dbt mart generation
- deterministic `DBTTransformPlan` compilation
- SQLGlot validation of generated dbt SQL
- dbt model metadata persistence and fingerprint validation
- dbt quality-contract synchronization
- bounded dbt selectors and execution
- environment restoration after dbt execution
- dbt artifact parsing
- dbt build → lineage linkage
- dbt build → execution-observability linkage
- exclusion of compiled SQL/credentials/raw prompts from dbt observability
- SQL AST safety and read-only database execution

Run all tests:

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
- Bronze/Silver/Gold physical locations
- API authentication tokens
- checkpoint cursor values
- checkpoint persistence timing
- source-schema compatibility decisions
- schema-rejection policy
- PostgreSQL credentials
- arbitrary warehouse schemas
- arbitrary warehouse table names
- destructive Bronze table refresh behavior
- dbt project/profile paths
- arbitrary dbt selectors
- arbitrary dbt CLI arguments
- arbitrary generated dbt SQL
- direct dbt artifact contents
- lineage file contents
- direct Bronze → Gold transitions
- an unlimited ETL tool loop
- continuation after a failed required tool
- deterministic quality pass/fail decisions
- direct quality-contract file paths
- quality-contract fingerprints
- replacement or weakening of an existing different quality contract
- quality-check bypasses
- successful lineage creation for failed dbt model builds

For dbt transformations, the LLM produces a validated `DBTTransformPlan`; deterministic application code compiles and executes it.

For analytical SQL, SQLGlot AST validation and read-only PostgreSQL execution remain independent deterministic safety layers.

---

# Current Limitations

- incremental retry idempotency still uses exact-row equality rather than business-key upserts
- breaking source schema changes are rejected instead of automatically migrated
- optional fields disappearing from an entire batch may appear as schema removal
- response-size limits are not yet enforced while streaming the HTTP body
- data-quality rules are currently limited to `not_null`, `unique`, `accepted_values`, `range`, and `row_count`
- file-backed Pandas Silver/Gold and warehouse-backed dbt Silver/Gold currently coexist as two supported execution paths
- Bronze warehouse refresh is full-table refresh-in-place, not business-key incremental warehouse merging
- dbt model generation currently uses a bounded typed operation set rather than unrestricted SQL modeling
- generated model metadata is file-backed
- lineage uses a single JSON history and is not designed for highly concurrent distributed writers
- execution observability is local file-based rather than backed by centralized tracing/metrics
- dbt execution uses an in-process lock; distributed execution coordination is not yet implemented
- quality rejections preserve aggregate diagnostics but do not provide row-level quarantine datasets
- the SQL Analyst is not yet governed against an explicit Silver/Gold dbt catalog
- broader live-LLM evaluation and cost monitoring remain future work

---

# Roadmap

## Completed

### Phase 2A — Reliable API Ingestion

- ✅ dedicated `APIClient`
- ✅ pagination / retries / rate-limit handling
- ✅ authenticated APIs
- ✅ extraction limits
- ✅ SSRF and redirect hardening

### Phase 2B — Incremental Ingestion

- ✅ persistent checkpoints
- ✅ watermark-based extraction
- ✅ atomic persistence
- ✅ retry idempotency
- ✅ agent-safe incremental configuration
- ✅ checkpoint/source binding

### Phase 2C — Schema Evolution

- ✅ schema drift detection
- ✅ additive schema evolution
- ✅ schema fingerprints and history
- ✅ breaking-change rejection reports
- ✅ rejection-event idempotency

### Phase 2D — Medallion Architecture and Lineage

- ✅ deterministic DataLayer routing
- ✅ safe logical dataset names
- ✅ Bronze ingestion
- ✅ Silver transformations
- ✅ Gold analytics outputs
- ✅ planner / executor separation
- ✅ Medallion agent tools
- ✅ multi-stage ETL orchestration
- ✅ deterministic lineage
- ✅ schema / plan fingerprints
- ✅ lineage-before-checkpoint durability

### Phase 2E — Agent Runtime Reliability and CI

- ✅ deterministic ETL-agent graph tests
- ✅ active safe-tool surface tests
- ✅ one-tool-per-turn enforcement
- ✅ configurable ETL tool-call budget
- ✅ deterministic failure-stop routing
- ✅ terminal success/failure run states
- ✅ structured `_runs/` execution observability
- ✅ event timing and allowlisted metadata
- ✅ raw prompt / raw tool-argument minimization
- ✅ GitHub Actions CI

### Phase 2F — Data Quality and Dataset Contracts

- ✅ typed deterministic quality-rule engine
- ✅ persisted dataset-specific quality contracts
- ✅ stable contract fingerprints
- ✅ Silver and Gold quality promotion gates
- ✅ last-known-good output preservation
- ✅ aggregate quality rejection reports
- ✅ agent-facing quality-contract configuration
- ✅ quality-aware lineage and observability
- ✅ no quality bypass or contract weakening through the agent

### Phase 2G — PostgreSQL Warehouse Bridge

- ✅ deterministic `PostgresWarehouseLoader`
- ✅ application-controlled `bronze` schema
- ✅ safe logical table naming and identifier limits
- ✅ Bronze dataset → PostgreSQL synchronization
- ✅ warehouse synchronization metadata
- ✅ `warehouse_sync` lineage
- ✅ dynamic dbt source refresh after warehouse commit
- ✅ dependency-safe in-place Bronze refresh
- ✅ additive physical-column evolution
- ✅ no `DROP ... CASCADE` refresh behavior

### Phase 2H — dbt Integration

- ✅ dbt project + PostgreSQL adapter
- ✅ dynamic Bronze source registry
- ✅ generated Silver dbt models
- ✅ generated Gold dbt marts
- ✅ dbt quality tests from existing contracts
- ✅ bounded application-controlled dbt execution
- ✅ typed `DBTTransformPlan`
- ✅ deterministic PostgreSQL/dbt SQL compiler
- ✅ persisted model metadata + plan fingerprints
- ✅ dbt-specific planner/agent workflow integration
- ✅ safe manifest/run-results artifact reader
- ✅ artifact-verified `dbt_build` lineage
- ✅ dbt execution observability
- ✅ safe exclusion of compiled SQL, credentials, paths, and raw prompts

---

## Next Planned Work

### Phase 2I — Governed Warehouse Analytics

Connect the SQL Analyst to the warehouse-backed Medallion outputs without giving the LLM arbitrary database access.

Planned direction:

- application-controlled Silver/Gold analytics catalog
- no raw sample-row values in LLM schema context
- deterministic SQL relation/schema allowlisting
- reject Bronze, `public`, system catalogs, nonexistent relations, and unsafe relation references
- expose governed dbt Silver/Gold metadata to SQL generation
- add SQL execution observability
- run an end-to-end API → Bronze → dbt Silver/Gold → analytical question workflow

### Later Candidates

- configurable business-key warehouse upserts
- richer semantic contracts and dataset metadata
- external workflow orchestration
- Docker/containerized deployment
- richer lineage backends
- centralized tracing / metrics
- distributed dbt execution coordination
- live LLM evaluation
- LLM cost monitoring
- streamed response-size enforcement
- row-level quarantine datasets

---

# License

This project is released under the MIT License.
