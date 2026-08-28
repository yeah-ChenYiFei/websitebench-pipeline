def test_healthz(client, monkeypatch) -> None:
    build_id = "b" * 40
    monkeypatch.setenv("DEPLOYMENT_BUILD_ID", build_id)
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"ok": True, "site_id": "asana"}
    assert response.headers["X-WebsiteBench-Container-Build-ID"] == build_id


def test_home(client) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "The OS for" in response.text
    assert "human-agent teams" in response.text


def test_unknown_route(client) -> None:
    assert client.get("/not-in-scope").status_code == 404
