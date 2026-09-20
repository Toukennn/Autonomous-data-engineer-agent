from app.demo_api import (
    _ask_stages,
    _guardrail,
    _ingest_stages,
)


def test_ask_stages_show_generation_while_running():
    stages = _ask_stages(
        {
            "events": [],
        },
        "running",
    )

    assert stages[0]["status"] == "active"
    assert stages[1]["status"] == "pending"


def test_ask_stages_show_sql_guardrail_block():
    record = {
        "events": [
            {
                "event_type": "sql_safety",
                "name": "governed_sql_validation",
                "status": "rejected",
                "metadata": {},
            }
        ]
    }

    stages = _ask_stages(
        record,
        "blocked",
    )

    assert stages[1]["status"] == "blocked"
    assert stages[2]["status"] == "skipped"

    guardrail = _guardrail(
        record
    )

    assert guardrail is not None
    assert guardrail["kind"] == "sql_safety"


def test_ingest_stages_advance_from_extract_to_silver():
    record = {
        "events": [
            {
                "event_type": "tool",
                "name": "extract_load_tool",
                "status": "success",
                "metadata": {},
            }
        ]
    }

    stages = _ingest_stages(
        record,
        "running",
    )

    assert stages[0]["status"] == "completed"
    assert stages[1]["status"] == "active"


def test_quality_failure_is_presented_as_guardrail():
    record = {
        "events": [
            {
                "event_type": "tool",
                "name": "dbt_silver_to_gold_tool",
                "status": "failed",
                "metadata": {
                    "quality_gate": {
                        "failed_checks": 1,
                    }
                },
            }
        ]
    }

    guardrail = _guardrail(
        record
    )

    assert guardrail is not None
    assert guardrail["kind"] == "quality_gate"


def test_demo_routes_use_only_demo_key_and_are_registered(
    monkeypatch,
):
    from types import SimpleNamespace

    from fastapi.testclient import TestClient
    from pydantic import SecretStr

    from app import api

    demo_key = "demo-" + "a" * 32
    service_key = "service-" + "b" * 32

    monkeypatch.setattr(
        api,
        "get_demo_api_settings",
        lambda: SimpleNamespace(
            demo_api_key=SecretStr(demo_key)
        ),
    )
    monkeypatch.setattr(
        api,
        "get_service_api_settings",
        lambda: SimpleNamespace(
            service_api_key=SecretStr(service_key)
        ),
    )

    client = TestClient(api.app)
    path = "/demo/runs/not-a-valid-run-id"

    assert client.get(path).status_code == 401
    assert client.get(
        path,
        headers={"X-API-Key": service_key},
    ).status_code == 401

    authenticated = client.get(
        path,
        headers={"X-API-Key": demo_key},
    )
    assert authenticated.status_code == 404

    service_response = client.post(
        "/query",
        headers={"X-API-Key": demo_key},
        json={"message": "Hello"},
    )
    assert service_response.status_code == 401

    def missing_demo_settings():
        raise RuntimeError("missing")

    monkeypatch.setattr(
        api,
        "get_demo_api_settings",
        missing_demo_settings,
    )
    unavailable = client.get(path)
    assert unavailable.status_code == 503
    assert unavailable.json() == {
        "detail": "Demo authentication is not configured."
    }
