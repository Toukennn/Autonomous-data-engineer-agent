# Architecture

## Overview

The Autonomous Data Engineer Agent combines agentic orchestration with deterministic data-platform execution.

The application contains three primary agents:

- **Data Engineer Agent** — top-level router
- **ETL Analyst Agent** — orchestrates governed ingestion and transformation workflows
- **SQL Analyst Agent** — translates analytical questions into validated read-only PostgreSQL queries

## Cloud architecture

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
                │              └── private PostgreSQL
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

## Warehouse path

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

## Data Engineer Router

The top-level LangGraph graph classifies each request as either:

```text
etl
sql
```

and delegates the request to the corresponding specialist.

![Data Engineer Graph](../data_engineer_graph.png)

## ETL Analyst

The ETL Analyst is a bounded ReAct-style orchestrator.

Current tool surface:

```text
extract_load_tool
bronze_to_silver_tool
silver_to_gold_tool
dbt_bronze_to_silver_tool
dbt_silver_to_gold_tool
configure_quality_contract_tool
```

The file-backed path is:

```text
External API
    ↓
Bronze
    ↓
Silver
    ↓
Gold
```

The warehouse-backed path is:

```text
External API
    ↓
Durable Bronze filesystem
    ↓
PostgreSQL Bronze
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

![ETL Analyst Graph](../etl_analyst_graph.png)

## SQL Analyst

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

The same governed catalog snapshot is used for both prompt context and deterministic SQL validation.

![SQL Analyst Graph](../sql_analyst_graph.png)

## Runtime persistence

The cloud deployment stores durable runtime state under one volume:

```text
/app/runtime
├── data
├── dbt
└── home
```

The image routes:

```text
/app/data  → /app/runtime/data
/app/dbt   → /app/runtime/dbt
HOME       → /app/runtime/home
```

This keeps checkpoints, Bronze data, lineage, run records, generated dbt state, and runtime home data on persistent storage.
