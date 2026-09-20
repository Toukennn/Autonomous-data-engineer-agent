# Autonomous Data Engineer Agent

A safety-oriented agentic data engineering system for **API ingestion**, **persistent incremental processing**, **deterministic ETL workflows**, **Medallion architecture**, **PostgreSQL warehousing**, **dbt transformations**, **data-quality contracts**, **lineage**, **runtime observability**, and **governed natural-language SQL analytics**.

The project uses LangGraph to route requests to specialized ETL and SQL agents while keeping sensitive operations under deterministic application control.

> **LLMs decide what should happen. Deterministic tools decide how it happens.**

The LLM may choose a supported workflow and create typed transformation or quality plans, but it does not receive arbitrary Python execution, arbitrary filesystem access, direct checkpoint control, schema-policy control, unrestricted dbt execution, unrestricted database access, or control over warehouse merge keys/materialization settings.

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
Durable Bronze filesystem snapshot
    │
    ├── watermark checkpoint
    ├── business-key contract
    └── dataset fingerprint
    │
    ▼
PostgreSQL bronze.<dataset>
    │
    ├── refresh_in_place       (no business key)
    └── merge_upsert           (business key configured)
    │
    ▼
dbt
 ┌──┴────────────────────┐
 ▼                       ▼
Silver views          Gold marts
                         │
                         ├── table fallback
                         └── governed incremental
    │                       │
    ├──── dbt tests ────────┤
    │                       │
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
- application code controls physical paths, schemas, model names, selectors, credentials, execution boundaries, business-key enforcement, merge semantics, and dbt materialization configuration

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
Durable Bronze filesystem snapshot
    ↓
dbt_bronze_to_silver_tool
    ├─ validate Bronze/checkpoint binding
    ├─ synchronize Bronze → PostgreSQL
    │    ├─ refresh_in_place
    │    └─ merge_upsert
    ├─ refresh governed dbt source metadata
    ├─ create typed DBTTransformPlan
    ├─ deterministically compile dbt SQL
    ├─ propagate safe business-key lineage
    ├─ create Silver view
    ├─ synchronize dbt quality tests
    └─ execute bounded dbt build
    ↓
dbt Silver
    ↓
dbt_silver_to_gold_tool
    ├─ create typed DBTTransformPlan
    ├─ deterministically evaluate incremental safety
    ├─ deterministically compile dbt SQL
    ├─ choose table vs incremental materialization
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
- physical business-key indexes
- warehouse merge SQL
- dbt `materialized`, `unique_key`, or `incremental_strategy`
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

The checkpoint advances only after the required durable writes succeed.

Checkpoint metadata binds state to the source/configuration so one state key cannot silently be reused for a different incremental pipeline.

Retry/merge behavior now has two modes:

```text
no business-key contract
    → exact-row deduplication

business-key contract configured
    → incoming row replaces historical row with the same key
```

The keyed behavior was added in Phase 2J while preserving backward compatibility for unkeyed datasets.

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
    warehouse_sync_metadata.json    # after warehouse sync
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

## Dependency-safe synchronization

The warehouse now supports two deterministic synchronization modes.

### No business key: refresh in place

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

### Business key configured: merge/upsert

```text
validate business-key contract
      ↓
validate historical warehouse keys
      ↓
ensure deterministic unique index
      ↓
INSERT ... ON CONFLICT (<key>)
      ↓
update only changed non-key columns
      ↓
COMMIT
```

The merge/upsert path does **not** truncate or drop the table.

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

Phase 2J also makes source registration snapshot-aware: if the durable Bronze file changes after warehouse synchronization, the source registry rejects the stale synchronization metadata instead of advertising the warehouse state as current.

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

Silver metadata may carry forward a deterministically proven business key for downstream incremental decisions.

## Gold marts

Generated Gold models use names such as:

```text
mart_<dataset>
```

and live in:

```text
dbt_dev_gold
```

Gold generation requires an existing governed Silver dbt model and its persisted metadata.

Gold materialization is now application-governed:

```text
safe key-preserving plan
    → incremental

unsafe / no key lineage
    → table
```

The LLM does not control `materialized`, `unique_key`, or `incremental_strategy`.

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
- unrestricted filesystem paths

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

## Governed analytics catalog

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

The catalog contains relation/column metadata only. It does **not** fetch sample rows.

Bronze, `public`, `information_schema`, `pg_catalog`, and unrelated schemas are excluded.

## Scope-aware SQL allowlisting

`utils/sql_safety.py` revalidates the catalog and uses SQLGlot scopes to distinguish physical relations, CTEs, and subqueries.

Governed SQL must be:

- exactly one parsed query
- read-only
- schema-qualified for physical relations
- limited to relations present in the governed catalog
- free of cross-database references
- free of Bronze/public/system-schema access

## SQL execution observability

SQL runs record safe structured events such as:

```text
sql_safety
sql_execution
```

Observability deliberately excludes user questions, generated SQL text, result row values, raw database error messages, and credentials.

## Phase 2I E2E

`phase_2i_e2e.py` exercises the complete API → Bronze → PostgreSQL → dbt Silver/Gold → governed analytics stack using the Open Library public API.

Because Open Library is a live external API, exact row contents and counts can change over time.

Run it with:

```bash
uv run python phase_2i_e2e.py
```

---

# Phase 2J — Incremental Warehouse Processing

Phase 2J extends incremental semantics beyond file-backed ingestion and into the PostgreSQL/dbt path while preserving the project rule that deterministic code owns row identity, durability, merge SQL, and materialization configuration.

Current repository status:

```text
2J.1   Typed business-key contracts               ✅
2J.2   Incremental PostgreSQL Bronze merge/upsert ✅
2J.3   Warehouse/checkpoint consistency           ✅
2J.4   Governed dbt incremental materialization   ✅
2J.5   Incremental lineage + observability        ✅
2J.6A  Business-key-aware durable Bronze merge    ✅
2J.6B  Real two-run PostgreSQL/dbt E2E            ✅
```

## 2J.1 — Typed business-key contracts

Phase 2J introduces typed row-identity contracts through:

```text
models/warehouse_keys.py
utils/business_keys.py
```

A `BusinessKeyContract` supports single-column and composite keys.

Contracts are persisted under:

```text
data/_warehouse_keys/<dataset>.json
```

Key contracts are immutable by default because rebinding a dataset to a different key changes the meaning of row identity.

Deterministic validation requires:

- every key column exists
- key values are non-null
- business-key tuples are unique
- duplicate key-column declarations are rejected
- persisted content matches its SHA-256 fingerprint
- persisted dataset binding matches the requested dataset

Business-key errors expose aggregate diagnostics rather than raw row values.

## 2J.2 — Incremental PostgreSQL Bronze merge/upsert

`PostgresWarehouseLoader` now has two Bronze synchronization paths:

```text
no business key
    → replace_bronze_table()
    → refresh_in_place

business key configured
    → merge_bronze_table()
    → merge_upsert
```

The keyed path:

- revalidates the business-key contract
- validates historical warehouse rows before enabling merge semantics
- creates an application-controlled deterministic unique index
- uses safely quoted Psycopg identifiers
- uses `INSERT ... ON CONFLICT (...) DO UPDATE`
- updates non-key columns only when values are actually distinct
- supports all-key datasets through `DO NOTHING`
- never `TRUNCATE`s or `DROP`s on the merge path
- rolls back on failure

Warehouse-sync metadata records:

```text
load_mode
business_key_configured
business_key_columns
business_key_fingerprint
```

The dbt source registry tolerates these extra metadata fields while keeping the same metadata-version boundary.

## 2J.3 — Warehouse/checkpoint consistency

The project does **not** pretend that filesystem persistence and PostgreSQL share one distributed transaction.

Instead, it uses explicit snapshot identity.

`utils/data_layers.py` provides a SHA-256 fingerprint of the exact durable Bronze file.

The Bronze checkpoint stores that fingerprint:

```text
checkpoint cursor
      │
      └── dataset_fingerprint
```

Warehouse synchronization then verifies:

```text
committed checkpoint
      ↓
expected Bronze fingerprint
      ↓
actual durable Bronze file
      ↓
warehouse sync
      ↓
re-check Bronze fingerprint
      ↓
warehouse_sync_metadata
```

If the Bronze file changes while the warehouse is synchronizing, PostgreSQL may already contain the snapshot that was read, but successful synchronization metadata is **not** advanced. A retry safely replays the synchronization.

`DBTSourceRegistry` also rejects a warehouse source when the current Bronze fingerprint no longer matches the fingerprint from the last successful warehouse synchronization.

This prevents stale PostgreSQL state from being advertised as current Bronze state.

## 2J.4 — Governed dbt incremental materialization

Incremental dbt behavior is decided by deterministic key-lineage analysis in:

```text
utils/dbt_incremental.py
```

The LLM supplies only a validated `DBTTransformPlan`.

Deterministic code evaluates whether the transformation preserves one stable output row per business key.

Examples of key-preserving behavior include:

- identity transformations
- projection that keeps all key columns
- deterministic key renaming
- non-key casting
- non-key string transformations
- non-key missing-value filling

Operations that disable incremental eligibility include:

- filtering
- aggregation
- dropping any business-key column
- casting a business-key column
- string-transforming a business-key column
- otherwise mutating row identity

Why filters are conservatively rejected:

```text
run 1: row satisfies filter → written to Gold
run 2: same key no longer satisfies filter
```

If the model only processed the new filtered result, the old Gold row could remain stale. The safe fallback is therefore a full Gold table rebuild.

Silver remains a view but persists safe key lineage in generated model metadata.

Gold uses:

```text
safe key lineage
    → materialized="incremental"
    → application-controlled unique_key
    → incremental_strategy="delete+insert"

unsafe / no key lineage
    → normal table materialization
```

The LLM cannot choose any of these dbt configuration values.

## 2J.5 — Incremental lineage and observability

Warehouse lineage now records the actual load mode instead of assuming every sync is a refresh.

Safe warehouse lineage metadata includes:

```text
load_mode
row_count
column_count
source_dataset_fingerprint
checkpoint_bound
business_key.configured
business_key.column_count
business_key.contract_fingerprint
```

dbt build lineage records:

```text
materialization
incremental.eligible
incremental.key_column_count
```

ETL execution observability also carries safe aggregate fields such as:

```text
materialization
incremental_eligible
incremental_key_column_count
```

Raw business-key values, row contents, compiled SQL, credentials, and unrestricted tool payloads are not persisted in these observability records.

## 2J.6A — Business-key-aware durable Bronze merge

The file-backed Bronze merge now aligns with warehouse row identity.

Without a business-key contract:

```text
existing rows + incoming rows
      ↓
exact-row deduplication
```

With a business-key contract:

```text
existing Bronze
      +
incoming batch
      ↓
validate incoming key uniqueness
      ↓
drop duplicates by business key
keep="last"
      ↓
incoming version wins
      ↓
validate final keyed snapshot
```

This supports a true update such as:

```text
run 1: id=1, name=Alice
run 2: id=1, name=Alicia
```

without leaving two `id=1` rows in durable Bronze.

Duplicate business keys **inside one incoming batch** are rejected rather than silently picking one, because the batch has no trusted row-version ordering contract.

Regression coverage includes:

- changed-key replacement
- keyed retry idempotency
- duplicate incoming-key rejection
- no-key backward compatibility

## 2J.6B — Final two-run E2E

The remaining final validation should prove this complete two-run scenario using real PostgreSQL and real dbt while controlling the external API batches deterministically:

```text
RUN 1
id=1  Alice    amount=10  updated_at=100
id=2  Bob      amount=20  updated_at=100

RUN 2
id=1  Alicia   amount=15  updated_at=200   ← UPDATE
id=3  Charlie  amount=30  updated_at=200   ← INSERT
```

Expected final state:

```text
1  Alicia   15  200
2  Bob      20  100
3  Charlie  30  200
```

The final E2E should verify:

- run 2 receives run 1's watermark
- checkpoint advances to the second watermark
- durable Bronze contains exactly one row per business key
- checkpoint fingerprint matches the final Bronze snapshot
- PostgreSQL Bronze matches the durable Bronze snapshot
- both warehouse syncs use `merge_upsert`
- Silver remains a view
- Gold is materialized incrementally when its plan preserves the key
- incremental key lineage survives into Gold metadata
- Gold lineage records incremental materialization
- the governed SQL validator accepts the final Gold relation
- read-only governed SQL returns the expected final three-row state

A source watermark must represent updates—such as `updated_at` or a change version—not merely the business key itself. Otherwise an update to an older key may never be fetched.

---

# Current Durability Model

## Incremental Bronze ingestion

```text
load checkpoint
      ↓
extract API data using watermark
      ↓
normalize records
      ↓
load optional business-key contract
      ↓
validate source schema transition
      ↓
merge with durable Bronze
      │
      ├── no key → exact-row retry deduplication
      │
      └── key    → incoming row replaces same-key history
      ↓
validate keyed candidate when applicable
      ↓
atomic Bronze dataset save
      ↓
compute exact dataset SHA-256
      ↓
schema history persistence
      ↓
atomic extraction metadata save
      ↓
lineage persistence
      ↓
checkpoint commit bound to dataset fingerprint
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
validate checkpoint ↔ Bronze fingerprint binding
      ↓
warehouse synchronization
      │
      ├── no business key
      │       ↓
      │   refresh_in_place
      │
      └── business key
              ↓
          merge_upsert
      ↓
re-check Bronze fingerprint
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
deterministic key-lineage analysis
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

data/_warehouse_keys/
    → immutable typed business-key contracts

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
    → validated generated model metadata, plan fingerprints,
      materialization metadata, incremental key lineage

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
└── mart_<dataset>               # dbt table or governed incremental table
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
├── app/
│   ├── __init__.py
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
│   │   ├── sources/
│   │   ├── staging/
│   │   └── marts/
│   └── tests/
│       └── generic/
│           └── quality_contract_tests.sql
│
├── models/
│   ├── data_quality.py
│   ├── schema.py
│   └── warehouse_keys.py
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
│   ├── incremental_state.py
│   ├── lineage.py
│   ├── llm_pick.py
│   ├── schema_evolution.py
│   ├── sql_safety.py
│   └── warehouse.py
│
├── tests/
│   ├── test_api_client.py
│   ├── test_business_keys.py
│   ├── test_data_layers.py
│   ├── test_data_quality.py
│   ├── test_data_quality_contracts.py
│   ├── test_database.py
│   ├── test_dbt_artifacts.py
│   ├── test_dbt_execution.py
│   ├── test_dbt_incremental.py
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
uv run uvicorn app.api:app --host 127.0.0.1 --port 8000 --workers 1
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

# Container Persistence

The app stores durable runtime state in one volume mounted at `/app/runtime`. Its existing `/app/data` and generated dbt paths are symlinks into that volume. Compose mounts the `agent_runtime` volume there.

On Railway, mount the app volume at `/app/runtime` and set `RAILWAY_RUN_UID=0` on the service. Railway mounts volumes as root; the container entrypoint prepares the volume and then starts Uvicorn as UID/GID 10001. Keep `PERSIST_ROOT=/app/runtime` so it matches the image symlinks.

The previous five Compose volumes are not copied into `agent_runtime` automatically. Migrate their contents before recreating the app container if you need existing ETL and dbt state. Keep the old volumes until the new runtime state is verified.

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
- exact Bronze dataset fingerprints
- checkpoint ↔ Bronze snapshot consistency
- stale warehouse/dbt source rejection
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
- typed business-key validation
- single and composite business keys
- immutable business-key contract persistence
- business-key contract fingerprint validation
- keyed durable Bronze replacement
- keyed retry idempotency
- duplicate incoming-key rejection
- PostgreSQL Bronze merge/upsert
- no-TRUNCATE/no-DROP merge regression
- dynamic dbt source generation
- generated Silver models
- generated Gold marts
- deterministic `DBTTransformPlan` compilation
- deterministic incremental key-lineage analysis
- safe/unsafe incremental materialization decisions
- composite dbt `unique_key` generation
- table fallback for unsafe/no-key Gold plans
- SQLGlot validation of generated dbt SQL
- dbt model metadata fingerprints
- dbt quality synchronization
- bounded dbt execution
- dbt artifact parsing
- dbt build → lineage linkage
- dbt build → observability linkage
- warehouse merge mode lineage
- incremental materialization lineage
- incremental observability privacy
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
- business-key validation
- business-key contract fingerprints
- physical business-key indexes
- warehouse merge/upsert SQL
- PostgreSQL credentials
- arbitrary warehouse schemas
- destructive Bronze table replacement
- dbt project/profile paths
- arbitrary dbt selectors
- arbitrary dbt CLI arguments
- arbitrary dbt SQL/Jinja generation
- dbt `materialized` configuration
- dbt `unique_key`
- dbt incremental strategy
- incremental eligibility decisions
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
LLM
  ↓
validated DBTTransformPlan
  ↓
deterministic SQL compiler
  ↓
deterministic incremental-safety decision
  ↓
application-controlled dbt config
  ↓
dbt
```

For analytical SQL:

```text
LLM → governed catalog → SQLGlot AST + relation allowlist → read-only PostgreSQL
```

---

# Current Limitations

- business-key contracts exist as deterministic persisted application state but do not yet have a dedicated agent-facing configuration tool
- the source watermark must capture updates (for example `updated_at` or a change version); using only a monotonically increasing business key cannot discover updates to older keys
- keyed Bronze currently represents the latest snapshot per business key rather than maintaining slowly-changing-dimension history
- explicit source deletions/tombstones are not yet modeled, so disappearance of a source row does not automatically delete it downstream
- governed Gold incremental materialization is correct for key-preserving plans, but the generated query currently reads the complete Silver view rather than using an `is_incremental()` source-side change filter; this is a performance limitation, not a correctness blocker
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
- the final real two-run Phase 2J PostgreSQL/dbt E2E is still pending in the current repository state

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

### Phase 2J — Incremental Warehouse Processing

- ✅ typed immutable business-key contracts
- ✅ single/composite key validation and fingerprints
- ✅ business-key-aware durable Bronze updates
- ✅ backward-compatible exact-row behavior for unkeyed datasets
- ✅ PostgreSQL Bronze `merge_upsert`
- ✅ deterministic unique business-key index
- ✅ checkpoint ↔ Bronze dataset fingerprint binding
- ✅ warehouse synchronization snapshot fingerprints
- ✅ stale dbt source rejection
- ✅ deterministic dbt incremental eligibility analysis
- ✅ Silver key-lineage propagation
- ✅ governed Gold incremental materialization
- ✅ deterministic composite `unique_key` support
- ✅ safe table fallback for filters/aggregations/key mutation
- ✅ incremental warehouse/dbt lineage
- ✅ privacy-preserving incremental observability
- ✅ final real two-run PostgreSQL/dbt E2E validation

---

## Next Planned Work

### Finish Phase 2J validation

Run and persist the final deterministic two-run scenario proving:

```text
update existing business key
+ insert new business key
+ preserve unchanged key
+ advance checkpoint
+ merge into PostgreSQL
+ incrementally build Gold
+ query final state through governed SQL
```

### Later Candidates

- source-side dbt incremental filtering with deterministic change predicates
- explicit deletion/tombstone semantics
- SCD/history-aware business-key processing
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
