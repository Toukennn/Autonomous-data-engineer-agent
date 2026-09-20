import os
import threading

from fastapi import (
    FastAPI,
    HTTPException,
)

from langchain_core.messages import (
    HumanMessage,
)

from pydantic import (
    BaseModel,
    Field,
    field_validator,
)

from config.settings import (
    get_database_settings,
    get_runtime_settings,
)

from utils.database import (
    DatabaseUtil,
)


# ============================================================
# APPLICATION
# ============================================================

app = FastAPI(
    title=(
        "Autonomous Data Engineer Agent"
    ),
    description=(
        "Governed agentic data engineering "
        "and warehouse analytics API."
    ),
    version="0.1.0",
)


# ============================================================
# SINGLE-PROCESS EXECUTION GUARD
# ============================================================
#
# The current runtime uses:
#
# - local checkpoint files
# - local lineage
# - local observability
# - generated dbt files
# - an in-process dbt lock
#
# Therefore we deliberately serialize agent runs
# inside one process for the first deployment.
#
# Docker must initially run ONE Uvicorn worker.
# ============================================================

_AGENT_EXECUTION_LOCK = (
    threading.Lock()
)


# ============================================================
# READINESS LIMITS
# ============================================================
#
# Readiness must fail quickly.
#
# These limits are intentionally much smaller than normal
# analytical-query limits.
# ============================================================

_READINESS_DB_CONNECT_TIMEOUT_SECONDS = 3

_READINESS_DB_STATEMENT_TIMEOUT_MS = 2_000


# ============================================================
# API SCHEMAS
# ============================================================


class AgentRequest(
    BaseModel
):
    message: str = Field(
        min_length=1,
        max_length=20_000,
    )

    @field_validator(
        "message"
    )
    @classmethod
    def validate_message(
        cls,
        value: str,
    ) -> str:

        normalized = (
            value.strip()
        )

        if not normalized:
            raise ValueError(
                "Message cannot be blank."
            )

        return normalized


class AgentResponse(
    BaseModel
):
    response: str


class HealthResponse(
    BaseModel
):
    status: str


class ReadinessResponse(
    BaseModel
):
    status: str


# ============================================================
# LAZY AGENT LOADING
# ============================================================


def _get_data_engineer():
    """
    Import the LangGraph application lazily.

    This allows infrastructure endpoints such as
    /health and /ready to work without constructing
    LLM clients during module import.
    """

    from agents.data_engineer import (
        data_engineer,
    )

    return data_engineer


# ============================================================
# RESPONSE VALIDATION
# ============================================================


def _extract_final_response(
    result: dict,
) -> str:
    """
    Extract one textual final response from the
    top-level Data Engineer graph.
    """

    if not isinstance(
        result,
        dict,
    ):
        raise RuntimeError(
            "Agent returned an invalid result."
        )

    messages = (
        result.get(
            "messages"
        )
    )

    if (
        not isinstance(
            messages,
            list,
        )
        or not messages
    ):
        raise RuntimeError(
            "Agent returned no final message."
        )

    content = getattr(
        messages[-1],
        "content",
        None,
    )

    if (
        not isinstance(
            content,
            str,
        )
        or not content.strip()
    ):
        raise RuntimeError(
            "Agent returned an invalid "
            "final response."
        )

    return content


# ============================================================
# READINESS CHECKS
# ============================================================


def _check_runtime_storage_ready() -> None:
    """
    Verify that the application runtime storage
    exists and is writable.

    No runtime path is exposed through the HTTP
    response if this check fails.
    """

    runtime_settings = (
        get_runtime_settings()
    )

    data_root = (
        runtime_settings.data_root
    )

    if (
        not data_root.exists()
        or not data_root.is_dir()
    ):
        raise RuntimeError(
            "Runtime storage is unavailable."
        )

    if not os.access(
        data_root,
        os.W_OK | os.X_OK,
    ):
        raise RuntimeError(
            "Runtime storage is not writable."
        )


def _check_database_ready() -> None:
    """
    Verify that PostgreSQL is reachable using a
    short connection and statement timeout.

    The readiness probe performs only a deterministic
    read-only SELECT 1.
    """

    database_config = (
        get_database_settings()
        .psycopg_config()
    )

    database_config[
        "connect_timeout"
    ] = (
        _READINESS_DB_CONNECT_TIMEOUT_SECONDS
    )

    database = (
        DatabaseUtil(
            database_config
        )
    )

    result = (
        database
        .execute_read_only_result(
            "SELECT 1 AS ready",
            statement_timeout_ms=(
                _READINESS_DB_STATEMENT_TIMEOUT_MS
            ),
            max_rows=1,
        )
    )

    if (
        result.row_count != 1
        or result.rows != (
            (1,),
        )
    ):
        raise RuntimeError(
            "Database readiness check failed."
        )


# ============================================================
# LIVENESS
# ============================================================


@app.get(
    "/health",
    response_model=HealthResponse,
)
def health() -> HealthResponse:
    """
    Lightweight process-liveness endpoint.

    This intentionally does not contact:

    - PostgreSQL
    - the LLM
    - external APIs
    """

    return HealthResponse(
        status="ok"
    )


# ============================================================
# READINESS
# ============================================================


@app.get(
    "/ready",
    response_model=ReadinessResponse,
)
def ready() -> ReadinessResponse:
    """
    Determine whether this application instance can
    currently accept governed agent work.

    Readiness requires:

    - usable runtime storage
    - reachable PostgreSQL

    Raw internal errors are deliberately not exposed.
    """

    try:

        _check_runtime_storage_ready()

        _check_database_ready()

    except Exception:

        raise HTTPException(
            status_code=503,
            detail=(
                "Service is not ready."
            ),
        ) from None

    return ReadinessResponse(
        status="ready"
    )


# ============================================================
# AGENT REQUEST
# ============================================================


@app.post(
    "/query",
    response_model=AgentResponse,
)
def query(
    request: AgentRequest,
) -> AgentResponse:
    """
    Execute one governed Data Engineer request.

    The current runtime intentionally allows only
    one agent execution at a time because local
    checkpoints, generated dbt files, lineage,
    observability, and process-local locks are not
    yet designed for concurrent runs.

    If the execution slot is already occupied, the
    request fails immediately instead of waiting in
    an unbounded in-process queue.
    """

    acquired = (
        _AGENT_EXECUTION_LOCK.acquire(
            blocking=False
        )
    )

    if not acquired:
        raise HTTPException(
            status_code=503,
            detail=(
                "Agent service is busy."
            ),
            headers={
                "Retry-After": "5",
            },
        )

    try:

        data_engineer = (
            _get_data_engineer()
        )

        result = (
            data_engineer.invoke(
                {
                    "messages": [
                        HumanMessage(
                            content=(
                                request.message
                            )
                        )
                    ]
                }
            )
        )

        response = (
            _extract_final_response(
                result
            )
        )

    except Exception:

        raise HTTPException(
            status_code=500,
            detail=(
                "Agent request failed."
            ),
        ) from None

    finally:

        _AGENT_EXECUTION_LOCK.release()

    return AgentResponse(
        response=response
    )