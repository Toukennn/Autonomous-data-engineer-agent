from fastapi.testclient import TestClient

from app import api


def test_landing_page_is_public_and_human_friendly():
    client = TestClient(api.app)

    response = client.get("/")

    assert response.status_code == 200
    assert "Autonomous Data Engineer Agent" in response.text
    assert "Ask a question" in response.text
    assert "Ingest an API" in response.text
    assert "X-API-Key" in response.text
    assert "Need a demo key?" in response.text
    assert "https://github.com/Toukennn" in response.text
    assert "autonomous-de-demo-key" in response.text
    assert "sessionStorage" in response.text
    assert "localStorage" not in response.text
