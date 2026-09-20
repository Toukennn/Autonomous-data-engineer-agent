# Limitations & Roadmap

## Current v1 durability model

The portfolio deployment combines:

- a persistent application volume
- managed PostgreSQL
- generated dbt runtime files
- persistent checkpoints, lineage, and execution records

This model is intentionally designed for a **single-instance deployment**.

The application runs one Uvicorn worker because coordination is process-local.

## Current limitations

Version 1 is intentionally bounded:

- one application process / one Uvicorn worker
- one active agent execution at a time
- synchronous `/query` execution
- HTTP timeout does not forcibly cancel an already-running Python worker
- checkpoints, lineage, execution records, and generated dbt state rely on one persistent application volume
- no distributed task queue
- no horizontal multi-replica coordination
- no advanced CDC deletion/tombstone semantics
- no SCD Type 2 history modeling
- no heavy centralized metrics/tracing stack
- semantic grounding of arbitrary user-supplied dataset names can still be strengthened

These are explicit scope boundaries rather than hidden production claims.

## Completed phases

| Phase | Scope | Status |
|---|---|---|
| 2A | Reliable API ingestion | ✅ |
| 2B | Persistent incremental ingestion | ✅ |
| 2C | Schema evolution | ✅ |
| 2D | Medallion architecture + lineage | ✅ |
| 2E | Agent runtime reliability + CI | ✅ |
| 2F | Data quality + contracts | ✅ |
| 2G | PostgreSQL warehouse bridge | ✅ |
| 2H | dbt integration | ✅ |
| 2I | Governed warehouse analytics | ✅ |
| 2J | Incremental warehouse processing | ✅ |
| 2K | FastAPI + Docker + Compose + container CI | ✅ |
| 2L | Production API hardening | ✅ |
| 2M | Railway cloud deployment + remote E2E validation | ✅ |

## Final v1 milestone

Phase 2R contains release polish:

- final architecture/documentation
- optional short GIF/video demo
- final regression run
- small semantic-grounding cleanup where useful
- `v1.0.0` release/tag

## Optional post-v1 work

Potential extensions that are deliberately not blockers:

- centralized metrics/tracing stack
- LLM cost dashboards
- asynchronous job queue / worker model
- externally coordinated distributed state
- multi-replica execution
- deletion/tombstone handling
- SCD Type 2 history
- row-level quarantine datasets
- richer lineage backends
- external workflow orchestration
- deeper enterprise security controls
