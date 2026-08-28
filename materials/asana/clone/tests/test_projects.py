def test_create_project_from_template(auth_client) -> None:
    r = auth_client.post("/api/projects", json={
        "name": "Template project", "template": "cross-functional",
        "view": "board", "color": "#5da283"})
    pid = r.json()["project_id"]
    meta = auth_client.get(f"/api/projects/{pid}").json()
    assert [s["name"] for s in meta["sections"]] == ["Planning", "Milestones", "Done"]
    tasks = auth_client.get(f"/api/projects/{pid}/tasks").json()["tasks"]
    assert len(tasks) == 3
    assert meta["project"]["default_view"] == "board"


def test_project_validation(auth_client) -> None:
    assert auth_client.post("/api/projects", json={"name": ""}).status_code == 400
    assert auth_client.post("/api/projects", json={
        "name": "x", "template": "nope"}).status_code == 400
    assert auth_client.post("/api/projects", json={
        "name": "x", "view": "gantt"}).status_code == 400


def test_project_edit_archive_delete(auth_client) -> None:
    pid = auth_client.post("/api/projects",
                           json={"name": "Lifecycle"}).json()["project_id"]
    assert auth_client.patch(f"/api/projects/{pid}", json={
        "name": "Lifecycle v2", "status": "at_risk",
        "description": "desc"}).status_code == 200
    meta = auth_client.get(f"/api/projects/{pid}").json()["project"]
    assert meta["name"] == "Lifecycle v2" and meta["status"] == "at_risk"

    assert auth_client.patch(f"/api/projects/{pid}",
                             json={"archived": 1}).status_code == 200
    active = {p["project_id"] for p in
              auth_client.get("/api/projects").json()["projects"]}
    assert pid not in active
    archived = {p["project_id"] for p in
                auth_client.get("/api/projects?archived=1").json()["projects"]}
    assert pid in archived
    assert auth_client.patch(f"/api/projects/{pid}",
                             json={"archived": 0}).status_code == 200

    assert auth_client.delete(f"/api/projects/{pid}").status_code == 200
    trash = auth_client.get("/api/trash").json()
    assert any(p["project_id"] == pid for p in trash["projects"])
    assert auth_client.post("/api/trash/restore",
                            json={"project_id": pid}).status_code == 200


def test_sections(auth_client) -> None:
    pid = auth_client.post("/api/projects",
                           json={"name": "Sectioned"}).json()["project_id"]
    sid = auth_client.post(f"/api/projects/{pid}/sections",
                           json={"name": "Extra"}).json()["section_id"]
    assert auth_client.patch(f"/api/sections/{sid}",
                             json={"name": "Renamed"}).status_code == 200
    tid = auth_client.post("/api/tasks", json={
        "name": "In section", "project_id": pid,
        "section_id": sid}).json()["task_id"]
    assert auth_client.delete(f"/api/sections/{sid}").status_code == 409
    assert auth_client.delete(f"/api/tasks/{tid}").status_code == 200
    assert auth_client.delete(f"/api/sections/{sid}").status_code == 200


def test_import_export(auth_client) -> None:
    pid = auth_client.post("/api/projects",
                           json={"name": "IO project"}).json()["project_id"]
    csv_body = "Name,Notes,Due Date\nAlpha,,2026-09-01\nBeta,has note,\n,skipped,\n"
    r = auth_client.post(f"/api/projects/{pid}/import",
                         files={"file": ("in.csv", csv_body, "text/csv")})
    assert r.json()["imported"] == 2
    r = auth_client.post(f"/api/projects/{pid}/import",
                         files={"file": ("bad.csv", "no header row", "text/csv")})
    assert r.status_code == 400
    r = auth_client.get(f"/api/projects/{pid}/export.csv")
    assert r.status_code == 200
    assert "Alpha" in r.text and "Beta" in r.text
    r = auth_client.get("/api/export/workspace.json")
    assert r.status_code == 200
    assert any(p["project_id"] == pid for p in r.json()["projects"])


def test_rules(auth_client) -> None:
    pid = auth_client.post("/api/projects",
                           json={"name": "Ruled"}).json()["project_id"]
    rid = auth_client.post(f"/api/projects/{pid}/rules", json={
        "name": "Auto move", "trigger": "task_completed",
        "action": "move_to_section:Done"}).json()["rule_id"]
    assert auth_client.patch(f"/api/rules/{rid}",
                             json={"enabled": False}).status_code == 200
    rules = auth_client.get(f"/api/projects/{pid}").json()["rules"]
    assert rules[0]["enabled"] == 0
    assert auth_client.post(f"/api/projects/{pid}/rules", json={
        "name": "Bad", "trigger": "on_full_moon",
        "action": "x"}).status_code == 400


def test_portfolio_e2e_scenario(auth_client) -> None:
    """WB009-T48: portfolio 'Research Projects 2026' with 3 sub-projects."""

    portfolios = auth_client.get("/api/portfolios").json()["portfolios"]
    seeded = next(p for p in portfolios if p["name"] == "Research Projects 2026")
    assert seeded["project_count"] == 3

    # And the flow can be repeated from scratch by the user.
    pf = auth_client.post("/api/portfolios", json={
        "name": "Fresh portfolio"}).json()["portfolio_id"]
    for i in range(3):
        auth_client.post("/api/projects", json={
            "name": f"Sub-project {i + 1}", "portfolio_id": pf})
    detail = auth_client.get(f"/api/portfolios/{pf}").json()
    assert len(detail["projects"]) == 3


def test_goals(auth_client) -> None:
    gid = auth_client.post("/api/goals", json={
        "name": "Test goal", "time_period": "Q4 FY26"}).json()["goal_id"]
    assert auth_client.patch(f"/api/goals/{gid}", json={
        "progress": 60, "status": "at_risk"}).status_code == 200
    goals = auth_client.get("/api/goals").json()["goals"]
    g = next(x for x in goals if x["goal_id"] == gid)
    assert g["progress"] == 60 and g["status"] == "at_risk"
    assert auth_client.patch(f"/api/goals/{gid}",
                             json={"progress": 150}).status_code == 400


def test_saved_views(auth_client) -> None:
    vid = auth_client.post("/api/views", json={
        "name": "My high priority",
        "query": {"priority": "High", "path": "/app/tasks"}}).json()["view_id"]
    views = auth_client.get("/api/views").json()["views"]
    assert any(v["view_id"] == vid for v in views)
    assert auth_client.delete(f"/api/views/{vid}").status_code == 200


def test_search(auth_client) -> None:
    p = auth_client.get("/api/projects").json()["projects"][0]
    auth_client.post("/api/tasks", json={
        "name": "Zebra hunting expedition", "project_id": p["project_id"]})
    r = auth_client.get("/api/search", params={"q": "zebra"}).json()
    assert any("Zebra" in t["name"] for t in r["tasks"])
    r = auth_client.get("/api/search", params={"q": "launch"}).json()
    assert r["projects"] or r["tasks"]
    r = auth_client.get("/api/search", params={"q": "xyzzy-no-hit"}).json()
    assert not r["tasks"] and not r["projects"] and not r["people"]
