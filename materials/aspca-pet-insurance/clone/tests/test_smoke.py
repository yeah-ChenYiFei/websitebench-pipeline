from fastapi.testclient import TestClient

from app import app

client = TestClient(app)


def test_healthz() -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"ok": True, "site_id": "aspca-pet-insurance"}


def test_home() -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert len(response.text) > 10_000  # frozen capture, not a placeholder


def test_unknown_route() -> None:
    assert client.get("/not-in-scope").status_code == 404
