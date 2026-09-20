# Phase 2M — Real Cloud Deployment ✅

## Goal

Validate the complete platform outside the local development environment through a real HTTPS deployment with persistent state and managed PostgreSQL.

## Deployment

The application is deployed on Railway with:

```text
public HTTPS application
        +
private managed PostgreSQL
        +
persistent /app/runtime volume
```

The PostgreSQL service is intentionally not publicly exposed.

## Completed milestones

```text
2M.1   Single-volume cloud persistence             ✅
2M.2   Railway project                             ✅
2M.3   Managed PostgreSQL                          ✅
2M.4   Runtime variables and secret configuration  ✅
2M.5   Persistent /app/runtime volume              ✅
2M.6   /health deployment health check             ✅
2M.7   Public HTTPS domain                         ✅
2M.8   Remote /health + /ready + auth validation   ✅
2M.9   Real remote ETL + governed SQL demo         ✅
2M.10  Restart/persistence validation              ✅
```

## Public endpoints

- Swagger/OpenAPI: `https://autonomous-data-engineer-agent-production.up.railway.app/docs`
- Liveness: `https://autonomous-data-engineer-agent-production.up.railway.app/health`
- Readiness: `https://autonomous-data-engineer-agent-production.up.railway.app/ready`
- Agent: `POST https://autonomous-data-engineer-agent-production.up.railway.app/query`

## Verified remote E2E

A representative deployment test used:

```text
https://randomuser.me/api/?results=5
```

with records under:

```text
results
```

The requested Gold output contained exactly:

```text
gender
email
phone
```

The deployed path successfully verified:

- authenticated HTTPS `/query`
- `X-Request-ID` and `X-Run-ID`
- external API extraction
- durable Bronze persistence
- PostgreSQL Bronze synchronization
- dbt Silver build
- dbt Gold build
- exactly 5 Gold rows
- governed SQL validation
- read-only SQL execution
- retrieval of actual Gold values
- persisted SQL execution records

## Restart persistence

The application service was restarted and the previously created warehouse data remained queryable.

This verifies that application restart does not erase the durable runtime state or managed PostgreSQL data.

## Runtime home fix

Cloud execution exposed a dbt runtime issue because the non-root UID `10001` process inherited an unwritable root home. The image/runtime now provides:

```text
HOME=/app/runtime/home
```

and the persistent runtime tree is prepared before privileges are dropped.

## Result

Phase 2M proves the architecture through the real public boundary rather than only through local Docker or CI.
