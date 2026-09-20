# Safety Model

## Core principle

> **LLMs decide what should happen. Deterministic code decides how it is allowed to happen.**

All LLM output is treated as **untrusted input**.

The model may:

- classify a request as ETL or SQL
- choose among supported tools
- create typed transformation plans
- create typed data-quality plans
- generate one analytical SQL query

Deterministic application code controls:

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

The model does not receive arbitrary Python execution, unrestricted shell access, unrestricted filesystem mutation, arbitrary database writes, arbitrary Jinja, unrestricted dbt execution, or direct control over checkpoint/merge semantics.

## Planner vs executor

### File-backed transformations

The LLM receives the user request plus dataset metadata and produces a validated Pydantic `TransformPlan`.

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

### dbt transformations

Warehouse transformations use a typed `DBTTransformPlan`.

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

The planner does not write unrestricted dbt SQL or Jinja.

### Data quality

A typed `DataQualityContract` supports rules such as:

```text
not_null
unique
accepted_values
range
row_count
```

Contracts are stored and enforced by deterministic code.

## Governed SQL safety

Natural-language analytics use a governed catalog containing approved Silver and Gold relations.

Generated SQL must:

1. parse as exactly one PostgreSQL query
2. be read-only
3. use schema-qualified physical relations
4. reference only relations present in the governed catalog
5. avoid Bronze, `public`, `information_schema`, and `pg_catalog`
6. pass SQLGlot AST and relation-scope validation
7. execute through the read-only database path
8. respect statement timeouts and row limits

If validation fails, SQL is not executed.

## HTTP boundary

`POST /query` is protected with:

```text
X-API-Key: <SERVICE_API_KEY>
```

The service key is separate from outbound API-ingestion credentials.

`/health` and `/ready` remain public so infrastructure probes do not require application credentials.

## Error handling

Public HTTP errors are sanitized. Internal exception text, credentials, raw provider errors, database passwords, stack traces, and internal filesystem paths are not returned to callers.

## Observability privacy

Structured HTTP logs intentionally exclude:

- request bodies
- user prompts
- LLM responses
- `X-API-Key`
- arbitrary HTTP headers
- database credentials
- raw exception messages
