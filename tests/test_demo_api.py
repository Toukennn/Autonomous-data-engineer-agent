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


def test_demo_ingest_passes_discovered_path_to_etl(
    monkeypatch,
    tmp_path,
):
    import sys
    import threading
    from types import ModuleType, SimpleNamespace

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app import demo_api
    from utils.execution_observability import ExecutionRunStore

    requested_urls = []
    prompts = []

    class FakeAPIClient:
        def discover_records_path(self, url):
            requested_urls.append(url)
            return "response.data.items"

    def invoke(payload):
        prompts.append(payload["messages"][0].content)
        ExecutionRunStore(tmp_path).complete_run(
            run_id=payload["run_id"],
            status="completed",
        )
        return {
            "messages": [SimpleNamespace(content="Pipeline completed.")],
            "workflow_failed": False,
        }

    class ImmediatePool:
        def submit(self, operation, **kwargs):
            operation(**kwargs)

    fake_etl_module = ModuleType("agents.etl_analyst")
    fake_etl_module.etl_analyst = SimpleNamespace(invoke=invoke)
    monkeypatch.setitem(
        sys.modules,
        "agents.etl_analyst",
        fake_etl_module,
    )
    monkeypatch.setattr(demo_api, "APIClient", FakeAPIClient)
    monkeypatch.setattr(
        demo_api,
        "get_runtime_settings",
        lambda: SimpleNamespace(
            data_root=tmp_path,
            dbt_target_schema="dbt_test",
            etl_max_tool_calls=8,
        ),
    )

    app = FastAPI()
    app.include_router(
        demo_api.create_demo_router(
            require_demo_api_key=lambda: None,
            execution_lock=threading.Lock(),
            execution_pool=ImmediatePool(),
        )
    )

    client = TestClient(app)
    response = client.post(
        "/demo/ingest",
        json={
            "api_url": "https://example.com/data",
            "gold_goal": "Count active users by country.",
        },
    )

    assert response.status_code == 202
    assert requested_urls == ["https://example.com/data"]
    assert len(prompts) == 1
    assert "'response.data.items'" in prompts[0]
    assert "paginate=False" in prompts[0]
    assert "use_auth=False" in prompts[0]
    assert "Count active users by country." in prompts[0]

    status = client.get(
        f"/demo/runs/{response.json()['run_id']}"
    )
    assert status.status_code == 200
    assert status.json()["status"] == "completed"
