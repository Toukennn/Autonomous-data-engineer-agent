# Phase 2A — Reliable API Ingestion ✅

## Goal

Move HTTP behavior out of the agent layer and into a deterministic ingestion boundary so the model does not directly control networking behavior.

## Implemented

- top-level JSON arrays
- nested record paths
- controlled JSON validation
- retries and exponential backoff
- `Retry-After`
- transient `429` / `5xx` handling
- optional outbound token authentication
- configurable authentication header/scheme
- response/page/record limits
- pagination-loop detection
- redirect limits
- SSRF/public-destination validation
- authenticated redirect restrictions
- normalized external API errors

Authenticated outbound requests require HTTPS.

## Result

The LLM can choose a supported extraction workflow, but deterministic application code owns HTTP execution, retry policy, pagination limits, redirect policy, response limits, and network-safety checks.

## Design boundary

```text
LLM
  ↓
logical extraction intent
  ↓
deterministic API client
  ├── validation
  ├── retries
  ├── limits
  ├── redirect policy
  └── SSRF/public-destination checks
```
