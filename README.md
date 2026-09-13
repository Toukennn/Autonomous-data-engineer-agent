# Autonomous Data Engineer Agent

A safety-oriented agentic data engineering system for **API ingestion**, **deterministic ETL workflows**, and **natural-language SQL analytics**.

The project uses LangGraph to route user requests to specialized ETL and SQL agents while keeping sensitive operations under deterministic application control.

The core design principle is:

> **LLMs decide what should happen. Deterministic tools decide how it happens.**

The LLM may select a supported operation or configure a known ingestion contract, but it does not receive arbitrary execution privileges, manually control checkpoints, decide whether a schema transition is safe, or bypass SQL safety controls.

---

## Overview

The system currently contains three main agents:

- **Data Engineer Agent** — routes requests to the correct specialist.
- **ETL Analyst Agent** — extracts API data, supports persistent incremental ingestion, handles safe schema evolution, and performs deterministic DataFrame transformations.
- **SQL Analyst Agent** — converts natural-language questions into PostgreSQL queries and safely executes read-only analytics.

```text
                         User Request
                              │
                              ▼
                     Data Engineer Router
                     ┌────────┴────────────┐
                     ▼                     ▼
                ETL Analyst            SQL Analyst
                     │                     │
          ┌──────────┴──────────┐          ▼
          ▼                     ▼      SQLGlot AST
   API ingestion         TransformPlan  validation
          │                     │          │
          ▼                     ▼          ▼
      APIClient          deterministic  read-only
          │              Pandas tools   PostgreSQL
          ▼
 incremental state
 schema evolution
 durable data files
```

---

## Architecture

### Data Engineer Router

The top-level LangGraph agent classifies each request as either:

```text
etl
```

or:

```text
sql
```

and delegates the task to the appropriate specialist agent.

![Data Engineer Graph](data_engineer_graph.png)

---

## ETL Agent

The ETL agent is a ReAct-style agent with controlled tools for extraction and transformation.

The LLM does **not** generate or execute arbitrary Python. Instead, deterministic application code performs all data operations.

### Deterministic Transformations

For transformation requests, the LLM produces a validated `TransformPlan` containing supported operations such as:

- column selection and removal
- column renaming
- row filtering
- duplicate removal
- sorting
- missing-value handling
- type casting
- string transformations
- grouped aggregations

The application then executes the plan through trusted Pandas operations.

```text
User request
     │
     ▼
LLM transformation planner
     │
     ▼
Validated TransformPlan
     │
     ▼
Deterministic ETLTools
     │
     ▼
CSV / JSON / Parquet
```

### API Ingestion Path

API extraction is separated into deterministic layers:

```text
LLM / ETL Agent
      │
      ▼
extract_load_tool
      │
      ▼
ETLTools
      │
      ▼
APIClient
      │
      ├── URL / destination validation
      ├── authentication
      ├── pagination
      ├── retry / backoff
      ├── rate-limit handling
      ├── redirect validation
      └── extraction limits
      │
      ▼
normalized records
      │
      ▼
incremental merge / schema policy
      │
      ▼
atomic durable persistence
```

---

# Implemented ETL Reliability Phases

The API-ingestion subsystem has been developed in several safety-focused phases.

The details below document the important guarantees added in each substep.

---

## Phase 2A — Reliable API Ingestion ✅

Phase 2A moved HTTP behavior out of the agent/tool layer and into a dedicated deterministic `APIClient`.

### 2A.1 — Dedicated API Client

`utils/api_client.py` owns API communication and returns an `APIExtractionResult` containing extracted records and deterministic metadata.

Important details:

- supports top-level JSON arrays and nested record paths
- supports configurable pagination paths
- accepts relative pagination URLs
- normalizes HTTP/network failures into controlled application errors
- validates JSON responses before use
- keeps HTTP mechanics outside the LLM
- records extraction metadata independently from agent reasoning

The result object contains:

```text
records
metadata
```

so the extraction layer is separated cleanly from persistence and agent behavior.

---

### 2A.2 — Retry, Backoff, Rate Limits, and Authentication

The API client implements bounded retry behavior for transient HTTP failures including:

```text
429
500
502
503
504
```

It also supports:

- exponential retry backoff
- retry-aware HTTP adapters
- `Retry-After` support through the HTTP retry policy
- optional token-based authentication
- configurable authentication header
- configurable authentication scheme
- configurable user agent
- configurable redirect limits

Authenticated HTTP calls must use HTTPS.

This prevents API credentials from being sent over an insecure connection.

Credentials are loaded from application settings and are not exposed as free-form agent-generated values.

---

### 2A.3 — Bounded Extraction

API extraction is explicitly bounded to prevent uncontrolled downloads or pagination loops.

Configured protections include:

- maximum bytes per response
- maximum total bytes across pagination
- maximum number of pages
- maximum number of records
- request timeout
- maximum redirects
- visited-URL detection for pagination loops

Extraction metadata records information such as:

```text
pages_fetched
records_extracted
bytes_downloaded
```

This makes ingestion observable while preventing an LLM-generated request from causing unbounded data retrieval.

---

### 2A.4 — SSRF and Redirect Hardening

Before making requests, the client validates destinations instead of trusting LLM-provided URLs blindly.

The protection layer rejects unsafe destinations such as:

- `localhost`
- `.localhost`
- loopback addresses
- private network addresses
- link-local addresses
- unspecified addresses
- multicast addresses
- other non-public IP destinations
- hostnames resolving to unsafe addresses

Only supported HTTP schemes are allowed.

Redirects are handled manually so every redirected destination can be validated before the next request.

Authenticated requests are also prevented from following unsafe cross-origin flows that could expose credentials.

This provides protection against common SSRF-style attacks where an agent might otherwise be tricked into accessing local or internal infrastructure.

---

## Phase 2B — Persistent Incremental Ingestion ✅

Phase 2B added durable watermark-based ingestion while preserving the rule that:

> **Checkpoint state belongs to deterministic code, not the LLM.**

---

### 2B.1 — Persistent Checkpoint Store

`utils/incremental_state.py` implements `IncrementalStateStore`.

Important details:

- checkpoints are stored under:

```text
data/_state/
```

- state keys are validated against a restricted format
- unsafe state-key values are rejected
- path traversal is rejected
- nested arbitrary state paths are rejected
- checkpoint files are JSON
- state writes use a temporary file followed by replacement
- temporary files are cleaned up on failure where possible
- invalid or corrupted checkpoints produce controlled `DatasetError` failures

A checkpoint stores information such as:

```text
version
state_key
cursor_value
updated_at
metadata
```

The timestamp is persisted in UTC.

The store is application-controlled and is not exposed to the LLM as a directly editable resource.

---

### 2B.2 — Watermark-Aware API Extraction

`APIClient.extract_records()` supports incremental extraction through:

```text
watermark_param
watermark_field
watermark_value
```

The previous checkpoint value is added to the first API request using the configured watermark query parameter.

Pagination then continues normally.

The next watermark is calculated deterministically from the returned records.

Important safety rules include:

- incomplete incremental configuration is rejected
- first runs can occur without an existing checkpoint
- no-new-record runs preserve the previous watermark
- missing watermark fields are rejected
- mixed incompatible watermark types are rejected
- watermark regression is rejected
- the LLM does not provide the previous cursor value

The important separation is:

```text
LLM chooses:
    state_key
    watermark_param
    watermark_field

Deterministic code chooses:
    watermark_value
```

This prevents the agent from skipping data by inventing a future checkpoint.

---

### 2B.3 — Atomic and Idempotent Incremental Persistence

`ETLTools` connects the checkpoint store to extraction and durable dataset persistence.

The critical ordering is:

```text
load checkpoint
      ↓
extract records using checkpoint
      ↓
merge with durable dataset
      ↓
atomically save dataset
      ↓
persist schema history
      ↓
atomically save extraction metadata
      ↓
ONLY THEN
      ↓
advance checkpoint
```

The checkpoint is deliberately last.

This means a checkpoint cannot advance when the durable ingestion outputs have not been successfully written.

For example:

```text
API extraction succeeds
dataset write succeeds
metadata write fails
checkpoint DOES NOT advance
```

The next run can safely retry the same range.

Retry safety is preserved using exact-row deduplication.

If the dataset was successfully written but a later step failed before checkpoint advancement, the same records may be fetched again.

The incremental merge removes identical duplicate rows so retrying the same extraction does not duplicate those records.

At the current stage, this is:

```text
exact-row idempotency
```

rather than a business-key upsert system.

Business-key merge/upsert behavior is intentionally left for a later phase.

---

### 2B.4 — Agent and Tool Integration

The ETL extraction tool exposes only the information the LLM is allowed to select:

```text
state_key
watermark_param
watermark_field
```

It intentionally does **not** expose:

```text
watermark_value
```

The previous cursor is always loaded internally from application state.

```text
LLM
 │
 ├── state_key
 ├── watermark_param
 └── watermark_field
          │
          ▼
deterministic checkpoint store
          │
          ▼
previous watermark
          │
          ▼
APIClient
```

Additional protections include:

- incremental ingestion requires all three incremental parameters
- the LLM is instructed not to invent watermark semantics
- full extraction remains the default when an API's incremental contract is unknown
- the same `state_key` is expected to represent the same pipeline
- state metadata binds a checkpoint to its source URL
- state metadata binds the checkpoint to its watermark parameter
- state metadata binds the checkpoint to its watermark field
- reusing a state key with a different source/configuration is rejected
- checkpoint files remain application-controlled

This prevents an agent from bypassing state safety by simply changing extraction parameters.

---

## Phase 2C — Schema Evolution ✅

Phase 2C adds deterministic schema comparison, safe additive evolution, schema version history, and durable rejection reports for breaking changes.

The current schema policy is:

```text
same schema                 → ACCEPT
added columns only          → ACCEPT
removed columns             → REJECT
logical type changes        → REJECT
```

The LLM does not decide whether a schema transition is safe.

---

### 2C.1 — Detect and Classify Schema Drift

`utils/schema_evolution.py` contains deterministic schema comparison logic.

A `SchemaDiff` classifies:

```text
added_columns
removed_columns
type_changes
```

It also exposes deterministic properties such as:

```text
has_changes
is_additive_only
is_breaking
```

Pandas dtypes are reduced to a smaller logical type system.

The current logical types are:

```text
boolean
number
datetime
string
object
```

Integer and floating-point columns are intentionally grouped under:

```text
number
```

This means a change such as:

```text
int64 → float64
```

does not automatically appear as schema drift.

That avoids rejecting harmless numeric widening.

Example:

```text
existing schema

id      number
name    string

incoming schema

id        number
name      string
category  string
```

produces:

```text
added_columns = ("category",)
removed_columns = ()
type_changes = {}
is_additive_only = True
```

Schema comparison also preserves deterministic column ordering.

---

### 2C.2 — Safe Additive Schema Evolution

When the incoming API adds fields without removing or changing existing columns, the schema is evolved automatically.

Example:

```text
Existing dataset

id | name
1  | A
2  | B
```

Incoming API batch:

```text
id | name | email
3  | C    | c@example.com
```

Durable result:

```text
id | name | email
1  | A    | null
2  | B    | null
3  | C    | c@example.com
```

Important details:

- historical rows receive null values for newly introduced columns
- existing columns preserve their durable order
- new columns are appended after existing columns
- new-column order follows the incoming schema
- removed columns remain rejected
- incompatible logical type changes remain rejected
- additive evolution remains compatible with retry idempotency

Schema compatibility is decided by deterministic code.

There is no LLM parameter such as:

```text
allow_schema_evolution=true
```

because the agent is not trusted to decide whether a destructive schema transition should be accepted.

---

### 2C.3 — Schema History and Fingerprints

Every logical schema can be represented using a stable SHA-256 fingerprint.

The fingerprint is created from the ordered logical schema rather than row values.

For example:

```text
id:number
name:string
```

produces one stable fingerprint.

Changing the actual data:

```text
1,Alice
2,Bob
```

to:

```text
100,John
200,Mary
```

does not change the schema fingerprint.

Adding:

```text
email:string
```

does change the fingerprint.

Each extraction output directory can maintain:

```text
schema_history.json
```

The schema history stores:

- schema version
- schema fingerprint
- logical schema
- recording timestamp
- source URL

Example conceptually:

```json
{
  "history_version": 1,
  "latest_fingerprint": "abc123...",
  "entries": [
    {
      "schema_version": 1,
      "fingerprint": "old...",
      "schema": {
        "id": "number",
        "name": "string"
      }
    },
    {
      "schema_version": 2,
      "fingerprint": "new...",
      "schema": {
        "id": "number",
        "name": "string",
        "email": "string"
      }
    }
  ]
}
```

Important behavior:

- the first schema becomes version 1
- unchanged schemas do not create fake new versions
- safe additive evolution produces the next schema version
- schema history uses atomic JSON persistence
- failure to persist schema history prevents checkpoint advancement

Extraction metadata also records:

```text
schema_version
schema_fingerprint
schema_history_file
schema_evolution_policy
```

This creates a durable audit trail of schema evolution over time.

---

### 2C.4 — Breaking Schema Change Policy and Rejection Reports

Breaking changes use a dedicated structured exception:

```text
SchemaEvolutionError
```

which subclasses:

```text
DatasetError
```

The exception carries deterministic schema-diff details rather than only a human-readable error string.

Breaking transitions currently include:

```text
removed columns
logical type changes
```

For example:

```text
Existing schema

id      number
name    string
email   string

Incoming schema

id      number
name    string
```

produces a breaking change because:

```text
email
```

was removed.

Instead of silently modifying the durable dataset, the system rejects the transition.

A durable rejection report is written to:

```text
schema_change_rejections.json
```

A rejection event may contain:

- stable rejection ID
- detection timestamp
- decision
- rejection reason
- schema-evolution policy
- source URL
- previous watermark
- existing schema fingerprint
- incoming schema fingerprint
- added columns
- removed columns
- logical type changes
- complete existing schema
- complete incoming schema

---

### Schema Transition Fingerprints

A stable schema-transition fingerprint is calculated from:

```text
existing schema fingerprint
        +
incoming schema fingerprint
```

Conceptually:

```text
old-schema-fingerprint
        ↓
        +
        ↑
new-schema-fingerprint
        ↓
SHA-256
        ↓
transition / rejection ID
```

This means the same repeated breaking transition generates the same rejection ID.

Identical rejection events are therefore not appended repeatedly to the rejection report.

This keeps the rejection log idempotent.

---

### Breaking-Change Durability Guarantee

A breaking change is detected before the durable dataset-save stage.

The flow is:

```text
incoming API batch
        │
        ▼
schema comparison
        │
        ├── safe
        │     │
        │     ▼
        │   merge
        │     │
        │     ▼
        │   persist
        │
        └── breaking
              │
              ▼
       persist rejection report
              │
              ▼
            raise
              X
              X dataset is NOT replaced
              X schema history is NOT advanced
              X extraction metadata is NOT overwritten
              X checkpoint is NOT advanced
```

This prevents a breaking API contract change from corrupting or silently mutating the durable dataset.

---

## Current ETL Durability Model

Successful incremental ingestion follows this order:

```text
API extraction
      ↓
tabular normalization
      ↓
incremental merge
      ↓
atomic dataset save
      ↓
schema history persistence
      ↓
atomic extraction metadata save
      ↓
checkpoint commit
```

The checkpoint is intentionally last.

If any required durable operation fails before checkpoint persistence, the checkpoint does not advance.

This gives the system a transaction-like ingestion model even though the output is currently file-based rather than managed by a transactional data platform.

For breaking schema changes, execution exits before the durable dataset save.

---

## SQL Agent

The SQL agent converts natural-language analytical questions into PostgreSQL queries.

Generated SQL is **not trusted directly**.

Before reaching PostgreSQL, queries are parsed using SQLGlot and inspected as an abstract syntax tree.

The validation layer:

- allows exactly one SQL statement
- permits read-only query expressions
- rejects DML operations
- rejects DDL operations
- rejects multi-statement queries
- rejects invalid SQL
- inspects nested operations
- inspects CTEs for hidden write operations

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

This creates defense in depth instead of relying on an LLM to decide whether SQL is safe.

---

## Project Structure

```text
Autonomous-data-engineer-agent/
│
├── agents/
│   ├── data_engineer.py
│   ├── etl_analyst.py
│   └── sql_analyst.py
│
├── config/
│   └── settings.py
│
├── models/
│   └── schema.py
│
├── utils/
│   ├── __init__.py
│   ├── api_client.py
│   ├── database.py
│   ├── etl_tools.py
│   ├── exceptions.py
│   ├── incremental_state.py
│   ├── llm_pick.py
│   ├── schema_evolution.py
│   └── sql_safety.py
│
├── tests/
│   ├── conftest.py
│   ├── test_api_client.py
│   ├── test_database.py
│   ├── test_etl_tools.py
│   ├── test_incremental_state.py
│   ├── test_schema_evolution.py
│   ├── test_settings.py
│   └── test_sql_safety.py
│
├── data/
│   └── _state/
│
├── .env.example
├── .gitignore
├── .python-version
├── LICENSE
├── README.md
├── data_engineer_graph.png
├── etl_analyst_graph.png
├── sql_analyst_graph.png
├── feed_db.py
├── main.py
├── pyproject.toml
└── uv.lock
```

Runtime dataset folders may additionally contain files such as:

```text
extracted_data.csv
extraction_metadata.json
schema_history.json
schema_change_rejections.json
```

depending on the executed pipeline and schema events.

---

## Tech Stack

### Agent Orchestration

- LangGraph
- LangChain

### LLM Providers

- OpenAI
- Anthropic

### Data Engineering

- Pandas
- PyArrow
- PostgreSQL
- Psycopg
- Requests
- urllib3 retry support

### Safety and Validation

- SQLGlot
- Pydantic
- Pydantic Settings
- deterministic schema comparison
- SSRF/destination validation
- read-only database transactions
- atomic file persistence
- controlled application exceptions

### Engineering

- pytest
- Ruff
- uv

---

## Installation

The project uses Python 3.12 and `uv` for dependency management.

Clone the repository:

```bash
git clone https://github.com/Toukennn/Autonomous-data-engineer-agent.git
cd Autonomous-data-engineer-agent
```

Install the locked dependencies:

```bash
uv sync --locked
```

---

## Environment Configuration

Copy the example configuration.

### PowerShell

```powershell
Copy-Item .env.example .env
```

### Linux / macOS

```bash
cp .env.example .env
```

Then configure the required values in `.env`.

Example:

```env
# ============================================================
# LLM PROVIDERS
# ============================================================

OPENAI_API_KEY=your_openai_api_key
ANTHROPIC_API_KEY=your_anthropic_api_key


# ============================================================
# MODELS
# ============================================================

OPENAI_LOW_MODEL=gpt-5.6-luna
OPENAI_MEDIUM_MODEL=gpt-5.6-terra
OPENAI_HIGH_MODEL=gpt-5.6-sol

ANTHROPIC_MODEL=claude-sonnet-5


# ============================================================
# POSTGRESQL
# ============================================================

DB_HOST=localhost
DB_PORT=5432
DB_USER=your_database_user
DB_PASSWORD=your_database_password
DB_NAME=your_database_name


# ============================================================
# SQL SAFETY
# ============================================================

SQL_STATEMENT_TIMEOUT_MS=10000
SQL_MAX_ROWS=1000


# ============================================================
# API INGESTION
# ============================================================

HTTP_TIMEOUT_SECONDS=30

API_MAX_RESPONSE_BYTES=20000000
API_MAX_TOTAL_RESPONSE_BYTES=100000000

API_MAX_PAGES=50
API_MAX_RECORDS=100000

API_RETRY_TOTAL=4
API_RETRY_BACKOFF_SECONDS=0.5

API_USER_AGENT=autonomous-data-engineer-agent/0.1

API_MAX_REDIRECTS=5


# Optional authenticated API configuration

API_AUTH_TOKEN=
API_AUTH_HEADER=Authorization
API_AUTH_SCHEME=Bearer
```

Never commit your real `.env` file.

---

## Running the Agents

### Data Engineer Router

```bash
uv run python -m agents.data_engineer
```

### SQL Analyst

```bash
uv run python -m agents.sql_analyst
```

### ETL Analyst

```bash
uv run python -m agents.etl_analyst
```

---

## Example ETL Requests

### Full API Extraction

```text
Extract data from:

https://pokeapi.co/api/v2/pokemon

and save the result as CSV.
```

The request is routed to the ETL agent, which performs extraction through the controlled `ETLTools` and `APIClient` implementations.

---

### Incremental API Extraction

Incremental ingestion should only be used when the API's watermark semantics are known.

Conceptually, the agent needs to know:

```text
stable state key
API watermark query parameter
record field representing the watermark
```

The previous cursor value is intentionally loaded by deterministic application code rather than supplied by the LLM.

Example conceptually:

```text
state_key       = orders_pipeline
watermark_param = after_id
watermark_field = id
```

The application then loads the previous checkpoint internally and produces a request such as:

```text
GET /orders?after_id=500
```

The agent does not provide:

```text
500
```

itself.

---

## Example SQL Request

```text
What are the different payment methods available in the database?
```

The SQL workflow is:

```text
Natural-language question
        ↓
Question refinement
        ↓
Database schema context
        ↓
SQL generation
        ↓
Deterministic SQL validation
        ↓
Read-only PostgreSQL execution
        ↓
Natural-language answer
```

---

## Testing

The test suite covers the deterministic safety boundaries of the project.

Coverage includes:

- URL validation
- HTTP failure normalization
- invalid JSON handling
- API pagination
- relative pagination
- pagination loops
- maximum page enforcement
- maximum record enforcement
- response-size limits
- total-download limits
- retry policy
- private IP rejection
- loopback rejection
- localhost rejection
- DNS-to-private-IP rejection
- authenticated HTTP rejection
- cross-origin authentication protections
- incremental watermark injection
- first incremental runs
- no-new-record watermark preservation
- missing watermark fields
- mixed watermark types
- watermark regression
- incomplete incremental configuration
- checkpoint persistence
- checkpoint updates
- checkpoint path safety
- corrupted checkpoint handling
- dataset-save failure behavior
- checkpoint advancement ordering
- retry idempotency
- checkpoint/source binding
- schema drift classification
- added-column detection
- removed-column detection
- logical type changes
- numeric type normalization
- additive schema evolution
- schema fingerprint stability
- schema version history
- schema-history failure behavior
- breaking-schema rejection reporting
- rejection-report idempotency
- deterministic ETL transformations
- path restrictions
- SQL AST safety
- read-only database behavior
- runtime configuration

Run all tests:

```bash
uv run pytest -v
```

---

## Linting

Run Ruff:

```bash
uv run ruff check .
```

---

## Reproducible Environment

The project uses:

```text
.python-version
pyproject.toml
uv.lock
```

to make local environments reproducible.

A clean installation can be verified with:

```bash
uv sync --locked
uv run pytest
uv run ruff check .
uv build
```

---

## Current Safety Model

The project deliberately treats LLM output as **untrusted input**.

### ETL Transformations

```text
LLM
 ↓
typed TransformPlan
 ↓
validated supported operation
 ↓
deterministic Pandas implementation
```

There is no arbitrary:

```python
exec(...)
```

or unrestricted LLM-generated Python execution.

---

### API Extraction

```text
LLM selects a known extraction contract
        ↓
ETLTools
        ↓
APIClient
        ↓
destination validation
pagination
retries
limits
authentication controls
        ↓
deterministic incremental state
        ↓
schema policy
        ↓
atomic persistence
```

The LLM does not directly control:

- API authentication tokens
- checkpoint cursor values
- checkpoint file contents
- checkpoint persistence timing
- schema compatibility decisions
- schema-history versioning
- schema-rejection policy
- arbitrary local filesystem locations
- arbitrary Python execution

---

### SQL

```text
LLM
 ↓
SQL
 ↓
SQLGlot AST validation
 ↓
read-only PostgreSQL transaction
```

The system therefore applies deterministic controls at the boundaries where an agent could otherwise perform unsafe or irreversible operations.

---

## Current Limitations

Some deliberate limitations remain and are candidates for later phases.

### Exact-row deduplication

Incremental retry idempotency currently uses exact-row equality.

The project does not yet implement configurable business-key upserts such as:

```text
primary_key = ["order_id"]
```

or merge policies such as:

```text
insert
update
delete
SCD Type 2
```

---

### Conservative schema removals

Breaking schema changes are rejected rather than automatically migrated.

This is deliberate.

The system currently prefers:

```text
reject + report
```

over:

```text
guess + mutate
```

---

### Optional API Fields

If an optional field disappears from an entire API batch, the batch may appear to have removed a column.

The current policy rejects that transition conservatively.

A richer source-data contract system could later distinguish:

```text
temporarily absent field
```

from:

```text
actual schema removal
```

---

### Response Body Streaming

Response-size enforcement currently operates on the received response body.

A later hardening phase could enforce byte limits while streaming response content before the entire body is materialized.

---

### Logical Schema Scope

Schema history currently tracks the tabular logical schema.

It does not yet persist a richer contract including concepts such as:

```text
nullable
primary key
unique
min/max
semantic type
foreign key
business description
source field lineage
```

These can be added later as the metadata layer matures.

---

## Roadmap

### Completed

- ✅ deterministic ETL transformations
- ✅ SQL AST validation
- ✅ read-only PostgreSQL execution
- ✅ reliable API ingestion
- ✅ dedicated `APIClient`
- ✅ pagination
- ✅ retry and exponential backoff
- ✅ rate-limit handling
- ✅ authenticated APIs
- ✅ extraction limits
- ✅ SSRF protection
- ✅ redirect hardening
- ✅ persistent incremental ingestion
- ✅ deterministic checkpoint handling
- ✅ watermark-based incremental extraction
- ✅ atomic dataset persistence
- ✅ retry idempotency
- ✅ agent-safe incremental configuration
- ✅ checkpoint/source binding
- ✅ schema drift detection
- ✅ logical schema classification
- ✅ safe additive schema evolution
- ✅ schema fingerprints
- ✅ schema version history
- ✅ breaking-schema rejection policy
- ✅ durable schema rejection reports
- ✅ rejection-event idempotency

---

### Next Phase

## Phase 2D — Bronze / Silver / Gold Data Architecture

Planned substeps:

```text
2D.1  Deterministic Bronze layer
2D.2  Silver transformation layer
2D.3  Gold curated/output layer
2D.4  Agent integration and lineage
```

The target architecture is:

```text
                 External API
                     │
                     ▼
              ┌─────────────┐
              │   BRONZE    │
              │ raw/source  │
              └──────┬──────┘
                     │
             deterministic
             transformations
                     │
                     ▼
              ┌─────────────┐
              │   SILVER    │
              │ clean/model │
              └──────┬──────┘
                     │
              business-level
              aggregation
                     │
                     ▼
              ┌─────────────┐
              │    GOLD     │
              │ consumption │
              └─────────────┘
```

The intended responsibilities are:

```text
Bronze = source-oriented durable ingestion
Silver = cleaned / standardized / transformed datasets
Gold   = curated analytical or business-facing datasets
```

---

### Planned Later

- data-quality validation
- configurable business-key upserts
- richer dataset contracts
- lineage metadata
- dbt integration
- workflow orchestration
- Docker
- CI/CD
- agent observability
- tracing
- LLM evaluation
- LLM cost monitoring
- streaming response-size enforcement

---

## License

This project is released under the MIT License.
