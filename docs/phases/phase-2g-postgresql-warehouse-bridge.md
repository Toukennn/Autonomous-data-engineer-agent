# Phase 2G — PostgreSQL Warehouse Bridge ✅

## Goal

Bridge durable Bronze data into PostgreSQL while preserving deterministic load semantics.

## Target

```text
bronze.<dataset>
```

## Loading modes

```text
refresh_in_place
merge_upsert
```

`merge_upsert` is selected only when a trusted business-key contract exists.

The application—not the LLM—owns:

- physical PostgreSQL schema choice
- merge SQL
- uniqueness enforcement
- load-mode selection from trusted metadata

## Result

The file-backed ingestion path becomes a durable warehouse-backed pipeline without handing arbitrary write-SQL authority to the model.
