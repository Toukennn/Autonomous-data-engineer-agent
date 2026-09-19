from fastapi.testclient import (
    TestClient,
)

from langchain_core.messages import (
    AIMessage,
)

from app import api


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