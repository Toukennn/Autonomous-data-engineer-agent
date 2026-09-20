import os
import threading
import secrets
from time import (
    perf_counter,
)
from uuid import uuid4

from concurrent.futures import (
    ThreadPoolExecutor,
    wait,
)

from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    Request,
    Response,
    Security,
)

from fastapi.security import (
    APIKeyHeader,
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
    get_service_api_settings,
)

from utils.database import (
    DatabaseUtil,
)

from utils.http_observability import (
    emit_http_event,
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
    version="1.0.0",
)

@app.middleware(
    "http"
)
async def add_request_id(
    request: Request,
    call_next,
):
    """
    Assign one server-generated request ID and
    emit a safe structured HTTP completion event.

    Request bodies, headers, credentials, and
    exception details are deliberately excluded.
    """

    request_id = (
        uuid4().hex
    )

    request.state.request_id = (
        request_id
    )

    started_at = (
        perf_counter()
    )

    status_code = 500

    try:

        response = await call_next(
            request
        )

        status_code = (
            response.status_code
        )

        response.headers[
            "X-Request-ID"
        ] = request_id

        return response

    finally:

        duration_ms = (
            (
                perf_counter()
                - started_at
            )
            * 1000
        )

        emit_http_event(
            event=(
                "http_request.completed"
            ),
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            status_code=status_code,
            duration_ms=duration_ms,
        )


_SERVICE_API_KEY_HEADER = (
    APIKeyHeader(
        name="X-API-Key",
        auto_error=False,
    )
)

def _require_service_api_key(
    api_key: str | None = Security(
        _SERVICE_API_KEY_HEADER
    ),
) -> None:
    """
    Authenticate clients calling protected
    application endpoints.

    Health and readiness probes remain public.

    The configured secret is never returned or
    logged.
    """

    try:

        expected_api_key = (
            get_service_api_settings()
            .service_api_key
            .get_secret_value()
        )

    except Exception:

        # Fail closed if authentication was not
        # configured correctly.

        raise HTTPException(
            status_code=503,
            detail=(
                "Service authentication "
                "is not configured."
            ),
        ) from None

    if (
        api_key is None
        or not secrets.compare_digest(
            api_key,
            expected_api_key,
        )
    ):
        raise HTTPException(
            status_code=401,
            detail=(
                "Invalid API key."
            ),
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

_AGENT_EXECUTION_POOL = (
    ThreadPoolExecutor(
        max_workers=1,
        thread_name_prefix=(
            "agent-execution"
        ),
    )
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


def _execute_agent_request(
    message: str,
    request_id: str,
    run_id: str,
) -> str:
    """
    Execute one agent request inside the dedicated
    worker while emitting safe run-level
    observability.

    The user message itself is deliberately never
    logged.
    """

    started_at = (
        perf_counter()
    )

    emit_http_event(
        event="agent_run.started",
        request_id=request_id,
        run_id=run_id,
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
                            content=message
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

        duration_ms = (
            (
                perf_counter()
                - started_at
            )
            * 1000
        )

        emit_http_event(
            event="agent_run.failed",
            request_id=request_id,
            run_id=run_id,
            duration_ms=duration_ms,
        )

        raise

    else:

        duration_ms = (
            (
                perf_counter()
                - started_at
            )
            * 1000
        )

        emit_http_event(
            event=(
                "agent_run.completed"
            ),
            request_id=request_id,
            run_id=run_id,
            duration_ms=duration_ms,
        )

        return response

    finally:

        _AGENT_EXECUTION_LOCK.release()


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
    dependencies=[
        Depends(
            _require_service_api_key
        )
    ],
)
def query(
    request: AgentRequest,
    http_request: Request,
    http_response: Response,
) -> AgentResponse:
    """
    Execute one governed Data Engineer request.

    Only one agent execution may run at a time.

    The HTTP request has a bounded wait time.
    If that deadline is exceeded, the client
    receives 504 while the execution slot remains
    unavailable until the underlying worker
    actually terminates.
    """

    request_id = (
        http_request
        .state
        .request_id
    )

    acquired = (
        _AGENT_EXECUTION_LOCK.acquire(
            blocking=False
        )
    )

    if not acquired:

        emit_http_event(
            event="agent_run.busy",
            request_id=request_id,
            status_code=503,
        )

        raise HTTPException(
            status_code=503,
            detail=(
                "Agent service is busy."
            ),
            headers={
                "Retry-After": "5",
            },
        )

    run_id = (
        uuid4().hex
    )


    try:

        future = (
            _AGENT_EXECUTION_POOL.submit(
                _execute_agent_request,
                request.message,
                request_id,
                run_id,
            )
        )

    except Exception:

        # Submission failed before the worker
        # became responsible for releasing
        # the execution lock.

        _AGENT_EXECUTION_LOCK.release()

        emit_http_event(
            event=(
                "agent_run.submission_failed"
            ),
            request_id=request_id,
            run_id=run_id,
            status_code=500,
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "Agent request failed."
            ),
            headers={
                "X-Run-ID": run_id,
            },
        ) from None

    timeout_seconds = (
        get_runtime_settings()
        .agent_request_timeout_seconds
    )

    wait_started_at = (
        perf_counter()
    )

    completed, _ = wait(
        {future},
        timeout=timeout_seconds,
    )

    if not completed:

        # Important:
        #
        # Do NOT release the execution lock here.
        #
        # Python threads cannot be safely terminated.
        # The worker may still be modifying durable
        # application state.
        #
        # _execute_agent_request() releases the lock
        # only after the real execution ends.

        duration_ms = (
            (
                perf_counter()
                - wait_started_at
            )
            * 1000
        )

        emit_http_event(
            event=(
                "agent_run.http_timeout"
            ),
            request_id=request_id,
            run_id=run_id,
            status_code=504,
            duration_ms=duration_ms,
        )

        raise HTTPException(
            status_code=504,
            detail=(
                "Agent request timed out."
            ),
            headers={
                "X-Run-ID": run_id,
            },
        )

    try:

        response = (
            future.result()
        )

    except Exception:

        raise HTTPException(
            status_code=500,
            detail=(
                "Agent request failed."
            ),
            headers={
                "X-Run-ID": run_id,
            },
        ) from None

    http_response.headers[
        "X-Run-ID"
    ] = run_id

    return AgentResponse(
        response=response
    )