# Running & Configuration

## Docker Compose

Docker Compose is the recommended way to reproduce the full application + PostgreSQL runtime.

Copy the example environment file:

```bash
cp .env.example .env
```

Configure at minimum:

```env
OPENAI_API_KEY=...
ANTHROPIC_API_KEY=...

DB_USER=...
DB_PASSWORD=...
DB_NAME=...

SERVICE_API_KEY=...
```

Generate a strong inbound key:

```bash
uv run python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Start:

```bash
docker compose up -d --build
```

Check:

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/ready
```

Stop:

```bash
docker compose down
```

Remove the stack and named volumes:

```bash
docker compose down -v
```

Use `-v` carefully because it removes persisted PostgreSQL/application state.

## Local Python runtime

```bash
uv sync --locked --python 3.12
uv run uvicorn app.api:app --host 0.0.0.0 --port 8000
```

PostgreSQL and the required environment configuration must be available separately.

## HTTP API

### Liveness

```bash
curl http://127.0.0.1:8000/health
```

Expected:

```json
{"status":"ok"}
```

### Readiness

```bash
curl http://127.0.0.1:8000/ready
```

Expected when dependencies are ready:

```json
{"status":"ready"}
```

### Agent query

```bash
curl \
  -X POST \
  http://127.0.0.1:8000/query \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $SERVICE_API_KEY" \
  -d '{"message":"Build a warehouse-backed pipeline from an external API."}'
```

Cloud:

```bash
curl \
  -X POST \
  https://autonomous-data-engineer-agent-production.up.railway.app/query \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $SERVICE_API_KEY" \
  -d '{"message":"How many rows are in my Gold dataset? Use the governed warehouse analytics path."}'
```

## Configuration

The project uses environment-backed Pydantic settings.

### LLM providers

```env
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
```

### PostgreSQL

```env
DB_HOST=localhost
DB_PORT=5432
DB_USER=
DB_PASSWORD=
DB_NAME=
```

### SQL safety

```env
SQL_STATEMENT_TIMEOUT_MS=10000
SQL_MAX_ROWS=1000
```

### Outbound API ingestion

```env
HTTP_TIMEOUT_SECONDS=30
API_MAX_RESPONSE_BYTES=20000000
API_MAX_TOTAL_RESPONSE_BYTES=100000000
API_MAX_PAGES=50
API_MAX_RECORDS=100000
API_RETRY_TOTAL=4
API_RETRY_BACKOFF_SECONDS=0.5
API_USER_AGENT=autonomous-data-engineer-agent/0.1

API_AUTH_TOKEN=
API_AUTH_HEADER=Authorization
API_AUTH_SCHEME=Bearer
API_MAX_REDIRECTS=5
```

`API_AUTH_*` is for **outbound external API authentication**.

### Agent runtime safety

```env
ETL_MAX_TOOL_CALLS=8
AGENT_REQUEST_TIMEOUT_SECONDS=600
```

### dbt

```env
DBT_TARGET_SCHEMA=dbt_dev
DBT_THREADS=4
```

### Inbound service authentication

```env
SERVICE_API_KEY=replace_with_a_random_secret_at_least_32_characters
```

Never commit the real `.env`.

## Runtime persistence

Local:

```text
<project>/data
```

Docker/cloud logical path:

```text
/app/data
```

In the current image, `/app/data` resolves into:

```text
/app/runtime/data
```

The generated dbt project/runtime state also lives under `/app/runtime`.
