# Data Engineer Agent

A safety-oriented agentic data engineering system for **ETL workflows** and **natural-language SQL analytics**.

The project uses LangGraph to route user requests to specialized ETL and SQL agents while keeping sensitive operations under deterministic application control.

The core design principle is:

> **LLMs decide what should happen. Deterministic tools decide how it happens.**

This prevents the system from directly executing arbitrary LLM-generated Python or blindly executing SQL.

---

## Overview

The system currently contains three main agents:

- **Data Engineer Agent** — routes requests to the correct specialist.
- **ETL Analyst Agent** — extracts API data and performs structured DataFrame transformations.
- **SQL Analyst Agent** — converts natural-language questions into PostgreSQL queries and safely executes read-only analytics.

```text
User Request
      │
      ▼
Data Engineer Router
   ┌───────┴────────┐
   ▼                ▼
ETL Analyst      SQL Analyst
   │                │
   ▼                ▼
Safe ETL         SQL Validation
Operations           │
   │                 ▼
   ▼           Read-only PostgreSQL
Data Files            │
                      ▼
                 Final Answer
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

The ETL agent supports API extraction and deterministic tabular transformations.

The LLM does **not** generate or execute arbitrary Python.

Instead, it produces a structured `TransformPlan` containing supported operations such as:

- column selection and removal
- column renaming
- row filtering
- duplicate removal
- sorting
- missing-value handling
- type casting
- string transformations
- grouped aggregations

The application then executes those operations through trusted Pandas code.

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

Additional protections include:

- file operations restricted to the project's `data/` directory
- configurable HTTP request timeouts
- configurable API response-size limits
- explicit dataset and API error handling
- no use of `exec()`

![ETL Analyst Graph](etl_analyst_graph.png)

---

## SQL Agent

The SQL agent converts natural-language analytical questions into PostgreSQL queries.

Generated SQL is **not trusted directly**.

Before reaching PostgreSQL, queries are parsed using SQLGlot and inspected as an abstract syntax tree.

The validation layer:

- allows exactly one SQL statement
- permits read-only query expressions
- rejects DML and DDL operations
- rejects multi-statement queries
- inspects nested operations and CTEs

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

![SQL Analyst Graph](sql_analyst_graph.png)

---

## Project Structure

```text
Data-engineer-agent/
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
│   ├── database.py
│   ├── etl_tools.py
│   ├── exceptions.py
│   ├── llm_pick.py
│   └── sql_safety.py
│
├── tests/
│   ├── conftest.py
│   ├── test_database.py
│   ├── test_etl_tools.py
│   ├── test_settings.py
│   └── test_sql_safety.py
│
├── data/
├── .env.example
├── .python-version
├── feed_db.py
├── main.py
├── pyproject.toml
└── uv.lock
```

---

## Tech Stack

**Agent orchestration**

- LangGraph
- LangChain

**LLMs**

- OpenAI
- Anthropic

**Data engineering**

- Pandas
- PyArrow
- PostgreSQL
- Psycopg

**Safety and validation**

- SQLGlot
- Pydantic
- Pydantic Settings

**Engineering**

- pytest
- Ruff
- uv

---

## Installation

The project uses Python 3.12 and `uv` for dependency management.

Clone the repository:

```bash
git clone https://github.com/Toukennn/Data-enginner-agent.git
cd Data-enginner-agent
```

Install the locked dependencies:

```bash
uv sync --locked
```

---

## Environment Configuration

Copy the example configuration:

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
OPENAI_API_KEY=your_key
ANTHROPIC_API_KEY=your_key

DB_HOST=localhost
DB_PORT=5432
DB_USER=your_database_user
DB_PASSWORD=your_database_password
DB_NAME=your_database

SQL_STATEMENT_TIMEOUT_MS=10000
SQL_MAX_ROWS=1000

HTTP_TIMEOUT_SECONDS=30
API_MAX_RESPONSE_BYTES=20000000
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

## Example ETL Request

```text
Extract data from:

https://pokeapi.co/api/v2/pokemon

and save the result as CSV.
```

The request is routed to the ETL agent, which performs extraction through the controlled `ETLTools` implementation.

---

## Example SQL Request

```text
What are the different payment methods available in the database?
```

The SQL workflow:

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

The project contains deterministic unit tests for:

- SQL safety
- ETL transformations
- path restrictions
- configuration
- API failure handling
- database read-only behavior

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

### ETL

```text
LLM → typed TransformPlan → deterministic Pandas operations
```

rather than:

```text
LLM → generated Python → exec()
```

### SQL

```text
LLM → SQL → AST validation → read-only DB transaction
```

rather than:

```text
LLM → SQL → direct execution
```

This architecture is intended to make agentic data workflows easier to reason about, test, and secure.

---

## Roadmap

Planned improvements include:

- API pagination
- retry and exponential backoff
- rate-limit handling
- authenticated APIs
- incremental ingestion
- schema-evolution handling
- Bronze / Silver / Gold data layers
- data-quality validation
- dbt integration
- workflow orchestration
- Docker
- CI/CD
- agent observability and tracing
- LLM evaluation and cost monitoring

---

## License

This project is released under the MIT License.