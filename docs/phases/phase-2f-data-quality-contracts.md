# Phase 2F — Data Quality + Contracts ✅

## Goal

Represent quality requirements as typed contracts instead of free-form LLM instructions.

## Supported rule families

```text
not_null
unique
accepted_values
range
row_count
```

## Behavior

Contracts are stored and enforced by deterministic application code and can be synchronized into dbt tests.

The model cannot silently weaken an established contract or bypass required quality checks.

## Result

Quality expectations become durable configuration with deterministic enforcement rather than transient prompt text.
