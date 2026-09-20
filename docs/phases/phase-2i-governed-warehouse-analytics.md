# Phase 2I — Governed Warehouse Analytics ✅

## Goal

Allow natural-language analytics over the warehouse while deterministically constraining what SQL can execute.

## Implemented

- governed analytics catalog
- Silver/Gold relation discovery
- SQL generation from catalog context
- SQLGlot AST validation
- schema/relation allowlisting
- read-only execution
- result-row limits
- SQL execution observability
- end-to-end governed analytics validation

## Execution path

```text
natural-language question
        ↓
governed analytics catalog
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
        bounded result
```

The same catalog snapshot is used for prompt context and deterministic validation.

## Result

The model can propose analytical SQL but cannot authorize its own query.
