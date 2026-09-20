import json
import logging
import sys


# ============================================================
# LOGGER
# ============================================================

logger = logging.getLogger(
    "autonomous_data_engineer.http"
)

logger.setLevel(
    logging.INFO
)

logger.propagate = False


if not logger.handlers:

    handler = (
        logging.StreamHandler(
            sys.stdout
        )
    )

    handler.setFormatter(
        logging.Formatter(
            "%(message)s"
        )
    )

    logger.addHandler(
        handler
    )


# ============================================================
# STRUCTURED EVENT
# ============================================================


def emit_http_event(
    *,
    event: str,
    request_id: str,
    run_id: str | None = None,
    method: str | None = None,
    path: str | None = None,
    status_code: int | None = None,
    duration_ms: float | None = None,
) -> None:
    """
    Emit one safe structured application event.

    Only explicitly approved operational metadata
    can be included.

    Never include:

    - request bodies
    - prompts
    - API keys
    - HTTP headers
    - database credentials
    - raw exception messages
    - LLM responses
    """

    payload = {
        "event": event,
        "request_id": request_id,
    }

    if run_id is not None:
        payload[
            "run_id"
        ] = run_id

    if method is not None:
        payload[
            "method"
        ] = method

    if path is not None:
        payload[
            "path"
        ] = path

    if status_code is not None:
        payload[
            "status_code"
        ] = status_code

    if duration_ms is not None:
        payload[
            "duration_ms"
        ] = round(
            max(
                duration_ms,
                0.0,
            ),
            3,
        )

    try:

        logger.info(
            json.dumps(
                payload,
                sort_keys=True,
                separators=(
                    ",",
                    ":",
                ),
            )
        )

    except Exception:

        # Observability must never make the
        # application workflow fail.

        pass
