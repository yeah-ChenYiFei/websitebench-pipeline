from fastapi.testclient import TestClient

from app import app


client = TestClient(app)


def test_healthz() -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_home() -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "学习新技能，开启更多可能" in response.text


def test_unknown_route() -> None:
    assert client.get("/not-in-scope").status_code == 404
