from uuid import (
    UUID,
)

from fastapi.testclient import (
    TestClient,
)

from langchain_core.messages import (
    AIMessage,
)

import pytest

from pydantic import (
    SecretStr,
)

from app import api
import threading

class FakeDataEngineer:
    def __init__(
        self,
    ):
        self.calls = []

    def invoke(
        self,
        payload,
    ):
        self.calls.append(
            payload
        )

        return {
            "messages": [
                AIMessage(
                    content=(
                        "Pipeline completed."
                    )
                )
            ]
        }

TEST_SERVICE_API_KEY = (
    "test-service-api-key-0123456789abcdef"
)


class FakeServiceAPISettings:
    service_api_key = SecretStr(
        TEST_SERVICE_API_KEY
    )


def _authenticated_client():
    client = TestClient(
        api.app
    )

    client.headers.update(
        {
            "X-API-Key": (
                TEST_SERVICE_API_KEY
            )
        }
    )

    return client


def _assert_uuid4_header(
    response,
    header_name: str,
) -> str:
    value = (
        response.headers[
            header_name
        ]
    )

    parsed = UUID(
        value
    )

    assert (
        parsed.version
        == 4
    )

    return value


# ============================================================
# HEALTH
# ============================================================


def test_health_endpoint():
    client = TestClient(
        api.app
    )

    response = client.get(
        "/health"
    )

    assert (
        response.status_code
        == 200
    )

    assert response.json() == {
        "status": "ok"
    }

    _assert_uuid4_header(
        response,
        "X-Request-ID",
    )


def test_request_ids_are_unique():
    client = TestClient(
        api.app
    )

    first = client.get(
        "/health"
    )

    second = client.get(
        "/health"
    )

    first_id = (
        _assert_uuid4_header(
            first,
            "X-Request-ID",
        )
    )

    second_id = (
        _assert_uuid4_header(
            second,
            "X-Request-ID",
        )
    )

    assert (
        first_id
        != second_id
    )


def test_health_is_independent_of_readiness(
    monkeypatch,
):
    """
    Liveness must remain healthy even when
    dependencies are unavailable.
    """

    def fail_storage():
        raise RuntimeError(
            "Storage unavailable."
        )

    def fail_database():
        raise RuntimeError(
            "Database unavailable."
        )

    monkeypatch.setattr(
        api,
        "_check_runtime_storage_ready",
        fail_storage,
    )

    monkeypatch.setattr(
        api,
        "_check_database_ready",
        fail_database,
    )

    client = TestClient(
        api.app
    )

    response = client.get(
        "/health"
    )

    assert (
        response.status_code
        == 200
    )

    assert response.json() == {
        "status": "ok"
    }


# ============================================================
# READINESS
# ============================================================


def test_ready_endpoint(
    monkeypatch,
):
    monkeypatch.setattr(
        api,
        "_check_runtime_storage_ready",
        lambda: None,
    )

    monkeypatch.setattr(
        api,
        "_check_database_ready",
        lambda: None,
    )

    client = TestClient(
        api.app
    )

    response = client.get(
        "/ready"
    )

    assert (
        response.status_code
        == 200
    )

    assert response.json() == {
        "status": "ready"
    }


def test_ready_returns_503_when_storage_unavailable(
    monkeypatch,
):
    def fail_storage():
        raise RuntimeError(
            "Storage unavailable."
        )

    monkeypatch.setattr(
        api,
        "_check_runtime_storage_ready",
        fail_storage,
    )

    monkeypatch.setattr(
        api,
        "_check_database_ready",
        lambda: None,
    )

    client = TestClient(
        api.app
    )

    response = client.get(
        "/ready"
    )

    assert (
        response.status_code
        == 503
    )

    assert response.json() == {
        "detail": (
            "Service is not ready."
        )
    }


def test_ready_returns_503_when_database_unavailable(
    monkeypatch,
):
    def fail_database():
        raise RuntimeError(
            "DB_PASSWORD=super-secret"
        )

    monkeypatch.setattr(
        api,
        "_check_runtime_storage_ready",
        lambda: None,
    )

    monkeypatch.setattr(
        api,
        "_check_database_ready",
        fail_database,
    )

    client = TestClient(
        api.app
    )

    response = client.get(
        "/ready"
    )

    assert (
        response.status_code
        == 503
    )

    assert response.json() == {
        "detail": (
            "Service is not ready."
        )
    }

    assert (
        "super-secret"
        not in response.text
    )

    assert (
        "DB_PASSWORD"
        not in response.text
    )


# ============================================================
# QUERY
# ============================================================


def test_query_endpoint_invokes_data_engineer(
    monkeypatch,
):
    fake_agent = (
        FakeDataEngineer()
    )

    monkeypatch.setattr(
        api,
        "_get_data_engineer",
        lambda: fake_agent,
    )

    client = (
        _authenticated_client()
    )

    response = client.post(
        "/query",
        json={
            "message": (
                "Build an orders "
                "pipeline."
            )
        },
    )

    assert (
        response.status_code
        == 200
    )

    assert response.json() == {
        "response": (
            "Pipeline completed."
        )
    }

    request_id = (
        _assert_uuid4_header(
            response,
            "X-Request-ID",
        )
    )

    run_id = (
        _assert_uuid4_header(
            response,
            "X-Run-ID",
        )
    )

    assert (
        request_id
        != run_id
    )

    assert (
        len(
            fake_agent.calls
        )
        == 1
    )

    payload = (
        fake_agent.calls[0]
    )

    assert (
        payload[
            "messages"
        ][0].content
        == (
            "Build an orders "
            "pipeline."
        )
    )


def test_query_rejects_blank_message():
    client = (
        _authenticated_client()
    )

    response = client.post(
        "/query",
        json={
            "message": "   "
        },
    )

    assert (
        response.status_code
        == 422
    )


def test_query_does_not_expose_internal_errors(
    monkeypatch,
):
    class FailingAgent:
        def invoke(
            self,
            payload,
        ):
            raise RuntimeError(
                "DB_PASSWORD=super-secret"
            )

    monkeypatch.setattr(
        api,
        "_get_data_engineer",
        lambda: FailingAgent(),
    )

    client = (
        _authenticated_client()
    )

    response = client.post(
        "/query",
        json={
            "message": "Run ETL."
        },
    )

    assert (
        response.status_code
        == 500
    )

    assert response.json() == {
        "detail": (
            "Agent request failed."
        )
    }

    assert (
        "super-secret"
        not in response.text
    )


def test_query_returns_503_when_agent_is_busy(
    monkeypatch,
):
    fake_agent = (
        FakeDataEngineer()
    )

    monkeypatch.setattr(
        api,
        "_get_data_engineer",
        lambda: fake_agent,
    )

    acquired = (
        api._AGENT_EXECUTION_LOCK.acquire(
            blocking=False
        )
    )

    assert acquired is True

    try:

        client = (
            _authenticated_client()
        )

        response = client.post(
            "/query",
            json={
                "message": (
                    "Build an orders pipeline."
                )
            },
        )

        assert (
            response.status_code
            == 503
        )

        assert response.json() == {
            "detail": (
                "Agent service is busy."
            )
        }

        _assert_uuid4_header(
            response,
            "X-Request-ID",
        )

        assert (
            "X-Run-ID"
            not in response.headers
        )

        assert (
            response.headers[
                "Retry-After"
            ]
            == "5"
        )

        assert (
            len(
                fake_agent.calls
            )
            == 0
        )

    finally:

        api._AGENT_EXECUTION_LOCK.release()


def test_query_releases_lock_after_success(
    monkeypatch,
):
    fake_agent = (
        FakeDataEngineer()
    )

    monkeypatch.setattr(
        api,
        "_get_data_engineer",
        lambda: fake_agent,
    )

    client = (
        _authenticated_client()
    )

    first_response = client.post(
        "/query",
        json={
            "message": "First request."
        },
    )

    second_response = client.post(
        "/query",
        json={
            "message": "Second request."
        },
    )

    assert (
        first_response.status_code
        == 200
    )

    assert (
        second_response.status_code
        == 200
    )

    assert (
        len(
            fake_agent.calls
        )
        == 2
    )


def test_query_releases_lock_after_failure(
    monkeypatch,
):
    class FailingAgent:
        def invoke(
            self,
            payload,
        ):
            raise RuntimeError(
                "Internal failure."
            )

    monkeypatch.setattr(
        api,
        "_get_data_engineer",
        lambda: FailingAgent(),
    )

    client = (
        _authenticated_client()
    )

    failed_response = client.post(
        "/query",
        json={
            "message": "Fail."
        },
    )

    assert (
        failed_response.status_code
        == 500
    )

    fake_agent = (
        FakeDataEngineer()
    )

    monkeypatch.setattr(
        api,
        "_get_data_engineer",
        lambda: fake_agent,
    )

    successful_response = client.post(
        "/query",
        json={
            "message": "Try again."
        },
    )

    assert (
        successful_response.status_code
        == 200
    )


def test_query_times_out_but_keeps_execution_busy(
    monkeypatch,
):
    release_execution = (
        threading.Event()
    )

    execution_started = (
        threading.Event()
    )

    class SlowAgent:
        def invoke(
            self,
            payload,
        ):
            execution_started.set()

            release_execution.wait(
                timeout=5
            )

            return {
                "messages": [
                    AIMessage(
                        content=(
                            "Slow pipeline completed."
                        )
                    )
                ]
            }

    class FakeRuntimeSettings:
        agent_request_timeout_seconds = (
            0.01
        )

    monkeypatch.setattr(
        api,
        "_get_data_engineer",
        lambda: SlowAgent(),
    )

    monkeypatch.setattr(
        api,
        "get_runtime_settings",
        lambda: FakeRuntimeSettings(),
    )

    client = (
        _authenticated_client()
    )

    response = client.post(
        "/query",
        json={
            "message": (
                "Run a slow pipeline."
            )
        },
    )

    assert (
        execution_started.wait(
            timeout=1
        )
        is True
    )

    assert (
        response.status_code
        == 504
    )

    assert response.json() == {
        "detail": (
            "Agent request timed out."
        )
    }

    _assert_uuid4_header(
        response,
        "X-Request-ID",
    )

    _assert_uuid4_header(
        response,
        "X-Run-ID",
    )

    # --------------------------------------------------------
    # The timed-out execution is still running.
    #
    # A new request must therefore NOT be allowed
    # to start.
    # --------------------------------------------------------

    busy_response = client.post(
        "/query",
        json={
            "message": (
                "Start another pipeline."
            )
        },
    )

    assert (
        busy_response.status_code
        == 503
    )

    assert busy_response.json() == {
        "detail": (
            "Agent service is busy."
        )
    }

    # --------------------------------------------------------
    # Allow the original execution to finish.
    # --------------------------------------------------------

    release_execution.set()

    # Queue a marker behind the original worker.
    #
    # When this completes, we know that the slow
    # execution has completely left the dedicated
    # worker and released its execution lock.
    api._AGENT_EXECUTION_POOL.submit(
        lambda: None
    ).result(
        timeout=2
    )

    # --------------------------------------------------------
    # Service should now accept another request.
    # --------------------------------------------------------

    fake_agent = (
        FakeDataEngineer()
    )

    monkeypatch.setattr(
        api,
        "_get_data_engineer",
        lambda: fake_agent,
    )

    final_response = client.post(
        "/query",
        json={
            "message": (
                "Try again."
            )
        },
    )

    assert (
        final_response.status_code
        == 200
    )


@pytest.fixture(
    autouse=True
)
def configure_service_api_auth(
    monkeypatch,
):
    monkeypatch.setattr(
        api,
        "get_service_api_settings",
        lambda: FakeServiceAPISettings(),
    )


def test_query_rejects_missing_api_key(
    monkeypatch,
):
    fake_agent = (
        FakeDataEngineer()
    )

    monkeypatch.setattr(
        api,
        "_get_data_engineer",
        lambda: fake_agent,
    )

    client = TestClient(
        api.app
    )

    response = client.post(
        "/query",
        json={
            "message": (
                "Build a pipeline."
            )
        },
    )

    assert (
        response.status_code
        == 401
    )

    assert response.json() == {
        "detail": (
            "Invalid API key."
        )
    }

    assert (
        len(
            fake_agent.calls
        )
        == 0
    )


def test_query_rejects_invalid_api_key(
    monkeypatch,
):
    fake_agent = (
        FakeDataEngineer()
    )

    monkeypatch.setattr(
        api,
        "_get_data_engineer",
        lambda: fake_agent,
    )

    client = TestClient(
        api.app
    )

    response = client.post(
        "/query",
        headers={
            "X-API-Key": (
                "wrong-key"
            )
        },
        json={
            "message": (
                "Build a pipeline."
            )
        },
    )

    assert (
        response.status_code
        == 401
    )

    assert response.json() == {
        "detail": (
            "Invalid API key."
        )
    }

    assert (
        len(
            fake_agent.calls
        )
        == 0
    )


def test_query_emits_safe_structured_events(
    monkeypatch,
):
    events = []

    def capture_event(
        **kwargs,
    ):
        events.append(
            kwargs
        )

    monkeypatch.setattr(
        api,
        "emit_http_event",
        capture_event,
    )

    fake_agent = (
        FakeDataEngineer()
    )

    monkeypatch.setattr(
        api,
        "_get_data_engineer",
        lambda: fake_agent,
    )

    client = (
        _authenticated_client()
    )

    secret_prompt = (
        "TOP-SECRET-PROMPT-DO-NOT-LOG"
    )

    response = client.post(
        "/query",
        json={
            "message": (
                secret_prompt
            )
        },
    )

    assert (
        response.status_code
        == 200
    )

    event_names = {
        event[
            "event"
        ]
        for event in events
    }

    assert (
        "http_request.completed"
        in event_names
    )

    assert (
        "agent_run.started"
        in event_names
    )

    assert (
        "agent_run.completed"
        in event_names
    )

    serialized_events = (
        repr(
            events
        )
    )

    assert (
        secret_prompt
        not in serialized_events
    )

    assert (
        TEST_SERVICE_API_KEY
        not in serialized_events
    )


def test_agent_logs_use_response_correlation_ids(
    monkeypatch,
):
    events = []

    monkeypatch.setattr(
        api,
        "emit_http_event",
        lambda **kwargs: (
            events.append(
                kwargs
            )
        ),
    )

    fake_agent = (
        FakeDataEngineer()
    )

    monkeypatch.setattr(
        api,
        "_get_data_engineer",
        lambda: fake_agent,
    )

    client = (
        _authenticated_client()
    )

    response = client.post(
        "/query",
        json={
            "message": "Run ETL."
        },
    )

    request_id = (
        response.headers[
            "X-Request-ID"
        ]
    )

    run_id = (
        response.headers[
            "X-Run-ID"
        ]
    )

    run_events = [
        event
        for event in events
        if event[
            "event"
        ].startswith(
            "agent_run."
        )
    ]

    assert run_events

    assert all(
        event[
            "request_id"
        ]
        == request_id
        for event in run_events
    )

    assert all(
        event.get(
            "run_id"
        )
        == run_id
        for event in run_events
    )