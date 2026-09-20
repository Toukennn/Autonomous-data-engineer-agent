# Phase 2H — dbt Integration ✅

## Goal

Add governed warehouse transformations through dynamically generated dbt models while keeping SQL/Jinja generation bounded.

## Implemented

- dynamic Bronze source generation
- generated Silver models
- generated Gold marts
- bounded dbt execution
- synchronized dbt tests
- safe artifact parsing
- deterministic model metadata
- controlled selectors and project/profile paths

## Planner/executor model

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
    ↓
bounded dbt execution
```

The LLM does not receive unrestricted dbt commands, SQL generation, or arbitrary Jinja execution.

## Result

dbt becomes part of the agentic workflow without becoming an unrestricted tool surface.
