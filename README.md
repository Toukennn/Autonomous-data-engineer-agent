# Autonomous Data Engineer Agent

A safety-oriented agentic data engineering system for **API ingestion**, **deterministic ETL workflows**, **Medallion data architecture**, **data-quality contracts**, **lineage**, **runtime observability**, and **natural-language SQL analytics**.

The project uses LangGraph to route user requests to specialized ETL and SQL agents while keeping sensitive operations under deterministic application control.

The core design principle is:

> **LLMs decide what should happen. Deterministic tools decide how it happens.**

The LLM may select a supported workflow and create typed transformation or data-quality plans, but it does not receive arbitrary Python execution, arbitrary filesystem access, direct checkpoint control, schema-policy control, lineage-write control, quality-gate bypass control, or unrestricted SQL execution.

---

# Overview

The system contains three main agents:

- **Data Engineer Agent** — routes requests to the correct specialist.
- **ETL Analyst Agent** — orchestrates bounded API → Bronze → Silver → Gold workflows and explicit data-quality contracts.
- **SQL Analyst Agent** — converts natural-language questions into PostgreSQL queries and safely executes read-only analytics.

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
                         │          │
                         ├─ quality ┤
                         │  gates   │
              └──── deterministic ─┘
                       ETLTools
                         │
         ┌───────────────┼────────────────┐
         ▼               ▼                ▼
    checkpoints       lineage        run records
         │
         ▼
   quality contracts
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

It currently exposes only:

```text
extract_load_tool
bronze_to_silver_tool
silver_to_gold_tool
configure_quality_contract_tool
```

The agent can therefore choose valid logical data transitions plus explicit Silver/Gold quality-contract configuration:

```text
External API → Bronze
Bronze       → Silver
Silver       → Gold

explicit quality requirement
        ↓
Silver / Gold quality contract
```

It cannot directly choose arbitrary input/output paths, arbitrary target layers, direct Bronze → Gold, unrestricted Python code, quality-check bypasses, or direct mutation of an existing quality contract.

For multi-stage requests, execution occurs sequentially so every stage is validated before the next dependent stage begins.

```text
LLM
 │
 ├── optional configure_quality_contract_tool
 │        ↓
 │   persisted quality contract
 │        ↓ success
 │
 ├── extract_load_tool
 │        ↓
 │      Bronze
 │        ↓ success
 │
 ├── bronze_to_silver_tool
 │        ↓
 │   deterministic quality gate
 │        ↓ success
 │      Silver
 │
 └── silver_to_gold_tool
          ↓
     deterministic quality gate
          ↓ success
         Gold
```

A tool failure stops the workflow deterministically. The LLM is not allowed to continue to downstream dependent stages after a failed tool call.

![ETL Analyst Graph](etl_analyst_graph.png)

---

## Planner LLM vs Deterministic Executor

Transformation planning and execution are intentionally separated.

### Transformation Planner LLM

The planner receives the user transformation request plus dataset context and returns a validated Pydantic `TransformPlan`.

The planner is explicitly instructed not to write Python code, write shell commands, perform filesystem operations, invent column names, or reference columns missing from dataset metadata.

Supported operations include column selection/removal, renaming, filtering, duplicate removal, sorting, missing-value handling, casting, string transformations, and grouped aggregations.

### Data-Quality Planner LLM

When a user explicitly requests quality expectations, a dedicated planner creates a validated `DataQualityContract`.

Supported quality rules currently include:

```text
not_null
unique
accepted_values
range
row_count
```

The planner is instructed not to invent quality requirements. Contract identity and version are application-controlled.

### Deterministic Executor

`ETLTools` executes validated plans through trusted Pandas implementations and deterministically enforces configured quality contracts.

```text
User request
     │
     ├──────── transformation request
     │               ↓
     │         Planner LLM
     │               ↓
     │      Validated TransformPlan
     │
     └──────── quality requirement
                     ↓
              Quality Planner
                     ↓
           DataQualityContract
                     │
                     ▼
                  ETLTools
                     │
          ┌──────────┴──────────┐
          ▼                     ▼
 deterministic Pandas      quality engine
    operations                 │
          └──────────┬──────────┘
                     ▼
              durable promotion
```

There is no arbitrary `exec(...)` or unrestricted generated Python execution.

---

# Phase 2A — Reliable API Ingestion ✅

Phase 2A moved HTTP behavior out of the agent layer and into a deterministic `APIClient`.

## 2A.1 — Dedicated API Client

`utils/api_client.py` owns API communication and returns an `APIExtractionResult` containing `records` and `metadata`.

Important behavior includes top-level JSON arrays and nested record paths, relative pagination URLs, controlled JSON validation, normalized external API errors, and metadata independent from agent reasoning.

## 2A.2 — Retry, Backoff, Rate Limits, and Authentication

The API client supports bounded retries for transient failures such as `429`, `500`, `502`, `503`, and `504`.

It also supports exponential backoff, `Retry-After`, token authentication, configurable auth header/scheme, configurable user agent, and redirect limits.

Authenticated requests must use HTTPS.

## 2A.3 — Bounded Extraction

Extraction is bounded by request timeout, maximum response bytes, maximum total bytes across pagination, maximum pages, maximum records, maximum redirects, and pagination-loop detection.

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

The resulting architecture is:

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

Silver transformation metadata records source/target layer information, row/column counts, schemas, fingerprints, output format, serialized `TransformPlan`, and UTC timestamps.

## 2D.3 — Gold Curated / Analytics Layer

Gold consumes Silver only.

Gold outputs are stored under:

```text
data/gold/<dataset>/
    curated_data.<format>
    curation_metadata.json
```

Gold is intended for curated analytical outputs, KPIs, business filters, aggregations, and reporting tables.

## 2D.4 — Agent Integration

The Medallion transformation toolset is limited to:

```text
extract_load_tool
bronze_to_silver_tool
silver_to_gold_tool
```

Physical storage paths are not exposed as agent choices.

## 2D.4 — Deterministic Lineage

`utils/lineage.py` implements `LineageStore` under:

```text
data/_lineage/lineage.json
```

Lineage is written by deterministic application code, never directly by the LLM.

Supported events are:

```text
extract
transform
curate
```

For incremental ingestion, lineage is part of the durability contract:

```text
atomic Bronze dataset save
      ↓
schema history persistence
      ↓
extraction metadata save
      ↓
lineage persistence
      ↓
checkpoint commit
```

A lineage failure therefore prevents checkpoint advancement.

---

# Phase 2E — Agent Runtime Reliability, Observability, and CI ✅

Phase 2E moved reliability guarantees above the deterministic ETL engine and into the agent runtime itself.

```text
2E.1  Deterministic agent orchestration tests   ✅
2E.2  Failure-stop and loop/runtime guards      ✅
2E.3  Structured execution observability        ✅
2E.4  GitHub Actions CI                         ✅
```

## 2E.1 — Deterministic Agent Orchestration Tests

`tests/test_etl_agent.py` executes the real compiled ETL LangGraph while replacing external LLM/tool dependencies with deterministic fakes.

The tests verify exact Bronze → Silver → Gold tool ordering, graph continuation after successful tool calls, dataset-name propagation, final graph termination, the active safe tool registry, and absence of the legacy generic transformation tool.

```text
real graph runtime        ✅
real routing logic        ✅
real tool-node logic      ✅
real external LLM call    ❌ mocked
real external API call    ❌ mocked
```

## 2E.2 — Deterministic Runtime Safety Guards

Prompt instructions alone are not considered sufficient to guarantee safe orchestration.

The ETL state tracks:

```text
run_id
tool_call_count
workflow_failed
failure_reason
```

### One dependent tool call per turn

A single LLM response may not execute multiple dependent ETL stages at once.

```text
LLM → one tool
        ↓
validate result
        ↓
LLM → next tool
```

Multiple tool calls in one turn are rejected deterministically.

### Tool-call budget

`ETL_MAX_TOOL_CALLS` bounds the number of tool executions in one ETL-agent run.

The default configuration is:

```text
ETL_MAX_TOOL_CALLS=8
```

This prevents an unbounded tool loop.

### Immediate failure stop

Unknown or unauthorized tools are rejected.

If a tool raises an exception, the workflow is marked failed and routed to a deterministic terminal failure node.

```text
required tool fails
       ↓
workflow_failed = true
       ↓
failure node
       ↓
END
```

The agent is not given another opportunity to continue to a dependent downstream stage.

## 2E.3 — Structured Execution Observability

Lineage answers:

```text
Where did this dataset come from?
```

Execution observability answers:

```text
What happened during this particular agent run?
```

`utils/execution_observability.py` implements `ExecutionRunStore` under:

```text
data/_runs/
```

Each ETL invocation receives a UUID-backed `run_id` and a separate run record.

A run tracks:

```text
run_version
run_id
agent
status
started_at
completed_at
max_tool_calls
failure_reason
events
```

Run lifecycle states:

```text
running
completed
failed
```

Tool event states:

```text
success
failed
rejected
```

Each event records sequence number, event type, tool name, status, timestamps, duration, and allowlisted operational metadata.

### Sensitive-data minimization

Raw prompts and raw tool arguments are deliberately not persisted in execution logs.

The observability layer uses an allowlist of operational fields such as logical dataset names, output format, pagination flag, state key, watermark configuration, and safe quality-contract identifiers.

Raw user transformation questions, raw quality requirements, and raw API URLs are intentionally excluded.

### Observability failure semantics

Execution observability is diagnostic rather than transactional.

```text
observability write failure
        ↓
log warning
        ↓
do NOT convert a successful ETL tool into a failed ETL operation
```

This differs from lineage, which participates in the incremental-ingestion durability contract.

## 2E.4 — GitHub Actions CI

The repository contains:

```text
.github/workflows/ci.yml
```

CI runs automatically on:

```text
push to main
pull request targeting main
```

The workflow performs:

```text
checkout
   ↓
install uv
   ↓
install Python 3.12
   ↓
uv sync --locked
   ↓
Ruff
   ↓
pytest
   ↓
uv build
```

It uses read-only repository permissions and concurrency cancellation for superseded runs.

### No production LLM credentials in CI

Some agent modules construct provider clients at import time. CI therefore supplies dummy key strings only so deterministic tests can import those modules.

The tests replace the real orchestration LLM before any external request is made.

The Phase 2E CI pipeline has been verified successfully on GitHub Actions.

---

# Phase 2F — Data Quality, Dataset Contracts, and Quality Governance ✅

Phase 2F introduced typed dataset-quality expectations and made them part of the deterministic Silver/Gold promotion path.

```text
2F.1  Deterministic quality-rule engine        ✅
2F.2  Persisted dataset quality contracts      ✅
2F.3  Silver / Gold quality gates              ✅
2F.4  Agent integration + quality reporting    ✅
2F.5  Quality observability + lineage linkage  ✅
```

The core principle is:

> **The LLM may describe what quality is expected. Deterministic code decides whether the data passes.**

## 2F.1 — Deterministic Quality-Rule Engine

`models/data_quality.py` defines typed Pydantic quality rules and result models.

Supported rules are:

```text
not_null
unique
accepted_values
range
row_count
```

`utils/data_quality.py` deterministically evaluates a Pandas DataFrame against a validated `DataQualityContract`.

Important behavior includes:

- referenced columns must exist
- nullability is controlled independently through `not_null`
- `accepted_values` checks only non-null values
- `range` checks only non-null values
- uniqueness can cover one or multiple columns
- row-count bounds are deterministic
- the evaluator does not mutate the dataset

The result records:

```text
passed
total_checks
failed_checks
checks
```

Each check includes its rule type, pass/fail state, violation count, and a deterministic description.

## 2F.2 — Persisted Dataset Quality Contracts

`utils/data_quality_contracts.py` implements `DataQualityContractStore`.

Contracts are stored under:

```text
data/_contracts/<layer>/<dataset>.json
```

For example:

```text
data/_contracts/silver/orders.json
data/_contracts/gold/revenue.json
```

Each persisted contract is bound to:

```text
store version
Medallion layer
logical dataset name
contract fingerprint
update timestamp
validated contract payload
```

Contract fingerprints use canonical JSON plus SHA-256.

Loading distinguishes:

```text
contract does not exist
        ↓
return None

contract exists but is corrupt/tampered
        ↓
raise DatasetError
```

Layer and dataset bindings are revalidated during loading so moving or editing a contract file cannot silently retarget it.

Contract writes are atomic.

## 2F.3 — Silver / Gold Quality Gates

Silver and Gold now evaluate candidate DataFrames before durable replacement.

```text
source dataset
      ↓
deterministic TransformPlan
      ↓
candidate dataframe
      ↓
load target quality contract
      ↓
evaluate_data_quality()
      │
   ┌──┴───────────────┐
   │                  │
 PASS                FAIL
   │                  │
   ▼                  ▼
atomic save      rejection report
   │                  │
metadata          DataQualityError
   │                  │
lineage              STOP
```

A failed quality gate therefore occurs before:

```text
durable dataset replacement
successful transformation metadata replacement
successful lineage creation
downstream agent continuation
```

This preserves the last known-good Silver or Gold dataset.

Failed candidate details are written to:

```text
data/silver/<dataset>/quality_rejections.json
data/gold/<dataset>/quality_rejections.json
```

The rejection report contains aggregate quality results and contract metadata, not raw rejected rows.

Successful Silver/Gold metadata now also records:

```text
quality_gate.contract_configured
quality_gate.contract_fingerprint
quality_gate.result
```

No configured contract and a successfully passed contract are represented as different states.

## 2F.4 — Agent Quality-Contract Integration

The ETL agent now exposes a fourth safe tool:

```text
configure_quality_contract_tool
```

This tool is used only when the user explicitly specifies Silver or Gold quality expectations.

A dedicated structured-output quality planner converts those explicit requirements into a validated `DataQualityContract`.

The agent-facing flow is:

```text
explicit quality requirement
        ↓
quality-contract planner
        ↓
validated DataQualityContract
        ↓
configure_quality_contract()
        ↓
persist contract
        ↓
Silver / Gold transformation
        ↓
deterministic quality gate
```

Important safety rules:

- quality constraints must not be invented
- Bronze contracts are not agent-configurable
- empty agent-configured contracts are rejected
- the agent cannot supply a skip-quality-check flag
- the agent cannot overwrite or weaken an existing different contract
- re-submitting the exact same contract is idempotent
- quality contracts for a newly created target are configured before promotion

A quality failure produces an explicit `DataQualityError` containing aggregate information such as failed-check count and rejection-report location.

## 2F.5 — Quality Observability and Lineage

Quality information is integrated into both successful lineage and failed execution observability.

### Successful promotion

Successful Silver/Gold lineage records a compact `quality_gate` summary containing:

```text
contract_configured
contract_fingerprint
passed
total_checks
failed_checks
```

`LineageStore` rejects attempts to write successful lineage for a failed quality result.

This means lineage can now answer not only:

```text
Which transformation produced this dataset?
```

but also:

```text
Which quality contract authorized the promotion?
```

### Failed quality gate

A `DataQualityError` is captured in the ETL execution run as a failed tool event.

Safe aggregate metadata can include:

```text
layer
dataset
contract name
contract version
contract fingerprint
passed
total checks
failed checks
```

Raw quality prompts, raw rejected rows, and raw row values are not written to execution observability.

### Quality-governance test coverage

Tests verify:

- passing Silver quality gates
- failed Silver candidates do not overwrite the last known-good Silver dataset
- failed Gold candidates do not overwrite the last known-good Gold dataset
- failed quality candidates do not create successful lineage
- successful lineage records the quality-contract fingerprint
- lineage rejects a failed quality result
- quality-contract overwrite attempts are rejected
- empty agent-created contracts are rejected
- quality contracts are configured before dependent Silver transformations
- quality failures are recorded safely in `_runs/`
- raw user quality requirements are excluded from execution records

---

# Runtime Persistence and Governance Concerns

The project now separates several operational questions:

```text
data/_state/
    → Where should incremental ingestion resume?

data/_contracts/
    → What quality rules govern a Silver or Gold dataset?

data/_lineage/
    → Which source/transformation produced this dataset?
      Which quality contract authorized promotion?

data/_runs/
    → What happened during this specific ETL-agent execution?

quality_rejections.json
    → Why was this candidate dataset rejected?
```

---

# Current ETL Durability Model

Successful incremental Bronze ingestion follows:

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

Breaking schema changes exit before replacing the durable Bronze dataset.

Lineage failure exits before checkpoint advancement.

Silver/Gold promotion follows:

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

Execution-observability failure does not invalidate otherwise successful ETL execution because observability is diagnostic rather than part of the data commit contract.

---

# Runtime Data Layout

```text
data/
├── _state/
│   └── <state_key>.json
├── _contracts/
│   ├── silver/
│   │   └── <dataset>.json
│   └── gold/
│       └── <dataset>.json
├── _lineage/
│   └── lineage.json
├── _runs/
│   └── <run_id>.json
├── bronze/
│   └── <dataset>/
│       ├── extracted_data.<format>
│       ├── extraction_metadata.json
│       ├── schema_history.json
│       └── schema_change_rejections.json
├── silver/
│   └── <dataset>/
│       ├── transformed_data.<format>
│       ├── transformation_metadata.json
│       └── quality_rejections.json     # when needed
└── gold/
    └── <dataset>/
        ├── curated_data.<format>
        ├── curation_metadata.json
        └── quality_rejections.json     # when needed
```

The entire `data/` directory is ignored by Git because it contains generated runtime data and metadata.

---

# SQL Agent

The SQL agent converts natural-language analytical questions into PostgreSQL queries.

Generated SQL is not trusted directly.

Before execution, SQL is parsed with SQLGlot and inspected as an AST.

The validation layer allows exactly one statement, permits read-only query expressions, rejects DML/DDL/multi-statement SQL, rejects invalid SQL, and inspects nested operations and CTEs for hidden writes.

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

---

# Project Structure

```text
Autonomous-data-engineer-agent/
│
├── .github/
│   └── workflows/
│       └── ci.yml
├── agents/
│   ├── data_engineer.py
│   ├── etl_analyst.py
│   └── sql_analyst.py
├── config/
│   └── settings.py
├── models/
│   ├── data_quality.py
│   └── schema.py
├── utils/
│   ├── api_client.py
│   ├── data_layers.py
│   ├── data_quality.py
│   ├── data_quality_contracts.py
│   ├── database.py
│   ├── etl_tools.py
│   ├── exceptions.py
│   ├── execution_observability.py
│   ├── incremental_state.py
│   ├── lineage.py
│   ├── llm_pick.py
│   ├── schema_evolution.py
│   └── sql_safety.py
├── tests/
│   ├── conftest.py
│   ├── test_api_client.py
│   ├── test_data_layers.py
│   ├── test_data_quality.py
│   ├── test_data_quality_contracts.py
│   ├── test_database.py
│   ├── test_etl_agent.py
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

# Runtime Safety Configuration

```env
ETL_MAX_TOOL_CALLS=8
```

This bounds the number of ETL tool executions permitted in one agent run.

---

# Running the System

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

Important coverage includes:

- API destination validation and SSRF protection
- pagination, retries, limits, and HTTP failure normalization
- watermark-based incremental extraction
- checkpoint durability and source/config binding
- schema drift classification and additive evolution
- breaking-schema rejection reports
- Bronze / Silver / Gold routing and metadata
- deterministic transformation plans
- full Medallion lineage integration
- lineage failure / checkpoint protection
- agent tool-order orchestration
- logical dataset-name propagation
- active safe-tool allowlist
- one-tool-per-turn enforcement
- tool-call budget enforcement
- deterministic stop after tool failure
- structured successful-run observability
- structured failed-run observability
- execution-store test isolation
- raw URL / raw prompt exclusion from execution logs
- deterministic data-quality rules
- stable quality-contract fingerprints
- contract layer/dataset binding
- corrupted/tampered contract rejection
- Silver and Gold quality promotion gates
- last-known-good dataset preservation after quality failure
- quality rejection reporting
- agent quality-contract creation
- existing-contract overwrite protection
- empty-contract rejection
- quality contract → lineage linkage
- failed-quality execution observability
- raw quality-requirement exclusion from run logs
- SQL AST safety and read-only execution

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

GitHub Actions runs the same quality checks automatically for pushes and pull requests targeting `main`.

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
- schema compatibility decisions
- schema-rejection policy
- lineage file contents
- direct Bronze → Gold transitions
- an unlimited ETL tool loop
- continuation after a failed required tool
- deterministic quality pass/fail decisions
- direct quality-contract file paths
- quality-contract fingerprints
- replacement or weakening of an existing different quality contract
- quality-check bypasses
- successful lineage creation for quality-rejected data

SQL remains protected by SQLGlot AST validation and read-only PostgreSQL execution.

---

# Current Limitations

- incremental retry idempotency uses exact-row equality rather than business-key upserts
- breaking source schema changes are rejected instead of automatically migrated
- optional fields disappearing from an entire batch may appear as schema removal
- response-size limits are not yet enforced while streaming the body
- data-quality rules are currently limited to `not_null`, `unique`, `accepted_values`, `range`, and `row_count`
- quality contracts are file-backed and are not yet synchronized with dbt or an external catalog
- quality rejections preserve aggregate diagnostics but do not provide row-level quarantine datasets
- lineage uses a single JSON history and is not designed for highly concurrent distributed writers
- execution observability is local file-based rather than backed by a centralized metrics/tracing platform
- agent-behavior tests are deterministic graph tests; broader live-LLM evaluation remains a later concern
- Silver/Gold transformations are still Pandas/file-backed; a warehouse/dbt execution path is not yet integrated

---

# Roadmap

## Completed

### Phase 2A — Reliable API ingestion

- ✅ dedicated `APIClient`
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
- ✅ Bronze ingestion
- ✅ Silver transformations
- ✅ Gold analytics outputs
- ✅ planner / executor separation
- ✅ Medallion agent tools
- ✅ multi-stage ETL orchestration
- ✅ deterministic lineage
- ✅ schema / plan fingerprints
- ✅ lineage-before-checkpoint durability
- ✅ full Medallion lineage integration tests

### Phase 2E — Agent runtime reliability and CI

- ✅ deterministic ETL-agent graph tests
- ✅ active safe-tool surface tests
- ✅ one-tool-per-turn enforcement
- ✅ configurable ETL tool-call budget
- ✅ deterministic failure-stop routing
- ✅ terminal success/failure run states
- ✅ structured `_runs/` execution observability
- ✅ event timing and allowlisted metadata
- ✅ raw prompt / raw tool-argument minimization
- ✅ successful and failed execution-record tests
- ✅ isolated observability test storage
- ✅ GitHub Actions CI
- ✅ automated Ruff / pytest / build quality gates

### Phase 2F — Data quality and dataset contracts

- ✅ typed deterministic quality-rule engine
- ✅ `not_null`, `unique`, `accepted_values`, `range`, and `row_count` rules
- ✅ persisted dataset-specific quality contracts
- ✅ stable contract fingerprints
- ✅ layer/dataset contract binding
- ✅ corruption and tamper detection
- ✅ Silver and Gold pre-persistence quality gates
- ✅ last-known-good output preservation
- ✅ aggregate quality rejection reports
- ✅ quality result persistence in transformation metadata
- ✅ agent-facing quality-contract configuration tool
- ✅ no contract overwrite/weakening through the agent
- ✅ contract-before-promotion orchestration
- ✅ quality-aware execution observability
- ✅ quality-contract fingerprint linkage in lineage
- ✅ lineage refusal for failed quality gates
- ✅ privacy-preserving quality diagnostics

---

## Next Planned Work

### Phase 2G — Warehouse Bridge

Prepare a database-backed execution target before dbt integration.

Planned direction:

- deterministic Bronze → PostgreSQL loading
- explicit warehouse schema/layer conventions
- safe application-controlled table naming
- deterministic write behavior and tests
- preserve existing source/checkpoint/schema/quality guarantees

### Phase 2H — dbt Integration

Planned direction:

- add a dbt project and PostgreSQL adapter
- expose Bronze warehouse tables as dbt sources
- build Silver dbt models
- build Gold dbt marts
- integrate dbt tests with the existing quality-governance model
- add a bounded dbt execution tool
- feed dbt artifacts into lineage and execution observability
- later introduce a dbt-specific SQL/model planner for validated model generation

### Later Candidates

- configurable business-key upserts
- richer dataset metadata and semantic contracts
- workflow orchestration
- Docker
- richer lineage backends
- centralized tracing / metrics
- live LLM evaluation
- LLM cost monitoring
- streamed response-size enforcement

---

# License

This project is released under the MIT License.
