from fastapi.testclient import TestClient

from app import app


def test_signup_validation(client) -> None:
    r = client.post("/api/auth/signup", json={
        "name": "X", "email": "not-an-email", "password": "password123"})
    assert r.status_code == 400
    r = client.post("/api/auth/signup", json={
        "name": "X", "email": "ok@example.com", "password": "short"})
    assert r.status_code == 400


def test_signup_verify_creates_seeded_workspace(auth_client) -> None:
    me = auth_client.get("/api/me").json()
    assert me["role"] == "admin"
    projects = auth_client.get("/api/projects").json()["projects"]
    names = {p["name"] for p in projects}
    assert names == {"Product launch plan", "Website redesign",
                     "User research study"}
    portfolios = auth_client.get("/api/portfolios").json()["portfolios"]
    assert portfolios[0]["name"] == "Research Projects 2026"
    assert portfolios[0]["project_count"] == 3


def test_duplicate_signup_conflict(auth_client) -> None:
    c = TestClient(app)
    r = c.post("/api/auth/signup", json={
        "name": "Dup", "email": auth_client.email, "password": "password123"})
    assert r.status_code == 409


def test_wrong_verification_code(client) -> None:
    r = client.post("/api/auth/signup", json={
        "name": "Code Test", "email": "codetest@example.com",
        "password": "password123"})
    assert r.status_code == 200
    r = client.post("/api/auth/verify", json={"code": "000000"})
    assert r.status_code == 400


def test_login_logout_cycle(auth_client) -> None:
    assert auth_client.post("/api/auth/logout").json()["ok"] is True
    assert auth_client.get("/api/me").status_code == 401
    r = auth_client.post("/api/auth/login", json={
        "email": auth_client.email, "password": "password123"})
    assert r.status_code == 200
    assert auth_client.get("/api/me").status_code == 200


def test_bad_credentials(auth_client) -> None:
    c = TestClient(app)
    r = c.post("/api/auth/login", json={
        "email": auth_client.email, "password": "wrongpass1"})
    assert r.status_code == 401
    r = c.post("/api/auth/login", json={
        "email": "ghost@example.com", "password": "whatever123"})
    assert r.status_code == 401


def test_protected_routes_require_auth(client) -> None:
    for path in ("/api/me", "/api/projects", "/api/my-tasks", "/api/inbox",
                 "/api/portfolios", "/api/goals", "/api/billing",
                 "/api/members", "/api/trash"):
        assert client.get(path).status_code == 401, path


def test_password_reset_flow(auth_client) -> None:
    c = TestClient(app)
    assert c.post("/api/auth/forgot",
                  json={"email": auth_client.email}).status_code == 200
    mail = c.get("/api/auth/mail",
                 params={"purpose": "password-reset"}).json()
    r = c.post("/api/auth/reset", json={
        "code": mail["verification_code"], "password": "brandnewpass1"})
    assert r.status_code == 200
    assert c.post("/api/auth/login", json={
        "email": auth_client.email,
        "password": "brandnewpass1"}).status_code == 200
    assert c.post("/api/auth/login", json={
        "email": auth_client.email,
        "password": "password123"}).status_code == 401


def test_forgot_does_not_enumerate(client) -> None:
    r = client.post("/api/auth/forgot", json={"email": "nobody@example.com"})
    assert r.status_code == 200


def test_authenticated_pages_render(auth_client) -> None:
    r = auth_client.get("/app/home")
    assert r.status_code == 200
    assert "data-app-root" in r.text
    r = auth_client.get("/-/login", follow_redirects=False)
    assert r.status_code == 302  # already signed in


def test_security_sessions(auth_client) -> None:
    sessions = auth_client.get("/api/security/sessions").json()["sessions"]
    assert sessions and sessions[0]["active"] is True
    r = auth_client.post("/api/security/logout-others")
    assert r.status_code == 200
