# Documentation

This folder contains the detailed technical documentation for the Autonomous Data Engineer Agent. The root `README.md` is intentionally concise; implementation history and subsystem details live here.

## Core documentation

- [Architecture](architecture.md)
- [Safety Model](safety-model.md)
- [Running & Configuration](running-and-configuration.md)
- [Testing & Operations](testing-and-operations.md)
- [Limitations & Roadmap](limitations-and-roadmap.md)

## Development phases

| Phase | Document |
|---|---|
| 2A | [Reliable API Ingestion](phases/phase-2a-reliable-api-ingestion.md) |
| 2B | [Persistent Incremental Ingestion](phases/phase-2b-persistent-incremental-ingestion.md) |
| 2C | [Schema Evolution](phases/phase-2c-schema-evolution.md) |
| 2D | [Medallion Architecture + Lineage](phases/phase-2d-medallion-lineage.md) |
| 2E | [Agent Runtime Reliability + CI](phases/phase-2e-runtime-reliability-ci.md) |
| 2F | [Data Quality + Contracts](phases/phase-2f-data-quality-contracts.md) |
| 2G | [PostgreSQL Warehouse Bridge](phases/phase-2g-postgresql-warehouse-bridge.md) |
| 2H | [dbt Integration](phases/phase-2h-dbt-integration.md) |
| 2I | [Governed Warehouse Analytics](phases/phase-2i-governed-warehouse-analytics.md) |
| 2J | [Incremental Warehouse Processing](phases/phase-2j-incremental-warehouse-processing.md) |
| 2K | [Containerized Runtime & Deployment Foundation](phases/phase-2k-containerized-runtime.md) |
| 2L | [Production API Hardening](phases/phase-2l-production-api-hardening.md) |
| 2M | [Real Cloud Deployment](phases/phase-2m-real-cloud-deployment.md) |
| 2R | [Final Validation + Release Polish](phases/phase-2r-final-validation-release.md) |

## Design principle

> **LLMs decide what should happen. Deterministic code decides how it is allowed to happen.**

The documentation repeatedly returns to this boundary because it is the central design choice of the project.
