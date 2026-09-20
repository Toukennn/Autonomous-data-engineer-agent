from fastapi.testclient import TestClient

from app import api


def test_landing_page_is_public_and_human_friendly():
    client = TestClient(api.app)

    response = client.get("/")

    assert response.status_code == 200
    assert "Autonomous Data Engineer Agent" in response.text
    assert "Live governed query" in response.text
    assert "X-API-Key" in response.text
