from fastapi.testclient import (
    TestClient,
)

from langchain_core.messages import (
    AIMessage,
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

    client = TestClient(
        api.app
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
    client = TestClient(
        api.app
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

    client = TestClient(
        api.app
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

        client = TestClient(
            api.app
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

    client = TestClient(
        api.app
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

    client = TestClient(
        api.app
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

    client = TestClient(
        api.app
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