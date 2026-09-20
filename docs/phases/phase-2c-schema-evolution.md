# Phase 2C — Schema Evolution ✅

## Goal

Handle compatible schema drift while deterministically rejecting unsafe changes.

## Transition policy

```text
same schema          → ACCEPT
added columns only   → ACCEPT
removed columns      → REJECT
logical type change  → REJECT
```

## Implemented

- drift detection
- additive schema evolution
- logical dtype normalization
- schema fingerprints
- schema history
- deterministic rejection reports

## Result

The pipeline can continue through additive changes without allowing the model to silently reinterpret removals or incompatible type changes.
