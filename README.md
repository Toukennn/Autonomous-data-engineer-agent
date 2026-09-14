# Autonomous Data Engineer Agent

A safety-oriented agentic data engineering system for **API ingestion**, **deterministic ETL workflows**, **Medallion data architecture**, **lineage tracking**, and **natural-language SQL analytics**.

The project uses LangGraph to route user requests to specialized ETL and SQL agents while keeping sensitive operations under deterministic application control.

The core design principle is:

> **LLMs decide what should happen. Deterministic tools decide how it happens.**

The LLM may decide which supported workflow should run and may create a typed transformation plan, but it does not receive arbitrary Python execution, arbitrary filesystem access, direct checkpoint control, schema-policy control, lineage-write control, or unrestricted SQL execution.

---

## Overview

The system currently contains three main agents:

- **Data Engineer Agent** — routes each user request to the ETL or SQL specialist.
- **ETL Analyst Agent** — orchestrates API → Bronze → Silver → Gold workflows using bounded tools.
- **SQL Analyst Agent** — converts natural-language questions into PostgreSQL queries and safely executes read-only analytics.

The ETL path now follows a deterministic Medallion architecture:

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
              ┌──────────┼──────────┐
              ▼          ▼          ▼
            Extract     Clean      Curate
              │          │          │
              ▼          ▼          ▼
           BRONZE      SILVER      GOLD
              │          │          │
              └──── deterministic ─┘
                       ETLTools
                         │
                         ▼
                     lineage
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

and delegates the task to the correct specialist.

![Data Engineer Graph](data_engineer_graph.png)

The router does not execute ETL or SQL itself. It only delegates the user request.

---

## ETL Agent

The ETL agent is a ReAct-style orchestrator with a deliberately small tool surface.

It currently exposes only:

```text
extract_load_tool
bronze_to_silver_tool
silver_to_gold_tool
```

The generic agent-facing arbitrary-path transformation tool was removed from the active toolkit.

This means the agent can choose only valid logical transitions:

```text
External API → Bronze
Bronze       → Silver
Silver       → Gold
```

It cannot directly choose:

```text
arbitrary input path
arbitrary output path
arbitrary target layer
Bronze → Gold
unrestricted Python code
```

The ETL system prompt also enforces dependency ordering for multi-stage requests.

For example, if the user asks to extract, clean, and aggregate data in one prompt, the ETL agent can loop through multiple tool calls:

```text
LLM
 │
 ├── extract_load_tool
 │        ↓
 │      Bronze
 │
 ├── bronze_to_silver_tool
 │        ↓
 │      Silver
 │
 └── silver_to_gold_tool
          ↓
         Gold
```

After every tool result, control returns to the ETL LLM so it can decide whether another valid stage is required or whether the workflow is complete.

---

## Planner LLM vs Deterministic Executor

Transformations are split into two responsibilities.

### Planner LLM

The planner receives:

```text
user transformation request
+
dataset context
```

and produces a structured Pydantic `TransformPlan`.

The planner is explicitly instructed not to:

- write Python code
- write shell commands
- perform filesystem operations
- invent column names
- reference columns that do not exist in dataset context

It may create plans containing supported operations such as:

- select columns
- drop columns
- rename columns
- filter rows
- drop duplicates
- sort values
- fill missing values
- cast columns
- string transformations
- grouped aggregations

### Deterministic Executor

`ETLTools.apply_transform_plan()` executes the validated plan using trusted Pandas implementations.

```text
User request
     │
     ▼
Planner LLM
     │
     ▼
Validated TransformPlan
     │
     ▼
ETLTools
     │
     ▼
Deterministic Pandas operations
```

There is no arbitrary:

```python
exec(...)
```

or unrestricted generated Python execution.

The planner logic is shared by both Bronze → Silver and Silver → Gold workflows.

---

# Phase 2A — Reliable API Ingestion ✅

Phase 2A moved HTTP behavior out of the agent/tool layer and into a dedicated deterministic `APIClient`.

## 2A.1 — Dedicated API Client

`utils/api_client.py` owns API communication and returns an `APIExtractionResult` containing:

```text
records
metadata
```

Important behavior includes:

- top-level JSON array support
- nested record-path support
- relative pagination URLs
- controlled JSON validation
- normalized external API errors
- metadata independent from agent reasoning

---

## 2A.2 — Retry, Backoff, Rate Limits, and Authentication

The API client implements bounded retry behavior for transient failures such as:

```text
429
500
502
503
504
```

It also supports:

- exponential retry backoff
- `Retry-After` handling through the retry policy
- optional token authentication
- configurable auth header and scheme
- configurable user agent
- redirect limits

Authenticated calls must use HTTPS.

Credentials are loaded from application settings and are never supplied as free-form LLM output.

---

## 2A.3 — Bounded Extraction

API extraction is bounded by configured limits including:

- request timeout
- maximum response bytes
- maximum total bytes across pagination
- maximum pages
- maximum records
- maximum redirects
- pagination loop detection

Extraction metadata records values such as:

```text
pages_fetched
records_extracted
bytes_downloaded
```

---

## 2A.4 — SSRF and Redirect Hardening

Before a request is made, the destination is validated.

Unsafe destinations such as the following are rejected:

- localhost
- loopback addresses
- private network addresses
- link-local addresses
- unspecified addresses
- multicast addresses
- other non-public destinations

Redirect destinations are validated before being followed.

Authenticated cross-origin flows are restricted to reduce credential-leak risk.

---

# Phase 2B — Persistent Incremental Ingestion ✅

Phase 2B added durable watermark-based ingestion while preserving the rule:

> **Checkpoint state belongs to deterministic code, not the LLM.**

## 2B.1 — Persistent Checkpoint Store

`utils/incremental_state.py` implements `IncrementalStateStore`.

Checkpoints are stored under:

```text
data/_state/
```

Important protections include:

- restricted state-key format
- path-containment checks
- atomic JSON persistence
- controlled handling of corrupted state
- UTC update timestamps

A checkpoint stores values such as:

```text
version
state_key
cursor_value
updated_at
metadata
```

---

## 2B.2 — Watermark-Aware API Extraction

Incremental extraction uses:

```text
watermark_param
watermark_field
watermark_value
```

The ownership split is intentional:

```text
LLM chooses:
    state_key
    watermark_param
    watermark_field

Deterministic code loads/calculates:
    watermark_value
```

The previous cursor is never exposed as an LLM-controlled argument.

The API client also rejects:

- incomplete incremental configuration
- missing watermark fields
- incompatible watermark types
- watermark regression

---

## 2B.3 — Atomic and Idempotent Persistence

Incremental writes follow a transaction-like order.

Before Phase 2D lineage was added, the persistence contract was:

```text
load checkpoint
      ↓
extract records
      ↓
merge
      ↓
atomic dataset save
      ↓
schema history
      ↓
extraction metadata
      ↓
checkpoint
```

Retry safety currently uses exact-row deduplication.

The project intentionally does not yet implement business-key upsert policies such as SCD Type 2.

---

## 2B.4 — Agent-Safe Incremental Configuration

The ETL extraction tool exposes only:

```text
state_key
watermark_param
watermark_field
```

It does not expose `watermark_value`.

Checkpoint metadata also binds the state to the expected source and incremental configuration so the same key cannot silently be reused for a different pipeline.

---

# Phase 2C — Schema Evolution ✅

Phase 2C added deterministic schema comparison, safe additive evolution, schema history, and durable breaking-change rejection reports.

The current source-ingestion policy is:

```text
same schema                 → ACCEPT
added columns only          → ACCEPT
removed columns             → REJECT
logical type changes        → REJECT
```

The LLM does not decide whether a source schema transition is compatible.

---

## 2C.1 — Schema Drift Detection

`utils/schema_evolution.py` contains deterministic schema comparison logic.

`SchemaDiff` records:

```text
added_columns
removed_columns
type_changes
```

and exposes properties such as:

```text
has_changes
is_additive_only
is_breaking
```

Pandas dtypes are mapped into a smaller logical type model:

```text
boolean
number
datetime
string
object
```

Integer and floating-point values are both treated as `number`, avoiding false schema breaks for ordinary numeric widening.

---

## 2C.2 — Additive Evolution

If a new API batch adds columns without removing or changing existing columns, the durable dataset evolves safely.

Historical rows receive null values for the new columns.

Existing column order is preserved and new columns are appended deterministically.

---

## 2C.3 — Schema History and Fingerprints

Logical schemas are fingerprinted with SHA-256.

Each Bronze dataset can persist:

```text
schema_history.json
```

with information including:

- schema version
- schema fingerprint
- logical schema
- timestamp
- source URL

Unchanged schemas do not create fake new versions.

---

## 2C.4 — Breaking-Change Rejection

Breaking schema transitions raise `SchemaEvolutionError`, a structured `DatasetError` subtype.

A durable report is written to:

```text
schema_change_rejections.json
```

Reports include information such as:

- stable rejection ID
- existing and incoming fingerprints
- added columns
- removed columns
- type changes
- complete old/new logical schemas
- previous watermark
- source URL
- policy and rejection reason

A stable transition fingerprint is used so repeated identical schema breaks do not create duplicate rejection events.

Breaking changes are rejected before the durable dataset is replaced.

---

# Phase 2D — Medallion Architecture, Agent Integration, and Lineage ✅

Phase 2D introduced a complete deterministic Bronze / Silver / Gold architecture and connected it to the ETL agent.

The phase was implemented in four major steps:

```text
2D.1  Deterministic Bronze layer          ✅
2D.2  Silver transformation layer         ✅
2D.3  Gold curated/output layer           ✅
2D.4  Agent integration + lineage         ✅
```

The final architecture is:

```text
                       External API
                           │
                           │ extract_load_tool
                           ▼
                    ┌─────────────┐
                    │   BRONZE    │
                    │ source data │
                    └──────┬──────┘
                           │
                           │ bronze_to_silver_tool
                           │ Planner LLM → TransformPlan
                           │ deterministic execution
                           ▼
                    ┌─────────────┐
                    │   SILVER    │
                    │ clean/model │
                    └──────┬──────┘
                           │
                           │ silver_to_gold_tool
                           │ Planner LLM → TransformPlan
                           │ deterministic execution
                           ▼
                    ┌─────────────┐
                    │    GOLD     │
                    │ analytics   │
                    └─────────────┘

Every successful transition also writes deterministic lineage.
```

The layer responsibilities are:

```text
Bronze = source-oriented durable ingestion
Silver = cleaned / standardized / transformed datasets
Gold   = curated analytical or business-facing datasets
```

---

## 2D.1 — Deterministic Bronze Layer

`utils/data_layers.py` introduced the explicit `DataLayer` enum:

```text
bronze
silver
gold
```

It also introduced deterministic logical dataset routing.

### Logical dataset names instead of paths

The agent chooses logical identifiers such as:

```text
orders
customers
pokemon
```

It does not choose paths such as:

```text
data/bronze/orders
../../somewhere
C:\arbitrary\path
```

`validate_dataset_name()` restricts dataset names and rejects path separators, hidden/path-like values, and unsafe names.

`resolve_layer_dataset_directory()` deterministically maps a logical name to its layer location while enforcing path containment.

For example:

```text
dataset_name = orders
layer        = bronze
```

becomes:

```text
data/bronze/orders/
```

without giving the LLM control of the physical path.

### Bronze output layout

API extraction writes to:

```text
data/bronze/<dataset>/
    extracted_data.<csv|json|parquet>
    extraction_metadata.json
    schema_history.json
    schema_change_rejections.json   # only when needed
```

Bronze is source-aligned and durable. It is minimally normalized into tabular form, but transformation/business logic is intentionally deferred to downstream layers.

### Checkpoint / Bronze binding

Incremental checkpoint metadata records the logical dataset, physical output, source configuration, layer, schema version, fingerprint, and schema policy.

A particularly important guard handles the case where a checkpoint exists but the associated Bronze dataset is missing.

The system refuses to continue because using the old cursor without the old durable data could skip historical records.

Conceptually:

```text
checkpoint exists
+
Bronze dataset missing
        ↓
      REJECT
```

rather than:

```text
reuse cursor
↓
skip old data
```

---

## 2D.2 — Silver Transformation Layer

Silver consumes **Bronze only**.

The public deterministic method is:

```text
transform_bronze_to_silver(...)
```

The source is selected by logical dataset name rather than a user-controlled file path.

### Deterministic layer file resolution

`_resolve_layer_dataset_file()` resolves exactly one physical dataset file for a logical layer dataset.

It supports:

```text
csv
json
parquet
```

and rejects two important invalid states:

```text
source dataset missing
multiple physical formats for the same logical dataset
```

The second case matters because a logical dataset should not ambiguously resolve to both, for example:

```text
extracted_data.csv
extracted_data.json
```

### Silver transformation contract

The flow is:

```text
Bronze dataset
      ↓
load deterministic dataset context
      ↓
Planner LLM
      ↓
validated TransformPlan
      ↓
trusted Pandas implementation
      ↓
atomic Silver dataset save
      ↓
transformation metadata
      ↓
lineage event
```

Silver outputs are written to:

```text
data/silver/<dataset>/
    transformed_data.<csv|json|parquet>
    transformation_metadata.json
```

The metadata records details such as:

- source dataset and layer
- target dataset and layer
- source file
- source schema and fingerprint
- output schema and fingerprint
- input/output rows
- input/output columns
- output format
- serialized `TransformPlan`
- UTC transformation timestamp

### Source schema policy vs transformation schema

A subtle but important rule was kept explicit:

```text
Bronze schema = source-controlled
Silver schema = transformation-controlled
```

The additive-only schema-evolution policy protects source ingestion.

It does **not** prevent an intentional Silver transformation from dropping, renaming, casting, or aggregating columns when that change is explicitly represented in a validated `TransformPlan`.

This keeps source-contract safety separate from intentional modeling logic.

### Bronze immutability during Silver creation

Silver transformations read Bronze and write a separate Silver dataset.

Tests verify that producing Silver does not mutate the Bronze source.

---

## 2D.3 — Gold Curated / Analytics Layer

Gold consumes **Silver only**.

The public deterministic method is:

```text
transform_silver_to_gold(...)
```

This enforces the allowed dependency chain:

```text
External → Bronze → Silver → Gold
```

and avoids a direct Bronze → Gold shortcut.

Gold uses the same validated `TransformPlan` mechanism, especially for business-oriented operations such as:

- grouped aggregations
- KPI preparation
- business filters
- reporting tables
- curated analytical outputs

Gold outputs are written to:

```text
data/gold/<dataset>/
    curated_data.<csv|json|parquet>
    curation_metadata.json
```

Gold metadata records:

- Silver source dataset/layer/file
- target Gold dataset/layer
- source and output schemas
- source and output schema fingerprints
- input/output rows
- input/output columns
- output format
- serialized curation plan
- UTC curation timestamp

Silver remains unchanged while Gold is produced.

Tests also reject missing or physically ambiguous Silver datasets.

---

## 2D.4 — Agent Integration

Once the deterministic Bronze, Silver, and Gold APIs were stable, the ETL agent was rewired around logical Medallion transitions.

The active toolset is now:

```text
extract_load_tool
bronze_to_silver_tool
silver_to_gold_tool
```

### No arbitrary transformation paths

The previous generic transformation interface accepted arbitrary input/output path concepts.

The agent-facing API now accepts logical dataset names instead.

For example:

```text
source_dataset_name = orders
target_dataset_name = clean_orders
```

instead of:

```text
input_file_path = data/bronze/orders/extracted_data.csv
output_folder   = data/silver/clean_orders
```

The physical path remains application-controlled.

### Reusable planner

`create_transform_plan()` centralizes the LLM planning logic.

Both Medallion transformations use the same pattern:

```text
logical source dataset
        ↓
get_layer_dataset_context()
        ↓
Planner LLM
        ↓
TransformPlan
        ↓
deterministic ETLTools method
```

`get_layer_dataset_context()` resolves the physical dataset internally, so the planner receives useful schema/context information without the agent choosing storage locations.

### Multi-stage orchestration

The ETL system prompt explicitly understands:

```text
External API
    ↓
Bronze
    ↓
Silver
    ↓
Gold
```

For a request requiring several stages, the agent is instructed to:

1. execute extraction first
2. continue to Bronze → Silver only after extraction succeeds
3. continue to Silver → Gold only after Silver succeeds
4. reuse the correct logical dataset names between stages
5. stop downstream work if an earlier stage fails

A single natural-language request can therefore orchestrate the whole pipeline.

---

## 2D.4 — Deterministic Lineage

Phase 2D also added `utils/lineage.py` and the `LineageStore`.

Lineage is intentionally written by deterministic application code after a successful durable operation.

The LLM does **not** write lineage directly.

Runtime lineage is stored under:

```text
data/_lineage/lineage.json
```

The lineage document is versioned and contains an event history.

Each event contains values such as:

```text
event_id
recorded_at
operation
source
target
metadata
```

Supported lineage operations are currently:

```text
extract
transform
curate
```

### API → Bronze lineage

Extraction lineage records:

- source type = API
- source URL
- target layer = Bronze
- target logical dataset
- target schema fingerprint
- output format

### Bronze → Silver and Silver → Gold lineage

Dataset transitions record:

- source layer
- source logical dataset
- source schema fingerprint
- target layer
- target logical dataset
- target schema fingerprint
- output format
- transformation-plan fingerprint

The full transformation plan remains in the Silver/Gold metadata files.

Lineage stores a stable SHA-256 fingerprint of the plan so the audit graph can identify which plan was used without duplicating the full plan payload in every lineage event.

### Atomic lineage persistence

The lineage document is loaded, extended with one event, written to a temporary file, and atomically replaced.

Corrupted lineage documents are rejected with a controlled `DatasetError`.

### Lineage is part of ingestion durability

For incremental Bronze ingestion the final persistence order is now:

```text
API extraction
      ↓
tabular normalization
      ↓
incremental merge
      ↓
atomic Bronze dataset save
      ↓
schema history persistence
      ↓
atomic extraction metadata save
      ↓
lineage event persistence
      ↓
checkpoint commit
```

The checkpoint remains the final commit point.

This was tested explicitly:

```text
lineage write fails
        ↓
checkpoint DOES NOT advance
```

---

## Phase 2D Testing Details

Important tests include:

- Bronze extraction writes only to Bronze
- Silver requires an existing Bronze dataset
- Gold requires an existing Silver dataset
- Silver creation does not mutate Bronze
- Gold creation does not mutate Silver
- ambiguous physical source formats are rejected
- metadata records source and target layers
- transformation and curation plans are persisted
- full API → Bronze → Silver → Gold lineage integration
- lineage fingerprint stability
- corrupted lineage rejection
- lineage failure prevents checkpoint advancement
- test fixture isolation for `LineageStore`

The pytest fixture rebinds path-bound helpers such as `LineageStore` after changing `data_root`, preventing tests from touching real runtime lineage.

---

# Current ETL Durability Model

The complete successful incremental path is now:

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

For breaking source schema changes, execution exits before the durable dataset is replaced.

For lineage failure, execution exits before checkpoint advancement.

---

# Runtime Data Layout

Runtime data is intentionally ignored by Git.

```text
data/
├── _state/
│   └── <state_key>.json
├── _lineage/
│   └── lineage.json
├── bronze/
│   └── <dataset>/
│       ├── extracted_data.<format>
│       ├── extraction_metadata.json
│       ├── schema_history.json
│       └── schema_change_rejections.json
├── silver/
│   └── <dataset>/
│       ├── transformed_data.<format>
│       └── transformation_metadata.json
└── gold/
    └── <dataset>/
        ├── curated_data.<format>
        └── curation_metadata.json
```

The entire `data/` directory is in `.gitignore` because it contains generated runtime data, state, lineage, and environment-specific metadata.

---

# SQL Agent

The SQL agent converts natural-language analytical questions into PostgreSQL queries.

Generated SQL is **not trusted directly**.

Before reaching PostgreSQL, queries are parsed with SQLGlot and inspected as an AST.

The validation layer:

- allows exactly one statement
- permits read-only query expressions
- rejects DML
- rejects DDL
- rejects multi-statement SQL
- rejects invalid SQL
- inspects nested operations
- inspects CTEs for hidden writes

Database execution adds another layer of protection:

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

---

# Project Structure

```text
Autonomous-data-engineer-agent/
│
├── agents/
│   ├── data_engineer.py
│   ├── etl_analyst.py
│   └── sql_analyst.py
├── config/
│   └── settings.py
├── models/
│   └── schema.py
├── utils/
│   ├── api_client.py
│   ├── data_layers.py
│   ├── database.py
│   ├── etl_tools.py
│   ├── exceptions.py
│   ├── incremental_state.py
│   ├── lineage.py
│   ├── llm_pick.py
│   ├── schema_evolution.py
│   └── sql_safety.py
├── tests/
│   ├── conftest.py
│   ├── test_api_client.py
│   ├── test_data_layers.py
│   ├── test_database.py
│   ├── test_etl_tools.py
│   ├── test_incremental_state.py
│   ├── test_lineage.py
│   ├── test_schema_evolution.py
│   ├── test_settings.py
│   └── test_sql_safety.py
├── .env.example
├── .gitignore
├── .python-version
├── LICENSE
├── README.md
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
- Requests / urllib3
- SQLGlot
- Pydantic / Pydantic Settings
- pytest / Ruff / uv

---

# Installation

```bash
git clone https://github.com/Toukennn/Autonomous-data-engineer-agent.git
cd Autonomous-data-engineer-agent
uv sync --locked
```

Copy `.env.example` to `.env` and configure your LLM/database credentials.

Never commit a real `.env` file.

---

# Running the System

Run the complete Data Engineer router:

```bash
uv run python main.py
```

Or individual agents:

```bash
uv run python -m agents.data_engineer
uv run python -m agents.etl_analyst
uv run python -m agents.sql_analyst
```

---

# Testing

Run all tests:

```bash
uv run pytest -v
```

Run Ruff:

```bash
uv run ruff check .
```

A clean local validation is:

```bash
uv sync --locked
uv run pytest -v
uv run ruff check .
uv build
```

---

# Current Limitations

- incremental retry idempotency currently uses exact-row equality rather than business-key upserts
- breaking source schema changes are rejected rather than auto-migrated
- optional fields disappearing for an entire batch may look like schema removal
- response-size limits are not yet enforced while streaming the body
- dataset contracts do not yet include keys, nullability, semantic types, or business descriptions
- lineage currently uses one file-based JSON history and is not designed for high-concurrency distributed writes
- deterministic agent-runtime orchestration tests and CI belong to the next phase

---

# Roadmap

## Completed

### Phase 2A — Reliable API ingestion

- ✅ APIClient
- ✅ pagination / retries / rate-limit handling
- ✅ authenticated APIs
- ✅ extraction limits
- ✅ SSRF and redirect hardening

### Phase 2B — Incremental ingestion

- ✅ persistent checkpoints
- ✅ watermark-based extraction
- ✅ atomic persistence
- ✅ retry idempotency
- ✅ agent-safe incremental configuration
- ✅ checkpoint/source binding

### Phase 2C — Schema evolution

- ✅ schema drift detection
- ✅ additive schema evolution
- ✅ schema fingerprints and history
- ✅ breaking-change rejection reports
- ✅ rejection-event idempotency

### Phase 2D — Medallion architecture and lineage

- ✅ deterministic DataLayer routing
- ✅ safe logical dataset names
- ✅ Bronze ingestion layer
- ✅ Silver transformation layer
- ✅ Gold analytics layer
- ✅ planner / executor separation
- ✅ Medallion agent tools
- ✅ multi-stage ETL orchestration
- ✅ deterministic lineage
- ✅ plan/schema fingerprints
- ✅ lineage-before-checkpoint durability
- ✅ full Medallion lineage integration tests
- ✅ runtime data excluded from Git

---

## Next Phase — 2E Agent Runtime Reliability & CI

```text
2E.1  Deterministic agent orchestration tests
2E.2  Failure-stop and loop/runtime guards
2E.3  Structured execution observability
2E.4  GitHub Actions CI
```

Later candidates:

- data-quality validation
- business-key upserts
- richer dataset contracts
- dbt integration
- workflow orchestration
- Docker
- tracing
- LLM evaluation
- LLM cost monitoring
- streaming response-size enforcement

---

# License

This project is released under the MIT License.
