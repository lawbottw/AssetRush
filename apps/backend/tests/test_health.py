from fastapi.testclient import TestClient

from assetrush.main import app

client = TestClient(app)


def test_health_returns_200() -> None:
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"
