from uuid import UUID

from fastapi.testclient import TestClient

from app import api


EXPECTED_RUNS = {
    "revenue-by-country": "completed",
    "gold-preview": "completed",
    "missing-values": "completed",
    "blocked-pg-catalog": "blocked",
}


def test_recorded_index_and_runs_are_public_without_demo_key(
    monkeypatch,
):
    def missing_demo_settings():
        raise RuntimeError("demo key unavailable")

    monkeypatch.setattr(
        api,
        "get_demo_api_settings",
        missing_demo_settings,
    )
    client = TestClient(api.app)

    index = client.get("/demo/recorded")
    assert index.status_code == 200
    assert index.json()["recorded"] is True
    assert {
        item["slug"]
        for item in index.json()["runs"]
    } == set(EXPECTED_RUNS)

    for slug, expected_status in EXPECTED_RUNS.items():
        response = client.get(
            f"/demo/recorded/{slug}"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["recorded"] is True
        assert data["slug"] == slug
        assert data["status"] == expected_status
        assert data["elapsed_ms"] > 0
        assert UUID(data["request_id"]).version == 4
        assert UUID(data["run_id"]).version == 4
        assert data["stages"]
        assert data["result"]["generated_sql"]
        assert data["result"]["answer"]

    protected = client.get(
        "/demo/runs/not-a-valid-run-id"
    )
    assert protected.status_code == 503


def test_recorded_data_shows_real_result_and_blocked_execution():
    client = TestClient(api.app)

    revenue = client.get(
        "/demo/recorded/revenue-by-country"
    ).json()
    assert len(revenue["result"]["rows"]) == 5
    assert revenue["result"]["columns"] == [
        "Country",
        "total_revenue",
    ]
    assert "SUM" in revenue["result"]["generated_sql"]
    assert revenue["guardrail"] is None

    blocked = client.get(
        "/demo/recorded/blocked-pg-catalog"
    ).json()
    assert blocked["guardrail"]["kind"] == "sql_safety"
    assert blocked["result"]["rows"] == []
    assert any(
        stage["id"] == "execute"
        and stage["status"] == "skipped"
        for stage in blocked["stages"]
    )


def test_only_allowlisted_recordings_are_served():
    client = TestClient(api.app)

    response = client.get(
        "/demo/recorded/unknown-run"
    )
    assert response.status_code == 404
    assert response.json() == {
        "detail": "Recorded run not found."
    }
