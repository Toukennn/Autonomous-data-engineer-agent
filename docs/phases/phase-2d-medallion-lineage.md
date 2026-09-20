# Phase 2D — Medallion Architecture + Lineage ✅

## Goal

Introduce explicit Bronze, Silver, and Gold boundaries and persist deterministic lineage across transformations.

## File-backed Medallion structure

```text
data/bronze/<dataset>/
data/silver/<dataset>/
data/gold/<dataset>/
```

Bronze stores source data and extraction/schema metadata. Silver consumes Bronze. Gold consumes Silver.

## Lineage

Deterministic lineage is persisted under:

```text
data/_lineage/lineage.json
```

Lineage events cover extraction, transformation, curation, warehouse synchronization, and dbt build activity.

## Result

Dataset promotion is explicit and auditable rather than being an implicit sequence of ad-hoc agent operations.
