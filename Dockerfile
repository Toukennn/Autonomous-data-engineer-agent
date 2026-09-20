# ============================================================
# AUTONOMOUS DATA ENGINEER AGENT
# ============================================================

FROM python:3.12-slim


# ============================================================
# UV
# ============================================================
#
# Pin uv rather than using a mutable "latest" image.
# ============================================================

COPY --from=ghcr.io/astral-sh/uv:0.8.22 \
    /uv \
    /uvx \
    /bin/


# ============================================================
# PYTHON / UV RUNTIME
# ============================================================

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    DATA_ROOT=/app/data \
    PATH="/app/.venv/bin:$PATH"


WORKDIR /app


# ============================================================
# NON-ROOT RUNTIME USER
# ============================================================

RUN groupadd \
        --system \
        --gid 10001 \
        appuser \
    && useradd \
        --system \
        --uid 10001 \
        --gid 10001 \
        --no-create-home \
        --shell /usr/sbin/nologin \
        appuser


# ============================================================
# DEPENDENCY LAYER
# ============================================================
#
# Keep this before application source COPY so dependency
# installation can remain cached when only source code changes.
# ============================================================

COPY pyproject.toml uv.lock README.md ./

RUN uv sync \
    --locked \
    --no-dev \
    --no-install-project


# ============================================================
# APPLICATION SOURCE
# ============================================================

COPY agents ./agents
COPY app ./app
COPY config ./config
COPY models ./models
COPY utils ./utils
COPY dbt ./dbt_seed
COPY scripts/container_entrypoint.py \
    ./scripts/container_entrypoint.py


# ============================================================
# INSTALL PROJECT
# ============================================================

RUN uv sync \
    --locked \
    --no-dev


# ============================================================
# PERSISTENT RUNTIME ROOT
# ============================================================
#
# All durable filesystem state is routed through one runtime
# root so cloud platforms only need one persistent volume.
# ============================================================

ENV PERSIST_ROOT=/app/runtime \
    HOME=/app/runtime/home


RUN mkdir -p \
        /app/runtime/data \
        /app/runtime/home \
        /app/runtime/dbt/generated_metadata \
        /app/runtime/dbt/models/sources \
        /app/runtime/dbt/models/staging/generated \
        /app/runtime/dbt/models/marts/generated \
    && ln -s \
        /app/runtime/data \
        /app/data \
    && ln -s \
        /app/runtime/dbt \
        /app/dbt \
    && chown -R \
        appuser:appuser \
        /app/runtime

# ============================================================
# NON-ROOT EXECUTION
# ============================================================

USER appuser


# ============================================================
# HTTP
# ============================================================

EXPOSE 8000


# ============================================================
# CONTAINER HEALTH CHECK
# ============================================================
#
# Uses only the Python standard library.
# No curl dependency is required.
# ============================================================

HEALTHCHECK \
    --interval=30s \
    --timeout=5s \
    --start-period=10s \
    --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).read()"]


# ============================================================
# APPLICATION ENTRYPOINT
# ============================================================
#
# IMPORTANT:
#
# Keep one worker for now.
#
# The application currently has:
# - local durable state
# - generated dbt runtime files
# - process-local execution locks
#
# Multi-worker deployment comes only after those concurrency
# boundaries are redesigned.
# ============================================================

ENTRYPOINT ["python", "/app/scripts/container_entrypoint.py"]

CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]