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
    assert "Hair Appointments | Beauty Salons: Book Online | StyleSeat" in response.text
    assert 'data-testid="home-hero-container"' in response.text
    assert '<script src="/static/local-auth.js" defer></script>' in response.text


def test_unknown_route() -> None:
    assert client.get("/not-in-scope").status_code == 404
