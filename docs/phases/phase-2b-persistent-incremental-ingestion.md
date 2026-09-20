# Phase 2B — Persistent Incremental Ingestion ✅

## Goal

Support incremental ingestion across separate executions while keeping checkpoint ownership deterministic.

## Persistent state

Watermark checkpoints are stored under:

```text
data/_state/
```

The LLM may identify logical incremental fields, but deterministic code owns checkpoint loading, comparison, and advancement.

Checkpoint state advances only after required durable writes succeed.

## Retry and merge semantics

```text
no business key
    → exact-row deduplication

business key configured
    → incoming rows replace historical rows with the same key
```

## Safety property

A failed downstream durable write must not incorrectly advance the checkpoint.

This binds incremental progress to successful persistence rather than to the LLM's intention or the moment an API response is received.
