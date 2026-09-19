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


# ============================================================
# LAZY AGENT LOADING
# ============================================================


def _get_data_engineer():
    """
    Import the LangGraph application lazily.

    This allows infrastructure endpoints such as
    /health to start without constructing LLM
    clients during module import.
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
# HEALTH
# ============================================================


@app.get(
    "/health",
    response_model=HealthResponse,
)
def health() -> HealthResponse:
    """
    Lightweight process health endpoint.

    This intentionally does not contact the LLM
    or PostgreSQL.
    """

    return HealthResponse(
        status="ok"
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

    The API accepts only the natural-language
    request. All physical execution boundaries
    remain application-controlled.
    """

    try:

        with _AGENT_EXECUTION_LOCK:

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

        # Do not expose raw:
        #
        # - database errors
        # - credentials
        # - LLM provider errors
        # - filesystem paths
        # - internal stack traces
        #
        # through the HTTP boundary.

        raise HTTPException(
            status_code=500,
            detail=(
                "Agent request failed."
            ),
        ) from None

    return AgentResponse(
        response=response
    )
