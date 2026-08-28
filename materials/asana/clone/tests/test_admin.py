from fastapi.testclient import TestClient

from app import app


def test_members_include_synthetic_teammates(auth_client) -> None:
    members = auth_client.get("/api/members").json()["members"]
    assert sum(1 for m in members if m["synthetic"]) == 4
    assert any(not m["synthetic"] for m in members)


def test_invite_is_simulated(auth_client) -> None:
    r = auth_client.post("/api/invites", json={"email": "friend@example.com"})
    body = r.json()
    assert body["simulated"] is True
    assert "locally" in body["note"]
    invites = auth_client.get("/api/members").json()["invites"]
    assert any(i["email"] == "friend@example.com" for i in invites)
    assert auth_client.post("/api/invites",
                            json={"email": "not-an-email"}).status_code == 400


def test_role_changes(auth_client) -> None:
    members = auth_client.get("/api/members").json()["members"]
    me = auth_client.get("/api/me").json()
    other = next(m for m in members if m["synthetic"])
    assert auth_client.patch(f"/api/members/{other['user_id']}",
                             json={"role": "admin"}).status_code == 200
    assert auth_client.patch(f"/api/members/{me['user']['user_id']}",
                             json={"role": "member"}).status_code == 400
    assert auth_client.patch(f"/api/members/{other['user_id']}",
                             json={"role": "owner"}).status_code == 400


def test_workspace_rename_and_switch(auth_client) -> None:
    assert auth_client.patch("/api/workspace",
                             json={"name": "Renamed WS"}).status_code == 200
    assert auth_client.get("/api/me").json()["workspace"]["name"] == "Renamed WS"

    ws2 = auth_client.post("/api/workspaces",
                           json={"name": "Second WS"}).json()["workspace_id"]
    me = auth_client.get("/api/me").json()
    assert me["workspace"]["workspace_id"] == ws2
    # Fresh workspace is empty (empty-state coverage), then switch back.
    assert auth_client.get("/api/projects").json()["projects"] == []
    first = next(w for w in me["workspaces"] if w["workspace_id"] != ws2)
    auth_client.post("/api/workspace/switch",
                     json={"workspace_id": first["workspace_id"]})
    assert auth_client.get("/api/projects").json()["projects"] != []
    assert auth_client.post("/api/workspace/switch",
                            json={"workspace_id": "workspace_ghost"}).status_code == 404


def test_workspace_isolation_between_accounts(auth_client) -> None:
    c2 = TestClient(app)
    c2.post("/api/auth/signup", json={
        "name": "Other Person", "email": "isolation@example.com",
        "password": "password123"})
    code = c2.get("/api/auth/mail",
                  params={"purpose": "registration"}).json()["verification_code"]
    c2.post("/api/auth/verify", json={"code": code})
    theirs = c2.get("/api/projects").json()["projects"]
    mine = auth_client.get("/api/projects").json()["projects"]
    assert {p["project_id"] for p in theirs}.isdisjoint(
        {p["project_id"] for p in mine})
    # Cross-tenant access is a 404, not a leak.
    assert c2.get(f"/api/projects/{mine[0]['project_id']}").status_code == 404


def test_profile_and_preferences(auth_client) -> None:
    assert auth_client.patch("/api/profile", json={
        "display_name": "New Name", "role_title": "PM",
        "theme": "dark", "notify_mentions": 0}).status_code == 200
    me = auth_client.get("/api/me").json()["user"]
    assert me["display_name"] == "New Name"
    assert me["initials"] == "NN"
    assert me["theme"] == "dark"
    assert auth_client.patch("/api/profile",
                             json={"theme": "sepia"}).status_code == 400
    assert auth_client.patch("/api/profile", json={}).status_code == 400


def test_activity_feed(auth_client) -> None:
    auth_client.post("/api/projects", json={"name": "Audit trail"})
    acts = auth_client.get("/api/activity").json()["activity"]
    assert any(a["verb"] == "created" and a["object_name"] == "Audit trail"
               for a in acts)


def test_notifications_flow(auth_client) -> None:
    # Comment mentioning a synthetic member notifies them, not us; assigning
    # ourselves a task from a synthetic member is not possible, so exercise
    # read/archive on our own inbox (may be empty) via error paths.
    assert auth_client.post("/api/inbox/999999/read").status_code == 404
    inbox = auth_client.get("/api/inbox").json()
    assert "unread" in inbox and isinstance(inbox["notifications"], list)


def test_billing_sandbox(auth_client) -> None:
    plans = auth_client.get("/api/billing").json()
    assert plans["payment_adapter"] == "local-sandbox"
    r = auth_client.post("/api/billing/upgrade", json={
        "plan": "starter", "scenario": "sandbox-declined"})
    assert r.status_code == 402
    assert auth_client.get("/api/me").json()["workspace"]["plan"] == "personal"
    r = auth_client.post("/api/billing/upgrade", json={
        "plan": "starter", "scenario": "sandbox-approved"})
    assert r.json()["ok"] is True
    assert auth_client.get("/api/me").json()["workspace"]["plan"] == "starter"
    assert auth_client.post("/api/billing/upgrade", json={
        "plan": "personal"}).status_code == 400
