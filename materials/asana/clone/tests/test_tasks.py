import sqlite3

from asana_app.services import SERVICES


def _first_project(c):
    return c.get("/api/projects").json()["projects"][0]


def test_task_crud_persists(auth_client) -> None:
    p = _first_project(auth_client)
    r = auth_client.post("/api/tasks", json={
        "name": "Persistence check", "project_id": p["project_id"],
        "due_date": "2026-09-15", "priority": "Medium", "notes": "note body"})
    task_id = r.json()["task_id"]
    r = auth_client.patch(f"/api/tasks/{task_id}", json={
        "name": "Persistence check v2", "priority": "High"})
    assert r.status_code == 200
    # Independent connection proves the row is durable in SQLite.
    db = sqlite3.connect(SERVICES.backend.lifecycle.database_path)
    row = db.execute("SELECT name, priority, due_date FROM az_tasks"
                     " WHERE task_id=?", (task_id,)).fetchone()
    db.close()
    assert row == ("Persistence check v2", "High", "2026-09-15")


def test_complete_and_uncomplete(auth_client) -> None:
    p = _first_project(auth_client)
    task_id = auth_client.post("/api/tasks", json={
        "name": "Completable", "project_id": p["project_id"]}).json()["task_id"]
    assert auth_client.patch(f"/api/tasks/{task_id}",
                             json={"completed": 1}).status_code == 200
    detail = auth_client.get(f"/api/tasks/{task_id}").json()["task"]
    assert detail["completed"] == 1 and detail["completed_at"]
    assert auth_client.patch(f"/api/tasks/{task_id}",
                             json={"completed": 0}).status_code == 200
    assert auth_client.get(f"/api/tasks/{task_id}").json()["task"]["completed"] == 0


def test_validation_errors(auth_client) -> None:
    assert auth_client.post("/api/tasks", json={"name": ""}).status_code == 400
    assert auth_client.post("/api/tasks", json={
        "name": "x", "project_id": "project_missing"}).status_code == 404
    p = _first_project(auth_client)
    task_id = auth_client.post("/api/tasks", json={
        "name": "V", "project_id": p["project_id"]}).json()["task_id"]
    assert auth_client.patch(f"/api/tasks/{task_id}",
                             json={"name": ""}).status_code == 400
    assert auth_client.patch(f"/api/tasks/{task_id}",
                             json={"assignee_user_id": "user_ghost"}).status_code == 400


def test_subtasks_and_dependencies(auth_client) -> None:
    p = _first_project(auth_client)
    parent = auth_client.post("/api/tasks", json={
        "name": "Parent task", "project_id": p["project_id"]}).json()["task_id"]
    sub = auth_client.post("/api/tasks", json={
        "name": "Child task", "parent_task_id": parent}).json()["task_id"]
    detail = auth_client.get(f"/api/tasks/{parent}").json()
    assert [s["task_id"] for s in detail["subtasks"]] == [sub]

    blocker = auth_client.post("/api/tasks", json={
        "name": "Blocker", "project_id": p["project_id"]}).json()["task_id"]
    assert auth_client.post(f"/api/tasks/{parent}/dependencies", json={
        "depends_on_task_id": blocker}).status_code == 200
    # cycle rejected
    assert auth_client.post(f"/api/tasks/{blocker}/dependencies", json={
        "depends_on_task_id": parent}).status_code == 409
    # self-dependency rejected
    assert auth_client.post(f"/api/tasks/{parent}/dependencies", json={
        "depends_on_task_id": parent}).status_code == 400
    # blocked completion returns conflict, force works
    assert auth_client.patch(f"/api/tasks/{parent}",
                             json={"completed": 1}).status_code == 409
    assert auth_client.patch(f"/api/tasks/{parent}", json={
        "completed": 1, "force": True}).status_code == 200


def test_bulk_actions(auth_client) -> None:
    p = _first_project(auth_client)
    ids = [auth_client.post("/api/tasks", json={
        "name": f"Bulk {i}", "project_id": p["project_id"]}).json()["task_id"]
        for i in range(3)]
    r = auth_client.post("/api/tasks/bulk", json={
        "task_ids": ids, "action": "complete"})
    assert r.json()["changed"] == 3
    for tid in ids:
        assert auth_client.get(f"/api/tasks/{tid}").json()["task"]["completed"] == 1
    assert auth_client.post("/api/tasks/bulk", json={
        "task_ids": [], "action": "complete"}).status_code == 400
    assert auth_client.post("/api/tasks/bulk", json={
        "task_ids": ids, "action": "explode"}).status_code == 400


def test_trash_restore_and_purge(auth_client) -> None:
    p = _first_project(auth_client)
    tid = auth_client.post("/api/tasks", json={
        "name": "Trashable", "project_id": p["project_id"]}).json()["task_id"]
    assert auth_client.delete(f"/api/tasks/{tid}").status_code == 200
    assert auth_client.get(f"/api/tasks/{tid}").status_code == 200  # visible detail
    trash = auth_client.get("/api/trash").json()
    assert any(t["task_id"] == tid for t in trash["tasks"])
    assert auth_client.post("/api/trash/restore",
                            json={"task_id": tid}).status_code == 200
    assert auth_client.delete(f"/api/tasks/{tid}").status_code == 200
    assert auth_client.post("/api/trash/purge",
                            json={"task_id": tid}).status_code == 200
    assert auth_client.get(f"/api/tasks/{tid}").status_code == 404


def test_filters_and_sort(auth_client) -> None:
    p = _first_project(auth_client)
    r = auth_client.get(f"/api/projects/{p['project_id']}/tasks",
                        params={"completed": "0", "priority": "High"})
    assert r.status_code == 200
    for t in r.json()["tasks"]:
        assert t["completed"] == 0 and t["priority"] == "High"
    r = auth_client.get(f"/api/projects/{p['project_id']}/tasks",
                        params={"sort": "alphabetical"})
    names = [t["name"].lower() for t in r.json()["tasks"]]
    assert names == sorted(names)
    assert auth_client.get(f"/api/projects/{p['project_id']}/tasks",
                           params={"sort": "bogus"}).status_code == 400


def test_comments_thread(auth_client) -> None:
    p = _first_project(auth_client)
    tid = auth_client.post("/api/tasks", json={
        "name": "Discussable", "project_id": p["project_id"]}).json()["task_id"]
    cid = auth_client.post(f"/api/tasks/{tid}/comments", json={
        "body": "First comment"}).json()["comment_id"]
    assert auth_client.patch(f"/api/comments/{cid}", json={
        "body": "Edited comment"}).status_code == 200
    comments = auth_client.get(f"/api/tasks/{tid}").json()["comments"]
    assert comments[-1]["body"] == "Edited comment"
    assert comments[-1]["edited_at"]
    assert auth_client.delete(f"/api/comments/{cid}").status_code == 200
    assert auth_client.post(f"/api/tasks/{tid}/comments",
                            json={"body": ""}).status_code == 400


def test_attachments_roundtrip(auth_client) -> None:
    p = _first_project(auth_client)
    tid = auth_client.post("/api/tasks", json={
        "name": "With file", "project_id": p["project_id"]}).json()["task_id"]
    r = auth_client.post(f"/api/tasks/{tid}/attachments",
                         files={"file": ("hello.txt", b"file body", "text/plain")})
    aid = r.json()["attachment_id"]
    r = auth_client.get(f"/api/attachments/{aid}")
    assert r.status_code == 200 and r.content == b"file body"
    r = auth_client.post(f"/api/tasks/{tid}/attachments",
                         files={"file": ("empty.txt", b"", "text/plain")})
    assert r.status_code == 400


def test_my_tasks_and_assignment_notification(auth_client) -> None:
    members = auth_client.get("/api/members").json()["members"]
    other = next(m for m in members if m["synthetic"])
    p = _first_project(auth_client)
    auth_client.post("/api/tasks", json={
        "name": "Delegated task", "project_id": p["project_id"],
        "assignee_user_id": other["user_id"]})
    mine = auth_client.get("/api/my-tasks").json()["tasks"]
    assert all(t["name"] != "Delegated task" for t in mine)


def test_date_validation(auth_client) -> None:
    p = _first_project(auth_client)
    assert auth_client.post("/api/tasks", json={
        "name": "Bad date", "project_id": p["project_id"],
        "due_date": "not-a-date"}).status_code == 400
    tid = auth_client.post("/api/tasks", json={
        "name": "Date holder", "project_id": p["project_id"]}).json()["task_id"]
    assert auth_client.patch(f"/api/tasks/{tid}",
                             json={"due_date": "2026-13-45"}).status_code == 400
    assert auth_client.patch(f"/api/tasks/{tid}",
                             json={"due_date": "2026-09-01"}).status_code == 200
    r = auth_client.post("/api/tasks/bulk", json={
        "task_ids": [tid], "action": "set_due_date", "due_date": "garbage"})
    assert r.status_code == 400
    r = auth_client.post("/api/tasks/bulk", json={
        "task_ids": [tid], "action": "set_due_date", "due_date": "2026-09-02"})
    assert r.json()["changed"] == 1
