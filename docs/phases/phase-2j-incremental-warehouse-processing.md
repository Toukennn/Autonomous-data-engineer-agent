# Phase 2J — Incremental Warehouse Processing ✅

## Goal

Extend incremental semantics beyond file-backed ingestion into PostgreSQL and dbt processing.

## Implemented

```text
2J.1   Typed business-key contracts
2J.2   PostgreSQL Bronze merge/upsert
2J.3   Checkpoint ↔ Bronze consistency binding
2J.4   Governed dbt incremental materialization
2J.5   Incremental lineage and observability
2J.6A  Business-key-aware durable Bronze merge
2J.6B  Two-run incremental E2E validation
```

## Key behavior

The two-run E2E path verifies that a subsequent run updates/inserts the correct rows without incorrectly rebuilding or duplicating the logical dataset.

Incremental dbt materialization is selected through deterministic eligibility rules rather than by arbitrary model choice.

## Result

Incremental behavior is consistent across API ingestion, durable Bronze state, PostgreSQL, dbt, lineage, and observability.
