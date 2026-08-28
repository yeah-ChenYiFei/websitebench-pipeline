"""JSON API for the Asana offline clone.

All persistence flows through the site-bound SQLite database opened by the
generated ``websitebench.site_backend`` seam. Authentication uses the
generated LocalAuthStore only — no custom auth. All collaborators, comments
and business records are local synthetic data.
"""

from __future__ import annotations

import csv
import datetime
import hashlib
import io
import json
import sqlite3
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request, Response, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

from websitebench.local_clone_auth import store as auth_store_mod
from websitebench.site_backend.errors import PaymentError, PaymentRejected

from . import db as d
from .seed import seed_workspace
from .services import SERVICES

AuthError = auth_store_mod.AuthError
AuthRejected = auth_store_mod.AuthRejected
AuthConflict = auth_store_mod.AuthConflict
AuthValidationError = auth_store_mod.AuthValidationError

router = APIRouter(prefix="/api")

PLANS = {
    "personal": {"label": "Personal", "monthly_minor": 0},
    "starter": {"label": "Starter", "monthly_minor": 1099},
    "advanced": {"label": "Advanced", "monthly_minor": 2499},
}
PROJECT_TEMPLATES = [
    {"id": "blank", "name": "Blank project", "sections": ["To do", "In progress", "Done"], "tasks": []},
    {"id": "cross-functional", "name": "Cross-functional project plan",
     "sections": ["Planning", "Milestones", "Done"],
     "tasks": [("Draft project brief", 0), ("Schedule kickoff meeting", 0), ("Share timeline with teammates", 1)]},
    {"id": "meeting-agenda", "name": "Meeting agenda",
     "sections": ["Discussion topics", "FYIs", "Action items"],
     "tasks": [("Add discussion topics", 0), ("Review last week's action items", 2)]},
    {"id": "sprint-plan", "name": "Sprint planning",
     "sections": ["Backlog", "This sprint", "Shipped"],
     "tasks": [("Groom backlog", 0), ("Define sprint goal", 1)]},
]


def valid_date(value: Any) -> bool:
    if value is None:
        return True
    if not isinstance(value, str):
        return False
    try:
        datetime.date.fromisoformat(value)
    except ValueError:
        return False
    return True


def err(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


LOCAL_SESSION_COOKIE = "websitebench-asana-session"


def _secure_request(request: Request) -> bool:
    return (request.url.scheme == "https" or
            request.headers.get("x-forwarded-proto", "").lower() == "https")


def _cookie_name(request: Request, services: Any) -> str:
    return services.cookie_name if _secure_request(request) else LOCAL_SESSION_COOKIE


class Ctx:
    def __init__(self, request: Request) -> None:
        self.request = request
        self.services = SERVICES
        self.auth = SERVICES.auth
        self.backend = SERVICES.backend
        self.token = request.cookies.get(_cookie_name(request, SERVICES))
        self.session = self.auth.resolve_session(self.token)
        account = (self.session or {}).get("account") or {}
        self.account_id = account.get("account_id")
        self.user: dict[str, Any] | None = None
        self.workspace: dict[str, Any] | None = None
        if self.account_id:
            with self.connect() as c:
                self.user = d.row_to_dict(c.execute(
                    "SELECT * FROM az_users WHERE user_id=?", (self.account_id,)
                ).fetchone())
                if self.user:
                    ws_id = request.cookies.get("asana_workspace")
                    row = None
                    if ws_id:
                        row = c.execute(
                            "SELECT w.* FROM az_workspaces w JOIN az_workspace_members m"
                            " ON m.workspace_id=w.workspace_id"
                            " WHERE m.user_id=? AND w.workspace_id=?",
                            (self.account_id, ws_id)).fetchone()
                    if row is None:
                        row = c.execute(
                            "SELECT w.* FROM az_workspaces w JOIN az_workspace_members m"
                            " ON m.workspace_id=w.workspace_id WHERE m.user_id=?"
                            " ORDER BY w.created_at LIMIT 1",
                            (self.account_id,)).fetchone()
                    self.workspace = d.row_to_dict(row)

    def connect(self) -> sqlite3.Connection:
        return self.auth.connect()

    @property
    def ws_id(self) -> str:
        return self.workspace["workspace_id"]

    def role(self, connection: sqlite3.Connection) -> str:
        row = connection.execute(
            "SELECT role FROM az_workspace_members WHERE workspace_id=? AND user_id=?",
            (self.ws_id, self.account_id)).fetchone()
        return row["role"] if row else "none"


def ctx(request: Request) -> Ctx:
    return Ctx(request)


def require_auth(c: Ctx) -> JSONResponse | None:
    if not c.account_id or not c.user or not c.workspace:
        return err(401, "unauthorized", "Sign in to continue.")
    return None


def _set_session_cookie(
    response: Response, request: Request, services: Any, token: str,
) -> None:
    opts = services.backend.session_cookie
    response.set_cookie(
        key=_cookie_name(request, services), value=token,
        httponly=bool(opts.get("http_only", True)), secure=_secure_request(request),
        samesite=str(opts.get("same_site", "Lax")).lower(), path="/",
    )


def _public_user(u: dict[str, Any]) -> dict[str, Any]:
    return {k: u[k] for k in (
        "user_id", "email", "display_name", "initials", "avatar_color",
        "role_title", "about_me", "synthetic", "task_default_view", "theme",
        "notify_mentions", "notify_status", "notify_daily_summary")}


def _create_user_and_workspace(
    connection: sqlite3.Connection, *, account_id: str, email: str, name: str,
) -> None:
    initials = "".join(w[0] for w in name.split()[:2]).upper() or name[:2].upper()
    connection.execute(
        "INSERT INTO az_users(user_id, email, display_name, initials, created_at)"
        " VALUES (?,?,?,?,?)", (account_id, email, name, initials, d.now()))
    ws_id = d.new_id("workspace")
    connection.execute(
        "INSERT INTO az_workspaces(workspace_id, name, owner_user_id, created_at)"
        " VALUES (?,?,?,?)", (ws_id, "My workspace", account_id, d.now()))
    connection.execute(
        "INSERT INTO az_workspace_members(workspace_id, user_id, role, joined_at)"
        " VALUES (?,?,'admin',?)", (ws_id, account_id, d.now()))
    seed_workspace(connection, workspace_id=ws_id, owner_user_id=account_id)


# ---------------------------------------------------------------- auth

@router.post("/auth/signup")
async def signup(request: Request, c: Ctx = Depends(ctx)):
    body = await request.json()
    token, _ = c.auth.ensure_session(c.token)
    try:
        result = c.auth.start_registration(
            token, email=str(body.get("email", "")),
            display_name=str(body.get("name", "")),
            password=str(body.get("password", "")),
            restart_invalid_flow=True)
    except AuthConflict as e:
        return err(409, "conflict", str(e))
    except (AuthValidationError, AuthError) as e:
        return err(400, "invalid", str(e))
    response = JSONResponse({"ok": True, "pending_id": result["pending_id"],
                             "mail_status": result["mail_status"]})
    _set_session_cookie(response, request, c.services, token)
    return response


@router.get("/auth/mail")
def auth_mail(purpose: str, c: Ctx = Depends(ctx)):
    """Local outbox viewer for the offline demo (LOCAL_ONLY mail)."""
    if not c.token:
        return err(401, "unauthorized", "No session.")
    try:
        mail = c.auth.local_mail_for_session(c.token, purpose=purpose)
    except ValueError:
        return err(400, "invalid", "Unknown mail purpose.")
    if mail is None:
        return err(404, "not-found", "No local mail for this session.")
    return {"purpose": mail["purpose"], "template": mail["template"],
            "verification_code": mail["verification_code"]}


@router.post("/auth/verify")
async def verify(request: Request, c: Ctx = Depends(ctx)):
    body = await request.json()
    if not c.token:
        return err(401, "unauthorized", "No session.")
    try:
        c.auth.verify_registration_code(c.token, str(body.get("code", "")))
        result = c.auth.complete_registration(c.token)
    except AuthError as e:
        return err(400, "invalid", str(e))
    account = result["account"]
    with c.connect() as conn:
        _create_user_and_workspace(
            conn, account_id=account["account_id"],
            email=account["email_normalized"],
            name=account["display_name"])
    response = JSONResponse({"ok": True, "account": account})
    _set_session_cookie(response, request, c.services, result["session_token"])
    return response


@router.post("/auth/login")
async def login(request: Request, c: Ctx = Depends(ctx)):
    body = await request.json()
    token, _ = c.auth.ensure_session(c.token)
    try:
        result = c.auth.sign_in(token, email=str(body.get("email", "")),
                                password=str(body.get("password", "")))
    except AuthError:
        return err(401, "bad-credentials",
                   "The email or password you entered is incorrect.")
    account = result["account"]
    with c.connect() as conn:
        row = conn.execute("SELECT 1 FROM az_users WHERE user_id=?",
                           (account["account_id"],)).fetchone()
        if row is None:
            _create_user_and_workspace(
                conn, account_id=account["account_id"],
                email=account["email_normalized"],
                name=account["display_name"])
    response = JSONResponse({"ok": True, "account": account})
    _set_session_cookie(response, request, c.services, result["session_token"])
    return response


@router.post("/auth/logout")
def logout(request: Request, c: Ctx = Depends(ctx)):
    c.auth.sign_out(c.token)
    response = JSONResponse({"ok": True})
    response.delete_cookie(_cookie_name(request, c.services), path="/")
    response.delete_cookie(c.services.cookie_name, path="/")
    response.delete_cookie("asana_workspace", path="/")
    return response


@router.post("/auth/forgot")
async def forgot(request: Request, c: Ctx = Depends(ctx)):
    body = await request.json()
    token, _ = c.auth.ensure_session(c.token)
    try:
        c.auth.start_password_reset(token, email=str(body.get("email", "")),
                                    restart_invalid_flow=True)
    except AuthError as e:
        return err(400, "invalid", str(e))
    # Same response whether or not the account exists (no enumeration).
    response = JSONResponse({"ok": True})
    _set_session_cookie(response, request, c.services, token)
    return response


@router.post("/auth/reset")
async def reset(request: Request, c: Ctx = Depends(ctx)):
    body = await request.json()
    if not c.token:
        return err(401, "unauthorized", "No session.")
    try:
        c.auth.verify_password_reset_code(c.token, str(body.get("code", "")))
        c.auth.complete_password_reset(
            c.token, new_password=str(body.get("password", "")))
    except AuthError as e:
        return err(400, "invalid", str(e))
    return {"ok": True}


@router.get("/me")
def me(c: Ctx = Depends(ctx)):
    if (resp := require_auth(c)) is not None:
        return resp
    with c.connect() as conn:
        workspaces = d.rows_to_dicts(conn.execute(
            "SELECT w.workspace_id, w.name, w.plan, m.role FROM az_workspaces w"
            " JOIN az_workspace_members m ON m.workspace_id=w.workspace_id"
            " WHERE m.user_id=? ORDER BY w.created_at", (c.account_id,)).fetchall())
        role = c.role(conn)
    return {"user": _public_user(c.user), "workspace": c.workspace,
            "workspaces": workspaces, "role": role}


# ---------------------------------------------------------------- workspace

@router.post("/workspaces")
async def create_workspace(request: Request, c: Ctx = Depends(ctx)):
    if (resp := require_auth(c)) is not None:
        return resp
    body = await request.json()
    name = str(body.get("name", "")).strip()
    if not 1 <= len(name) <= 120:
        return err(400, "invalid", "Workspace name is required.")
    ws_id = d.new_id("workspace")
    with c.connect() as conn:
        conn.execute(
            "INSERT INTO az_workspaces(workspace_id, name, owner_user_id,"
            " created_at) VALUES (?,?,?,?)", (ws_id, name, c.account_id, d.now()))
        conn.execute(
            "INSERT INTO az_workspace_members(workspace_id, user_id, role,"
            " joined_at) VALUES (?,?,'admin',?)", (ws_id, c.account_id, d.now()))
        d.record_activity(conn, workspace_id=ws_id, actor_user_id=c.account_id,
                          verb="created", object_type="workspace",
                          object_id=ws_id, object_name=name)
    response = JSONResponse({"ok": True, "workspace_id": ws_id})
    response.set_cookie("asana_workspace", ws_id, path="/")
    return response


@router.post("/workspace/switch")
async def switch_workspace(request: Request, c: Ctx = Depends(ctx)):
    if (resp := require_auth(c)) is not None:
        return resp
    body = await request.json()
    ws_id = str(body.get("workspace_id", ""))
    with c.connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM az_workspace_members WHERE workspace_id=? AND user_id=?",
            (ws_id, c.account_id)).fetchone()
    if row is None:
        return err(404, "not-found", "You are not a member of that workspace.")
    response = JSONResponse({"ok": True})
    response.set_cookie("asana_workspace", ws_id, path="/")
    return response


@router.patch("/workspace")
async def update_workspace(request: Request, c: Ctx = Depends(ctx)):
    if (resp := require_auth(c)) is not None:
        return resp
    body = await request.json()
    with c.connect() as conn:
        if c.role(conn) != "admin":
            return err(403, "forbidden", "Only workspace admins can change settings.")
        name = str(body.get("name", "")).strip()
        if not 1 <= len(name) <= 120:
            return err(400, "invalid", "Workspace name is required.")
        conn.execute("UPDATE az_workspaces SET name=? WHERE workspace_id=?",
                     (name, c.ws_id))
        d.record_activity(conn, workspace_id=c.ws_id, actor_user_id=c.account_id,
                          verb="renamed", object_type="workspace",
                          object_id=c.ws_id, object_name=name)
    return {"ok": True}


@router.get("/members")
def members(c: Ctx = Depends(ctx)):
    if (resp := require_auth(c)) is not None:
        return resp
    with c.connect() as conn:
        rows = d.rows_to_dicts(conn.execute(
            "SELECT u.user_id, u.display_name, u.email, u.initials,"
            " u.avatar_color, u.role_title, u.synthetic, m.role"
            " FROM az_workspace_members m JOIN az_users u ON u.user_id=m.user_id"
            " WHERE m.workspace_id=? ORDER BY u.display_name", (c.ws_id,)).fetchall())
        invites = d.rows_to_dicts(conn.execute(
            "SELECT invite_id, email, role, status, created_at FROM az_invites"
            " WHERE workspace_id=? ORDER BY created_at DESC", (c.ws_id,)).fetchall())
    return {"members": rows, "invites": invites}


@router.post("/invites")
async def invite(request: Request, c: Ctx = Depends(ctx)):
    if (resp := require_auth(c)) is not None:
        return resp
    body = await request.json()
    email = str(body.get("email", "")).strip().lower()
    role = body.get("role", "member")
    if "@" not in email or "." not in email.split("@")[-1]:
        return err(400, "invalid", "Enter a valid email address.")
    if role not in ("member", "admin"):
        return err(400, "invalid", "Role must be member or admin.")
    with c.connect() as conn:
        conn.execute(
            "INSERT INTO az_invites(invite_id, workspace_id, email, role,"
            " invited_by, created_at) VALUES (?,?,?,?,?,?)",
            (d.new_id("invite"), c.ws_id, email, role, c.account_id, d.now()))
        d.record_activity(conn, workspace_id=c.ws_id, actor_user_id=c.account_id,
                          verb="invited", object_type="invite", object_id=email,
                          object_name=email,
                          detail="Local simulated invite; no email is sent")
    return {"ok": True, "simulated": True,
            "note": "Offline clone: the invite is recorded locally only."}


@router.patch("/members/{user_id}")
async def change_role(user_id: str, request: Request, c: Ctx = Depends(ctx)):
    if (resp := require_auth(c)) is not None:
        return resp
    body = await request.json()
    role = body.get("role")
    if role not in ("member", "admin"):
        return err(400, "invalid", "Role must be member or admin.")
    with c.connect() as conn:
        if c.role(conn) != "admin":
            return err(403, "forbidden", "Only admins can change member roles.")
        if user_id == c.account_id:
            return err(400, "invalid", "You cannot change your own role.")
        updated = conn.execute(
            "UPDATE az_workspace_members SET role=? WHERE workspace_id=? AND user_id=?",
            (role, c.ws_id, user_id)).rowcount
        if not updated:
            return err(404, "not-found", "Member not found.")
        d.record_activity(conn, workspace_id=c.ws_id, actor_user_id=c.account_id,
                          verb="changed-role", object_type="member",
                          object_id=user_id, detail=role)
    return {"ok": True}


# ---------------------------------------------------------------- projects

def _project_or_none(conn: sqlite3.Connection, c: Ctx, project_id: str,
                     *, include_deleted: bool = False):
    row = conn.execute(
        "SELECT * FROM az_projects WHERE project_id=? AND workspace_id=?",
        (project_id, c.ws_id)).fetchone()
    if row is None:
        return None
    if row["deleted_at"] and not include_deleted:
        return None
    return d.row_to_dict(row)


@router.get("/projects")
def list_projects(c: Ctx = Depends(ctx), archived: int = 0):
    if (resp := require_auth(c)) is not None:
        return resp
    with c.connect() as conn:
        rows = d.rows_to_dicts(conn.execute(
            "SELECT p.*, (SELECT COUNT(*) FROM az_tasks t WHERE t.project_id="
            "p.project_id AND t.deleted_at IS NULL AND t.parent_task_id IS NULL)"
            " AS task_count FROM az_projects p WHERE p.workspace_id=?"
            " AND p.deleted_at IS NULL AND p.archived=? ORDER BY p.created_at",
            (c.ws_id, archived)).fetchall())
    return {"projects": rows}


@router.post("/projects")
async def create_project(request: Request, c: Ctx = Depends(ctx)):
    if (resp := require_auth(c)) is not None:
        return resp
    body = await request.json()
    name = str(body.get("name", "")).strip()
    if not 1 <= len(name) <= 200:
        return err(400, "invalid", "Project name is required.")
    template = next((t for t in PROJECT_TEMPLATES
                     if t["id"] == body.get("template", "blank")), None)
    if template is None:
        return err(400, "invalid", "Unknown template.")
    color = str(body.get("color", "#4573d2"))
    view = body.get("view", "list")
    if view not in ("list", "board", "calendar", "timeline"):
        return err(400, "invalid", "Unknown default view.")
    project_id = d.new_id("project")
    with c.connect() as conn:
        conn.execute(
            "INSERT INTO az_projects(project_id, workspace_id, portfolio_id, name,"
            " description, color, owner_user_id, default_view,"
            " created_from_template, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (project_id, c.ws_id, body.get("portfolio_id"), name,
             str(body.get("description", "")), color, c.account_id, view,
             template["id"], d.now()))
        conn.execute(
            "INSERT INTO az_project_memberships(project_id, user_id, access)"
            " VALUES (?,?,'admin')", (project_id, c.account_id))
        sec_ids = []
        for i, sname in enumerate(template["sections"]):
            sid = d.new_id("section")
            sec_ids.append(sid)
            conn.execute(
                "INSERT INTO az_sections(section_id, project_id, name, sort_order)"
                " VALUES (?,?,?,?)", (sid, project_id, sname, i))
        for i, (tname, sec_i) in enumerate(template["tasks"]):
            conn.execute(
                "INSERT INTO az_tasks(task_id, workspace_id, project_id,"
                " section_id, name, creator_user_id, sort_order, created_at,"
                " modified_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (d.new_id("task"), c.ws_id, project_id, sec_ids[sec_i], tname,
                 c.account_id, i, d.now(), d.now()))
        d.record_activity(conn, workspace_id=c.ws_id, actor_user_id=c.account_id,
                          verb="created", object_type="project",
                          object_id=project_id, object_name=name)
    return {"ok": True, "project_id": project_id}


@router.get("/projects/{project_id}")
def get_project(project_id: str, c: Ctx = Depends(ctx)):
    if (resp := require_auth(c)) is not None:
        return resp
    with c.connect() as conn:
        project = _project_or_none(conn, c, project_id, include_deleted=True)
        if project is None:
            return err(404, "not-found", "Project not found.")
        sections = d.rows_to_dicts(conn.execute(
            "SELECT * FROM az_sections WHERE project_id=? ORDER BY sort_order",
            (project_id,)).fetchall())
        rules = d.rows_to_dicts(conn.execute(
            "SELECT * FROM az_rules WHERE project_id=? ORDER BY created_at",
            (project_id,)).fetchall())
        memberships = d.rows_to_dicts(conn.execute(
            "SELECT m.user_id, m.access, u.display_name, u.initials, u.avatar_color"
            " FROM az_project_memberships m JOIN az_users u ON u.user_id=m.user_id"
            " WHERE m.project_id=?", (project_id,)).fetchall())
    return {"project": project, "sections": sections, "rules": rules,
            "members": memberships}


@router.patch("/projects/{project_id}")
async def update_project(project_id: str, request: Request, c: Ctx = Depends(ctx)):
    if (resp := require_auth(c)) is not None:
        return resp
    body = await request.json()
    allowed = {"name", "description", "color", "icon", "status", "status_note",
               "default_view", "archived", "starred", "portfolio_id",
               "share_mode"}
    updates = {k: v for k, v in body.items() if k in allowed}
    if not updates:
        return err(400, "invalid", "Nothing to update.")
    if "name" in updates and not 1 <= len(str(updates["name"]).strip()) <= 200:
        return err(400, "invalid", "Project name is required.")
    if "status" in updates and updates["status"] not in (
            "on_track", "at_risk", "off_track", "on_hold", "complete"):
        return err(400, "invalid", "Unknown status.")
    if "share_mode" in updates and updates["share_mode"] not in (
            "workspace", "private", "public_link"):
        return err(400, "invalid", "Unknown share mode.")
    with c.connect() as conn:
        project = _project_or_none(conn, c, project_id, include_deleted=True)
        if project is None:
            return err(404, "not-found", "Project not found.")
        sets = ", ".join(f"{k}=?" for k in updates)
        conn.execute(f"UPDATE az_projects SET {sets} WHERE project_id=?",
                     (*updates.values(), project_id))
        verb = ("archived" if updates.get("archived") == 1 else
                "unarchived" if updates.get("archived") == 0 else "updated")
        d.record_activity(conn, workspace_id=c.ws_id, actor_user_id=c.account_id,
                          verb=verb, object_type="project", object_id=project_id,
                          object_name=str(updates.get("name", project["name"])),
                          detail=json.dumps(sorted(updates)))
    return {"ok": True}


@router.delete("/projects/{project_id}")
def delete_project(project_id: str, c: Ctx = Depends(ctx)):
    if (resp := require_auth(c)) is not None:
        return resp
    with c.connect() as conn:
        project = _project_or_none(conn, c, project_id)
        if project is None:
            return err(404, "not-found", "Project not found.")
        conn.execute("UPDATE az_projects SET deleted_at=? WHERE project_id=?",
                     (d.now(), project_id))
        d.record_activity(conn, workspace_id=c.ws_id, actor_user_id=c.account_id,
                          verb="deleted", object_type="project",
                          object_id=project_id, object_name=project["name"])
    return {"ok": True}


@router.post("/projects/{project_id}/sections")
async def create_section(project_id: str, request: Request, c: Ctx = Depends(ctx)):
    if (resp := require_auth(c)) is not None:
        return resp
    body = await request.json()
    name = str(body.get("name", "")).strip()
    if not 1 <= len(name) <= 120:
        return err(400, "invalid", "Section name is required.")
    with c.connect() as conn:
        if _project_or_none(conn, c, project_id) is None:
            return err(404, "not-found", "Project not found.")
        order = conn.execute(
            "SELECT COALESCE(MAX(sort_order),-1)+1 AS o FROM az_sections"
            " WHERE project_id=?", (project_id,)).fetchone()["o"]
        sid = d.new_id("section")
        conn.execute(
            "INSERT INTO az_sections(section_id, project_id, name, sort_order)"
            " VALUES (?,?,?,?)", (sid, project_id, name, order))
    return {"ok": True, "section_id": sid}


@router.patch("/sections/{section_id}")
async def rename_section(section_id: str, request: Request, c: Ctx = Depends(ctx)):
    if (resp := require_auth(c)) is not None:
        return resp
    body = await request.json()
    name = str(body.get("name", "")).strip()
    if not 1 <= len(name) <= 120:
        return err(400, "invalid", "Section name is required.")
    with c.connect() as conn:
        row = conn.execute(
            "SELECT s.section_id FROM az_sections s JOIN az_projects p"
            " ON p.project_id=s.project_id WHERE s.section_id=? AND p.workspace_id=?",
            (section_id, c.ws_id)).fetchone()
        if row is None:
            return err(404, "not-found", "Section not found.")
        conn.execute("UPDATE az_sections SET name=? WHERE section_id=?",
                     (name, section_id))
    return {"ok": True}


@router.delete("/sections/{section_id}")
def delete_section(section_id: str, c: Ctx = Depends(ctx)):
    if (resp := require_auth(c)) is not None:
        return resp
    with c.connect() as conn:
        row = conn.execute(
            "SELECT s.section_id, s.project_id FROM az_sections s JOIN az_projects p"
            " ON p.project_id=s.project_id WHERE s.section_id=? AND p.workspace_id=?",
            (section_id, c.ws_id)).fetchone()
        if row is None:
            return err(404, "not-found", "Section not found.")
        n = conn.execute(
            "SELECT COUNT(*) AS n FROM az_tasks WHERE section_id=?"
            " AND deleted_at IS NULL", (section_id,)).fetchone()["n"]
        if n:
            return err(409, "conflict",
                       "Move or delete this section's tasks first.")
        conn.execute("DELETE FROM az_sections WHERE section_id=?", (section_id,))
    return {"ok": True}


# ---------------------------------------------------------------- tasks

TASK_FIELDS = (
    "t.*, u.display_name AS assignee_name, u.initials AS assignee_initials,"
    " u.avatar_color AS assignee_color,"
    " (SELECT COUNT(*) FROM az_comments cm WHERE cm.task_id=t.task_id)"
    " AS comment_count,"
    " (SELECT COUNT(*) FROM az_tasks st WHERE st.parent_task_id=t.task_id"
    "  AND st.deleted_at IS NULL) AS subtask_count,"
    " (SELECT COUNT(*) FROM az_attachments a WHERE a.task_id=t.task_id)"
    " AS attachment_count"
)


def _task_query(conn: sqlite3.Connection, where: str, params: tuple) -> list[dict]:
    return d.rows_to_dicts(conn.execute(
        f"SELECT {TASK_FIELDS} FROM az_tasks t LEFT JOIN az_users u"
        f" ON u.user_id=t.assignee_user_id WHERE {where}", params).fetchall())


def _apply_filters(request: Request) -> tuple[str, list]:
    q = request.query_params
    where, params = [], []
    if q.get("completed") in ("0", "1"):
        where.append("t.completed=?")
        params.append(int(q["completed"]))
    if q.get("assignee"):
        where.append("t.assignee_user_id=?")
        params.append(q["assignee"])
    if q.get("priority"):
        where.append("t.priority=?")
        params.append(q["priority"])
    if q.get("due_before"):
        where.append("t.due_date IS NOT NULL AND t.due_date<=?")
        params.append(q["due_before"])
    if q.get("due_after"):
        where.append("t.due_date IS NOT NULL AND t.due_date>=?")
        params.append(q["due_after"])
    return (" AND " + " AND ".join(where) if where else ""), params


@router.get("/projects/{project_id}/tasks")
def project_tasks(project_id: str, request: Request, c: Ctx = Depends(ctx)):
    if (resp := require_auth(c)) is not None:
        return resp
    extra, params = _apply_filters(request)
    sort = request.query_params.get("sort", "manual")
    order = {"manual": "t.section_id, t.sort_order",
             "due_date": "t.due_date IS NULL, t.due_date",
             "alphabetical": "LOWER(t.name)",
             "created": "t.created_at DESC"}.get(sort)
    if order is None:
        return err(400, "invalid", "Unknown sort.")
    with c.connect() as conn:
        if _project_or_none(conn, c, project_id) is None:
            return err(404, "not-found", "Project not found.")
        tasks = d.rows_to_dicts(conn.execute(
            f"SELECT {TASK_FIELDS} FROM az_tasks t LEFT JOIN az_users u"
            " ON u.user_id=t.assignee_user_id WHERE t.project_id=?"
            " AND t.deleted_at IS NULL AND t.parent_task_id IS NULL"
            f"{extra} ORDER BY {order}", (project_id, *params)).fetchall())
        deps = d.rows_to_dicts(conn.execute(
            "SELECT dep.* FROM az_task_dependencies dep JOIN az_tasks t"
            " ON t.task_id=dep.task_id WHERE t.project_id=?",
            (project_id,)).fetchall())
    return {"tasks": tasks, "dependencies": deps}


@router.get("/my-tasks")
def my_tasks(request: Request, c: Ctx = Depends(ctx)):
    if (resp := require_auth(c)) is not None:
        return resp
    extra, params = _apply_filters(request)
    with c.connect() as conn:
        tasks = _task_query(
            conn,
            "t.workspace_id=? AND t.assignee_user_id=? AND t.deleted_at IS NULL"
            + extra + " ORDER BY t.completed, t.due_date IS NULL, t.due_date",
            (c.ws_id, c.account_id, *params))
    return {"tasks": tasks}


@router.post("/tasks")
async def create_task(request: Request, c: Ctx = Depends(ctx)):
    if (resp := require_auth(c)) is not None:
        return resp
    body = await request.json()
    name = str(body.get("name", "")).strip()
    if not 1 <= len(name) <= 400:
        return err(400, "invalid", "Task name is required.")
    project_id = body.get("project_id")
    section_id = body.get("section_id")
    parent_task_id = body.get("parent_task_id")
    if not valid_date(body.get("due_date")) or not valid_date(body.get("start_date")):
        return err(400, "invalid", "Enter dates as YYYY-MM-DD.")
    with c.connect() as conn:
        if project_id:
            project = _project_or_none(conn, c, project_id)
            if project is None:
                return err(404, "not-found", "Project not found.")
            if section_id:
                sec = conn.execute(
                    "SELECT 1 FROM az_sections WHERE section_id=? AND project_id=?",
                    (section_id, project_id)).fetchone()
                if sec is None:
                    return err(400, "invalid", "Section does not belong to project.")
            else:
                first = conn.execute(
                    "SELECT section_id FROM az_sections WHERE project_id=?"
                    " ORDER BY sort_order LIMIT 1", (project_id,)).fetchone()
                section_id = first["section_id"] if first else None
        if parent_task_id:
            parent = conn.execute(
                "SELECT task_id, project_id FROM az_tasks WHERE task_id=?"
                " AND workspace_id=? AND deleted_at IS NULL",
                (parent_task_id, c.ws_id)).fetchone()
            if parent is None:
                return err(404, "not-found", "Parent task not found.")
            project_id = project_id or parent["project_id"]
        task_id = d.new_id("task")
        order = conn.execute(
            "SELECT COALESCE(MAX(sort_order),-1)+1 AS o FROM az_tasks"
            " WHERE section_id IS ? AND parent_task_id IS ?",
            (section_id, parent_task_id)).fetchone()["o"]
        assignee = body.get("assignee_user_id") or None
        conn.execute(
            "INSERT INTO az_tasks(task_id, workspace_id, project_id, section_id,"
            " parent_task_id, name, notes, assignee_user_id, creator_user_id,"
            " due_date, start_date, priority, task_status, sort_order,"
            " created_at, modified_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (task_id, c.ws_id, project_id, section_id, parent_task_id, name,
             str(body.get("notes", "")), assignee, c.account_id,
             body.get("due_date"), body.get("start_date"), body.get("priority"),
             body.get("task_status"), order, d.now(), d.now()))
        d.record_activity(conn, workspace_id=c.ws_id, actor_user_id=c.account_id,
                          verb="created", object_type="task", object_id=task_id,
                          object_name=name)
        if assignee and assignee != c.account_id:
            d.notify(conn, user_id=assignee, workspace_id=c.ws_id,
                     kind="assigned", text=f"{c.user['display_name']} assigned"
                     f" you “{name}”", task_id=task_id)
    return {"ok": True, "task_id": task_id}


@router.get("/tasks/{task_id}")
def get_task(task_id: str, c: Ctx = Depends(ctx)):
    if (resp := require_auth(c)) is not None:
        return resp
    with c.connect() as conn:
        rows = _task_query(conn, "t.task_id=? AND t.workspace_id=?",
                           (task_id, c.ws_id))
        if not rows:
            return err(404, "not-found", "Task not found.")
        task = rows[0]
        subtasks = _task_query(
            conn, "t.parent_task_id=? AND t.deleted_at IS NULL"
            " ORDER BY t.sort_order", (task_id,))
        comments = d.rows_to_dicts(conn.execute(
            "SELECT cm.*, u.display_name, u.initials, u.avatar_color"
            " FROM az_comments cm JOIN az_users u ON u.user_id=cm.author_user_id"
            " WHERE cm.task_id=? ORDER BY cm.created_at", (task_id,)).fetchall())
        deps = d.rows_to_dicts(conn.execute(
            "SELECT dep.depends_on_task_id, t.name FROM az_task_dependencies dep"
            " JOIN az_tasks t ON t.task_id=dep.depends_on_task_id"
            " WHERE dep.task_id=?", (task_id,)).fetchall())
        blocking = d.rows_to_dicts(conn.execute(
            "SELECT dep.task_id, t.name FROM az_task_dependencies dep"
            " JOIN az_tasks t ON t.task_id=dep.task_id"
            " WHERE dep.depends_on_task_id=?", (task_id,)).fetchall())
        attachments = d.rows_to_dicts(conn.execute(
            "SELECT attachment_id, filename, size_bytes, content_type,"
            " uploader_user_id, created_at FROM az_attachments WHERE task_id=?"
            " ORDER BY created_at", (task_id,)).fetchall())
        collaborators = d.rows_to_dicts(conn.execute(
            "SELECT tc.user_id, u.display_name, u.initials, u.avatar_color"
            " FROM az_task_collaborators tc JOIN az_users u ON u.user_id=tc.user_id"
            " WHERE tc.task_id=?", (task_id,)).fetchall())
        activity = d.rows_to_dicts(conn.execute(
            "SELECT a.*, u.display_name FROM az_activity a JOIN az_users u"
            " ON u.user_id=a.actor_user_id WHERE a.object_type='task'"
            " AND a.object_id=? ORDER BY a.created_at DESC LIMIT 30",
            (task_id,)).fetchall())
        project = None
        if task["project_id"]:
            project = _project_or_none(conn, c, task["project_id"],
                                       include_deleted=True)
    return {"task": task, "subtasks": subtasks, "comments": comments,
            "dependencies": deps, "blocking": blocking,
            "attachments": attachments, "collaborators": collaborators,
            "activity": activity, "project": project}


@router.patch("/tasks/{task_id}")
async def update_task(task_id: str, request: Request, c: Ctx = Depends(ctx)):
    if (resp := require_auth(c)) is not None:
        return resp
    body = await request.json()
    allowed = {"name", "notes", "assignee_user_id", "due_date", "start_date",
               "priority", "task_status", "completed", "section_id",
               "sort_order", "project_id"}
    updates = {k: v for k, v in body.items() if k in allowed}
    if not updates:
        return err(400, "invalid", "Nothing to update.")
    if "name" in updates and not 1 <= len(str(updates["name"]).strip()) <= 400:
        return err(400, "invalid", "Task name cannot be empty.")
    for key in ("due_date", "start_date"):
        if key in updates and not valid_date(updates[key]):
            return err(400, "invalid", "Enter dates as YYYY-MM-DD.")
    with c.connect() as conn:
        task = conn.execute(
            "SELECT * FROM az_tasks WHERE task_id=? AND workspace_id=?"
            " AND deleted_at IS NULL", (task_id, c.ws_id)).fetchone()
        if task is None:
            return err(404, "not-found", "Task not found.")
        if "completed" in updates:
            done = 1 if updates["completed"] else 0
            if done and task["completed"] == 0:
                blocked_by = conn.execute(
                    "SELECT COUNT(*) AS n FROM az_task_dependencies dep JOIN"
                    " az_tasks bt ON bt.task_id=dep.depends_on_task_id"
                    " WHERE dep.task_id=? AND bt.completed=0"
                    " AND bt.deleted_at IS NULL", (task_id,)).fetchone()["n"]
                if blocked_by and not body.get("force"):
                    return err(409, "blocked",
                               "This task is waiting on an incomplete dependency.")
            updates["completed"] = done
            updates["completed_at"] = d.now() if done else None
        if "section_id" in updates and updates["section_id"]:
            sec = conn.execute(
                "SELECT project_id FROM az_sections WHERE section_id=?",
                (updates["section_id"],)).fetchone()
            if sec is None:
                return err(400, "invalid", "Unknown section.")
            updates.setdefault("project_id", sec["project_id"])
        if "project_id" in updates and updates["project_id"]:
            if _project_or_none(conn, c, updates["project_id"]) is None:
                return err(404, "not-found", "Target project not found.")
        if updates.get("assignee_user_id"):
            member = conn.execute(
                "SELECT 1 FROM az_workspace_members WHERE workspace_id=?"
                " AND user_id=?", (c.ws_id, updates["assignee_user_id"])).fetchone()
            if member is None:
                return err(400, "invalid", "Assignee is not a workspace member.")
        updates["modified_at"] = d.now()
        sets = ", ".join(f"{k}=?" for k in updates)
        conn.execute(f"UPDATE az_tasks SET {sets} WHERE task_id=?",
                     (*updates.values(), task_id))
        verb = ("completed" if updates.get("completed") == 1 else
                "uncompleted" if updates.get("completed") == 0 else "updated")
        d.record_activity(conn, workspace_id=c.ws_id, actor_user_id=c.account_id,
                          verb=verb, object_type="task", object_id=task_id,
                          object_name=task["name"],
                          detail=json.dumps(sorted(set(updates) - {"modified_at"})))
        new_assignee = updates.get("assignee_user_id")
        if new_assignee and new_assignee not in (task["assignee_user_id"],
                                                 c.account_id):
            d.notify(conn, user_id=new_assignee, workspace_id=c.ws_id,
                     kind="assigned", text=f"{c.user['display_name']} assigned"
                     f" you “{task['name']}”", task_id=task_id)
    return {"ok": True}


@router.post("/tasks/bulk")
async def bulk_tasks(request: Request, c: Ctx = Depends(ctx)):
    if (resp := require_auth(c)) is not None:
        return resp
    body = await request.json()
    ids = body.get("task_ids")
    action = body.get("action")
    if not isinstance(ids, list) or not ids or len(ids) > 200:
        return err(400, "invalid", "Select between 1 and 200 tasks.")
    if action not in ("complete", "uncomplete", "delete", "assign",
                      "set_due_date", "move_section"):
        return err(400, "invalid", "Unknown bulk action.")
    if action == "set_due_date" and (
            body.get("due_date") is None or not valid_date(body.get("due_date"))):
        return err(400, "invalid", "Enter the due date as YYYY-MM-DD.")
    changed = 0
    with c.connect() as conn:
        for task_id in ids:
            task = conn.execute(
                "SELECT task_id, name FROM az_tasks WHERE task_id=?"
                " AND workspace_id=? AND deleted_at IS NULL",
                (task_id, c.ws_id)).fetchone()
            if task is None:
                continue
            if action == "complete":
                conn.execute("UPDATE az_tasks SET completed=1, completed_at=?,"
                             " modified_at=? WHERE task_id=?",
                             (d.now(), d.now(), task_id))
            elif action == "uncomplete":
                conn.execute("UPDATE az_tasks SET completed=0, completed_at=NULL,"
                             " modified_at=? WHERE task_id=?", (d.now(), task_id))
            elif action == "delete":
                conn.execute("UPDATE az_tasks SET deleted_at=? WHERE task_id=?",
                             (d.now(), task_id))
            elif action == "assign":
                conn.execute("UPDATE az_tasks SET assignee_user_id=?,"
                             " modified_at=? WHERE task_id=?",
                             (body.get("assignee_user_id"), d.now(), task_id))
            elif action == "set_due_date":
                conn.execute("UPDATE az_tasks SET due_date=?, modified_at=?"
                             " WHERE task_id=?",
                             (body.get("due_date"), d.now(), task_id))
            elif action == "move_section":
                conn.execute("UPDATE az_tasks SET section_id=?, modified_at=?"
                             " WHERE task_id=?",
                             (body.get("section_id"), d.now(), task_id))
            changed += 1
        d.record_activity(conn, workspace_id=c.ws_id, actor_user_id=c.account_id,
                          verb=f"bulk-{action}", object_type="tasks",
                          object_id=",".join(ids[:5]), detail=f"{changed} tasks")
    return {"ok": True, "changed": changed}


@router.delete("/tasks/{task_id}")
def delete_task(task_id: str, c: Ctx = Depends(ctx)):
    if (resp := require_auth(c)) is not None:
        return resp
    with c.connect() as conn:
        task = conn.execute(
            "SELECT name FROM az_tasks WHERE task_id=? AND workspace_id=?"
            " AND deleted_at IS NULL", (task_id, c.ws_id)).fetchone()
        if task is None:
            return err(404, "not-found", "Task not found.")
        conn.execute("UPDATE az_tasks SET deleted_at=? WHERE task_id=?",
                     (d.now(), task_id))
        d.record_activity(conn, workspace_id=c.ws_id, actor_user_id=c.account_id,
                          verb="deleted", object_type="task", object_id=task_id,
                          object_name=task["name"])
    return {"ok": True}


@router.post("/tasks/{task_id}/dependencies")
async def add_dependency(task_id: str, request: Request, c: Ctx = Depends(ctx)):
    if (resp := require_auth(c)) is not None:
        return resp
    body = await request.json()
    dep_id = str(body.get("depends_on_task_id", ""))
    if dep_id == task_id:
        return err(400, "invalid", "A task cannot depend on itself.")
    with c.connect() as conn:
        for tid in (task_id, dep_id):
            if conn.execute("SELECT 1 FROM az_tasks WHERE task_id=?"
                            " AND workspace_id=? AND deleted_at IS NULL",
                            (tid, c.ws_id)).fetchone() is None:
                return err(404, "not-found", "Task not found.")
        reverse = conn.execute(
            "SELECT 1 FROM az_task_dependencies WHERE task_id=?"
            " AND depends_on_task_id=?", (dep_id, task_id)).fetchone()
        if reverse:
            return err(409, "conflict", "That would create a dependency cycle.")
        conn.execute(
            "INSERT OR IGNORE INTO az_task_dependencies(task_id,"
            " depends_on_task_id) VALUES (?,?)", (task_id, dep_id))
    return {"ok": True}


@router.delete("/tasks/{task_id}/dependencies/{dep_id}")
def remove_dependency(task_id: str, dep_id: str, c: Ctx = Depends(ctx)):
    if (resp := require_auth(c)) is not None:
        return resp
    with c.connect() as conn:
        conn.execute("DELETE FROM az_task_dependencies WHERE task_id=?"
                     " AND depends_on_task_id=?", (task_id, dep_id))
    return {"ok": True}


# ------------------------------------------------------- comments/attachments

@router.post("/tasks/{task_id}/comments")
async def add_comment(task_id: str, request: Request, c: Ctx = Depends(ctx)):
    if (resp := require_auth(c)) is not None:
        return resp
    body = await request.json()
    text = str(body.get("body", "")).strip()
    if not 1 <= len(text) <= 5000:
        return err(400, "invalid", "Comment text is required.")
    with c.connect() as conn:
        task = conn.execute(
            "SELECT name, assignee_user_id FROM az_tasks WHERE task_id=?"
            " AND workspace_id=? AND deleted_at IS NULL",
            (task_id, c.ws_id)).fetchone()
        if task is None:
            return err(404, "not-found", "Task not found.")
        cid = d.new_id("comment")
        conn.execute(
            "INSERT INTO az_comments(comment_id, task_id, author_user_id, body,"
            " created_at) VALUES (?,?,?,?,?)",
            (cid, task_id, c.account_id, text, d.now()))
        conn.execute(
            "INSERT OR IGNORE INTO az_task_collaborators(task_id, user_id)"
            " VALUES (?,?)", (task_id, c.account_id))
        d.record_activity(conn, workspace_id=c.ws_id, actor_user_id=c.account_id,
                          verb="commented", object_type="task",
                          object_id=task_id, object_name=task["name"])
        # @-mention notifications for workspace members named in the text.
        members = conn.execute(
            "SELECT u.user_id, u.display_name FROM az_workspace_members m"
            " JOIN az_users u ON u.user_id=m.user_id WHERE m.workspace_id=?",
            (c.ws_id,)).fetchall()
        for m in members:
            if f"@{m['display_name']}" in text and m["user_id"] != c.account_id:
                d.notify(conn, user_id=m["user_id"], workspace_id=c.ws_id,
                         kind="mention", text=f"{c.user['display_name']}"
                         f" mentioned you on “{task['name']}”",
                         task_id=task_id)
        if task["assignee_user_id"] and task["assignee_user_id"] != c.account_id:
            d.notify(conn, user_id=task["assignee_user_id"], workspace_id=c.ws_id,
                     kind="comment", text=f"{c.user['display_name']} commented on"
                     f" “{task['name']}”", task_id=task_id)
    return {"ok": True, "comment_id": cid}


@router.patch("/comments/{comment_id}")
async def edit_comment(comment_id: str, request: Request, c: Ctx = Depends(ctx)):
    if (resp := require_auth(c)) is not None:
        return resp
    body = await request.json()
    text = str(body.get("body", "")).strip()
    if not 1 <= len(text) <= 5000:
        return err(400, "invalid", "Comment text is required.")
    with c.connect() as conn:
        row = conn.execute("SELECT author_user_id FROM az_comments"
                           " WHERE comment_id=?", (comment_id,)).fetchone()
        if row is None:
            return err(404, "not-found", "Comment not found.")
        if row["author_user_id"] != c.account_id:
            return err(403, "forbidden", "Only the author can edit a comment.")
        conn.execute("UPDATE az_comments SET body=?, edited_at=?"
                     " WHERE comment_id=?", (text, d.now(), comment_id))
    return {"ok": True}


@router.delete("/comments/{comment_id}")
def delete_comment(comment_id: str, c: Ctx = Depends(ctx)):
    if (resp := require_auth(c)) is not None:
        return resp
    with c.connect() as conn:
        row = conn.execute("SELECT author_user_id FROM az_comments"
                           " WHERE comment_id=?", (comment_id,)).fetchone()
        if row is None:
            return err(404, "not-found", "Comment not found.")
        if row["author_user_id"] != c.account_id:
            return err(403, "forbidden", "Only the author can delete a comment.")
        conn.execute("DELETE FROM az_comments WHERE comment_id=?", (comment_id,))
    return {"ok": True}


MAX_UPLOAD = 5 * 1024 * 1024


@router.post("/tasks/{task_id}/attachments")
async def upload_attachment(task_id: str, file: UploadFile, c: Ctx = Depends(ctx)):
    if (resp := require_auth(c)) is not None:
        return resp
    data = await file.read()
    if not data:
        return err(400, "invalid", "The file is empty.")
    if len(data) > MAX_UPLOAD:
        return err(413, "too-large", "Attachments are limited to 5 MB locally.")
    with c.connect() as conn:
        task = conn.execute(
            "SELECT name FROM az_tasks WHERE task_id=? AND workspace_id=?"
            " AND deleted_at IS NULL", (task_id, c.ws_id)).fetchone()
        if task is None:
            return err(404, "not-found", "Task not found.")
        aid = d.new_id("attachment")
        conn.execute(
            "INSERT INTO az_attachments(attachment_id, task_id, filename,"
            " size_bytes, content_type, data, uploader_user_id, created_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (aid, task_id, file.filename or "upload.bin", len(data),
             file.content_type or "application/octet-stream", data,
             c.account_id, d.now()))
        d.record_activity(conn, workspace_id=c.ws_id, actor_user_id=c.account_id,
                          verb="attached", object_type="task", object_id=task_id,
                          object_name=task["name"], detail=file.filename or "")
    return {"ok": True, "attachment_id": aid}


@router.get("/attachments/{attachment_id}")
def download_attachment(attachment_id: str, c: Ctx = Depends(ctx)):
    if (resp := require_auth(c)) is not None:
        return resp
    with c.connect() as conn:
        row = conn.execute(
            "SELECT a.* FROM az_attachments a JOIN az_tasks t ON t.task_id="
            "a.task_id WHERE a.attachment_id=? AND t.workspace_id=?",
            (attachment_id, c.ws_id)).fetchone()
    if row is None:
        return err(404, "not-found", "Attachment not found.")
    return Response(content=row["data"], media_type=row["content_type"],
                    headers={"Content-Disposition":
                             f'attachment; filename="{row["filename"]}"'})


# ------------------------------------------------- search / views / inbox

@router.get("/search")
def search(q: str = "", c: Ctx = Depends(ctx)):
    if (resp := require_auth(c)) is not None:
        return resp
    q = q.strip()
    if not q:
        return {"query": "", "tasks": [], "projects": [], "people": []}
    like = f"%{q}%"
    with c.connect() as conn:
        tasks = _task_query(
            conn, "t.workspace_id=? AND t.deleted_at IS NULL AND"
            " (t.name LIKE ? OR t.notes LIKE ?) ORDER BY t.modified_at DESC"
            " LIMIT 25", (c.ws_id, like, like))
        projects = d.rows_to_dicts(conn.execute(
            "SELECT project_id, name, color, icon, archived FROM az_projects"
            " WHERE workspace_id=? AND deleted_at IS NULL AND name LIKE ?"
            " LIMIT 10", (c.ws_id, like)).fetchall())
        people = d.rows_to_dicts(conn.execute(
            "SELECT u.user_id, u.display_name, u.initials, u.avatar_color"
            " FROM az_workspace_members m JOIN az_users u ON u.user_id=m.user_id"
            " WHERE m.workspace_id=? AND u.display_name LIKE ? LIMIT 10",
            (c.ws_id, like)).fetchall())
    return {"query": q, "tasks": tasks, "projects": projects, "people": people}


@router.get("/views")
def list_views(c: Ctx = Depends(ctx)):
    if (resp := require_auth(c)) is not None:
        return resp
    with c.connect() as conn:
        rows = d.rows_to_dicts(conn.execute(
            "SELECT * FROM az_saved_views WHERE workspace_id=? AND user_id=?"
            " ORDER BY created_at DESC", (c.ws_id, c.account_id)).fetchall())
    return {"views": rows}


@router.post("/views")
async def save_view(request: Request, c: Ctx = Depends(ctx)):
    if (resp := require_auth(c)) is not None:
        return resp
    body = await request.json()
    name = str(body.get("name", "")).strip()
    if not 1 <= len(name) <= 120:
        return err(400, "invalid", "View name is required.")
    vid = d.new_id("view")
    with c.connect() as conn:
        conn.execute(
            "INSERT INTO az_saved_views(view_id, workspace_id, user_id, name,"
            " query_json, created_at) VALUES (?,?,?,?,?,?)",
            (vid, c.ws_id, c.account_id,
             name, json.dumps(body.get("query", {})), d.now()))
    return {"ok": True, "view_id": vid}


@router.delete("/views/{view_id}")
def delete_view(view_id: str, c: Ctx = Depends(ctx)):
    if (resp := require_auth(c)) is not None:
        return resp
    with c.connect() as conn:
        removed = conn.execute(
            "DELETE FROM az_saved_views WHERE view_id=? AND user_id=?",
            (view_id, c.account_id)).rowcount
    if not removed:
        return err(404, "not-found", "Saved view not found.")
    return {"ok": True}


@router.get("/inbox")
def inbox(c: Ctx = Depends(ctx), archived: int = 0):
    if (resp := require_auth(c)) is not None:
        return resp
    with c.connect() as conn:
        rows = d.rows_to_dicts(conn.execute(
            "SELECT * FROM az_notifications WHERE user_id=? AND workspace_id=?"
            " AND archived=? ORDER BY created_at DESC LIMIT 100",
            (c.account_id, c.ws_id, archived)).fetchall())
        unread = conn.execute(
            "SELECT COUNT(*) AS n FROM az_notifications WHERE user_id=?"
            " AND workspace_id=? AND read=0 AND archived=0",
            (c.account_id, c.ws_id)).fetchone()["n"]
    return {"notifications": rows, "unread": unread}


@router.post("/inbox/{notification_id}/{action}")
def inbox_action(notification_id: int, action: str, c: Ctx = Depends(ctx)):
    if (resp := require_auth(c)) is not None:
        return resp
    if action not in ("read", "unread", "archive", "unarchive"):
        return err(400, "invalid", "Unknown action.")
    sets = {"read": "read=1", "unread": "read=0",
            "archive": "archived=1, read=1", "unarchive": "archived=0"}[action]
    with c.connect() as conn:
        n = conn.execute(
            f"UPDATE az_notifications SET {sets} WHERE notification_id=?"
            " AND user_id=?", (notification_id, c.account_id)).rowcount
    if not n:
        return err(404, "not-found", "Notification not found.")
    return {"ok": True}


# -------------------------------------------- portfolios / goals / activity

@router.get("/portfolios")
def portfolios(c: Ctx = Depends(ctx)):
    if (resp := require_auth(c)) is not None:
        return resp
    with c.connect() as conn:
        rows = d.rows_to_dicts(conn.execute(
            "SELECT p.*, (SELECT COUNT(*) FROM az_projects pr WHERE"
            " pr.portfolio_id=p.portfolio_id AND pr.deleted_at IS NULL)"
            " AS project_count FROM az_portfolios p WHERE p.workspace_id=?"
            " ORDER BY p.created_at", (c.ws_id,)).fetchall())
    return {"portfolios": rows}


@router.post("/portfolios")
async def create_portfolio(request: Request, c: Ctx = Depends(ctx)):
    if (resp := require_auth(c)) is not None:
        return resp
    body = await request.json()
    name = str(body.get("name", "")).strip()
    if not 1 <= len(name) <= 200:
        return err(400, "invalid", "Portfolio name is required.")
    pid = d.new_id("portfolio")
    with c.connect() as conn:
        conn.execute(
            "INSERT INTO az_portfolios(portfolio_id, workspace_id, name, color,"
            " owner_user_id, created_at) VALUES (?,?,?,?,?,?)",
            (pid, c.ws_id, name, str(body.get("color", "#796eff")),
             c.account_id, d.now()))
        d.record_activity(conn, workspace_id=c.ws_id, actor_user_id=c.account_id,
                          verb="created", object_type="portfolio",
                          object_id=pid, object_name=name)
    return {"ok": True, "portfolio_id": pid}


@router.get("/portfolios/{portfolio_id}")
def get_portfolio(portfolio_id: str, c: Ctx = Depends(ctx)):
    if (resp := require_auth(c)) is not None:
        return resp
    with c.connect() as conn:
        pf = conn.execute(
            "SELECT * FROM az_portfolios WHERE portfolio_id=? AND workspace_id=?",
            (portfolio_id, c.ws_id)).fetchone()
        if pf is None:
            return err(404, "not-found", "Portfolio not found.")
        projects = d.rows_to_dicts(conn.execute(
            "SELECT p.*, (SELECT COUNT(*) FROM az_tasks t WHERE t.project_id="
            "p.project_id AND t.deleted_at IS NULL) AS task_count,"
            " (SELECT COUNT(*) FROM az_tasks t WHERE t.project_id=p.project_id"
            " AND t.deleted_at IS NULL AND t.completed=1) AS done_count"
            " FROM az_projects p WHERE p.portfolio_id=? AND p.deleted_at IS NULL"
            " ORDER BY p.created_at", (portfolio_id,)).fetchall())
    return {"portfolio": d.row_to_dict(pf), "projects": projects}


@router.get("/goals")
def goals(c: Ctx = Depends(ctx)):
    if (resp := require_auth(c)) is not None:
        return resp
    with c.connect() as conn:
        rows = d.rows_to_dicts(conn.execute(
            "SELECT g.*, u.display_name AS owner_name, u.initials AS"
            " owner_initials, u.avatar_color AS owner_color FROM az_goals g"
            " JOIN az_users u ON u.user_id=g.owner_user_id WHERE g.workspace_id=?"
            " ORDER BY g.created_at", (c.ws_id,)).fetchall())
    return {"goals": rows}


@router.post("/goals")
async def create_goal(request: Request, c: Ctx = Depends(ctx)):
    if (resp := require_auth(c)) is not None:
        return resp
    body = await request.json()
    name = str(body.get("name", "")).strip()
    if not 1 <= len(name) <= 300:
        return err(400, "invalid", "Goal name is required.")
    gid = d.new_id("goal")
    with c.connect() as conn:
        conn.execute(
            "INSERT INTO az_goals(goal_id, workspace_id, name, owner_user_id,"
            " time_period, created_at) VALUES (?,?,?,?,?,?)",
            (gid, c.ws_id, name, c.account_id,
             str(body.get("time_period", "FY26")), d.now()))
    return {"ok": True, "goal_id": gid}


@router.patch("/goals/{goal_id}")
async def update_goal(goal_id: str, request: Request, c: Ctx = Depends(ctx)):
    if (resp := require_auth(c)) is not None:
        return resp
    body = await request.json()
    updates = {}
    if "progress" in body:
        progress = body["progress"]
        if not isinstance(progress, int) or not 0 <= progress <= 100:
            return err(400, "invalid", "Progress must be 0-100.")
        updates["progress"] = progress
    if "status" in body:
        if body["status"] not in ("on_track", "at_risk", "off_track", "achieved"):
            return err(400, "invalid", "Unknown goal status.")
        updates["status"] = body["status"]
    if "name" in body:
        name = str(body["name"]).strip()
        if not 1 <= len(name) <= 300:
            return err(400, "invalid", "Goal name is required.")
        updates["name"] = name
    if not updates:
        return err(400, "invalid", "Nothing to update.")
    with c.connect() as conn:
        n = conn.execute(
            f"UPDATE az_goals SET {', '.join(f'{k}=?' for k in updates)}"
            " WHERE goal_id=? AND workspace_id=?",
            (*updates.values(), goal_id, c.ws_id)).rowcount
    if not n:
        return err(404, "not-found", "Goal not found.")
    return {"ok": True}


@router.get("/activity")
def activity(c: Ctx = Depends(ctx)):
    if (resp := require_auth(c)) is not None:
        return resp
    with c.connect() as conn:
        rows = d.rows_to_dicts(conn.execute(
            "SELECT a.*, u.display_name, u.initials, u.avatar_color"
            " FROM az_activity a JOIN az_users u ON u.user_id=a.actor_user_id"
            " WHERE a.workspace_id=? ORDER BY a.created_at DESC LIMIT 100",
            (c.ws_id,)).fetchall())
    return {"activity": rows}


# ------------------------------------------------------ rules / templates

@router.get("/templates")
def templates(c: Ctx = Depends(ctx)):
    return {"templates": [{k: t[k] for k in ("id", "name", "sections")}
                          for t in PROJECT_TEMPLATES]}


@router.post("/projects/{project_id}/rules")
async def create_rule(project_id: str, request: Request, c: Ctx = Depends(ctx)):
    if (resp := require_auth(c)) is not None:
        return resp
    body = await request.json()
    name = str(body.get("name", "")).strip()
    trigger = body.get("trigger")
    action = body.get("action")
    if not name:
        return err(400, "invalid", "Rule name is required.")
    if trigger not in ("task_completed", "task_added", "due_date_set"):
        return err(400, "invalid", "Unknown trigger.")
    if not isinstance(action, str) or not action:
        return err(400, "invalid", "Rule action is required.")
    with c.connect() as conn:
        if _project_or_none(conn, c, project_id) is None:
            return err(404, "not-found", "Project not found.")
        rid = d.new_id("rule")
        conn.execute(
            "INSERT INTO az_rules(rule_id, project_id, name, trigger, action,"
            " created_at) VALUES (?,?,?,?,?,?)",
            (rid, project_id, name, trigger, action, d.now()))
    return {"ok": True, "rule_id": rid}


@router.patch("/rules/{rule_id}")
async def toggle_rule(rule_id: str, request: Request, c: Ctx = Depends(ctx)):
    if (resp := require_auth(c)) is not None:
        return resp
    body = await request.json()
    enabled = 1 if body.get("enabled") else 0
    with c.connect() as conn:
        n = conn.execute(
            "UPDATE az_rules SET enabled=? WHERE rule_id=? AND rule_id IN"
            " (SELECT r.rule_id FROM az_rules r JOIN az_projects p"
            "  ON p.project_id=r.project_id WHERE p.workspace_id=?)",
            (enabled, rule_id, c.ws_id)).rowcount
    if not n:
        return err(404, "not-found", "Rule not found.")
    return {"ok": True}


# ------------------------------------------------------ import / export

@router.post("/projects/{project_id}/import")
async def import_csv(project_id: str, file: UploadFile, c: Ctx = Depends(ctx)):
    if (resp := require_auth(c)) is not None:
        return resp
    raw = await file.read()
    if len(raw) > 1024 * 1024:
        return err(413, "too-large", "CSV imports are limited to 1 MB.")
    try:
        text = raw.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames or "Name" not in reader.fieldnames:
            return err(400, "invalid",
                       "The CSV needs a header row with at least a Name column.")
        rows = list(reader)
    except (UnicodeDecodeError, csv.Error):
        return err(400, "invalid", "That file could not be parsed as CSV.")
    if not rows:
        return err(400, "invalid", "The CSV contains no data rows.")
    imported = 0
    with c.connect() as conn:
        if _project_or_none(conn, c, project_id) is None:
            return err(404, "not-found", "Project not found.")
        first = conn.execute(
            "SELECT section_id FROM az_sections WHERE project_id=?"
            " ORDER BY sort_order LIMIT 1", (project_id,)).fetchone()
        section_id = first["section_id"] if first else None
        for i, row in enumerate(rows[:500]):
            name = (row.get("Name") or "").strip()
            if not name:
                continue
            conn.execute(
                "INSERT INTO az_tasks(task_id, workspace_id, project_id,"
                " section_id, name, notes, due_date, creator_user_id,"
                " sort_order, created_at, modified_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (d.new_id("task"), c.ws_id, project_id, section_id, name,
                 (row.get("Notes") or "").strip(),
                 ((row.get("Due Date") or "").strip()
                  if valid_date((row.get("Due Date") or "").strip() or None)
                  else None) or None,
                 c.account_id, 1000 + i, d.now(), d.now()))
            imported += 1
        d.record_activity(conn, workspace_id=c.ws_id, actor_user_id=c.account_id,
                          verb="imported", object_type="project",
                          object_id=project_id, detail=f"{imported} tasks from CSV")
    return {"ok": True, "imported": imported, "skipped": len(rows) - imported}


@router.get("/projects/{project_id}/export.csv")
def export_csv(project_id: str, c: Ctx = Depends(ctx)):
    if (resp := require_auth(c)) is not None:
        return resp
    with c.connect() as conn:
        project = _project_or_none(conn, c, project_id)
        if project is None:
            return err(404, "not-found", "Project not found.")
        tasks = d.rows_to_dicts(conn.execute(
            "SELECT t.name, t.notes, t.due_date, t.priority, t.completed,"
            " s.name AS section, u.display_name AS assignee FROM az_tasks t"
            " LEFT JOIN az_sections s ON s.section_id=t.section_id"
            " LEFT JOIN az_users u ON u.user_id=t.assignee_user_id"
            " WHERE t.project_id=? AND t.deleted_at IS NULL"
            " ORDER BY s.sort_order, t.sort_order", (project_id,)).fetchall())
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["Name", "Section", "Assignee", "Due Date", "Priority",
                     "Notes", "Completed"])
    for t in tasks:
        writer.writerow([t["name"], t["section"] or "", t["assignee"] or "",
                         t["due_date"] or "", t["priority"] or "",
                         t["notes"], "Yes" if t["completed"] else "No"])
    return StreamingResponse(
        iter([out.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition":
                 f'attachment; filename="{project["name"]}.csv"'})


# --------------------------------------------------------------- trash

@router.get("/trash")
def trash(c: Ctx = Depends(ctx)):
    if (resp := require_auth(c)) is not None:
        return resp
    with c.connect() as conn:
        tasks = d.rows_to_dicts(conn.execute(
            "SELECT task_id, name, deleted_at FROM az_tasks WHERE workspace_id=?"
            " AND deleted_at IS NOT NULL ORDER BY deleted_at DESC",
            (c.ws_id,)).fetchall())
        projects = d.rows_to_dicts(conn.execute(
            "SELECT project_id, name, deleted_at FROM az_projects"
            " WHERE workspace_id=? AND deleted_at IS NOT NULL"
            " ORDER BY deleted_at DESC", (c.ws_id,)).fetchall())
    return {"tasks": tasks, "projects": projects}


@router.post("/trash/restore")
async def restore(request: Request, c: Ctx = Depends(ctx)):
    if (resp := require_auth(c)) is not None:
        return resp
    body = await request.json()
    with c.connect() as conn:
        if body.get("task_id"):
            n = conn.execute(
                "UPDATE az_tasks SET deleted_at=NULL WHERE task_id=?"
                " AND workspace_id=?", (body["task_id"], c.ws_id)).rowcount
        elif body.get("project_id"):
            n = conn.execute(
                "UPDATE az_projects SET deleted_at=NULL WHERE project_id=?"
                " AND workspace_id=?", (body["project_id"], c.ws_id)).rowcount
        else:
            return err(400, "invalid", "Provide task_id or project_id.")
    if not n:
        return err(404, "not-found", "Item not found in trash.")
    return {"ok": True}


@router.post("/trash/purge")
async def purge(request: Request, c: Ctx = Depends(ctx)):
    if (resp := require_auth(c)) is not None:
        return resp
    body = await request.json()
    with c.connect() as conn:
        if body.get("task_id"):
            n = conn.execute(
                "DELETE FROM az_tasks WHERE task_id=? AND workspace_id=?"
                " AND deleted_at IS NOT NULL", (body["task_id"], c.ws_id)).rowcount
        elif body.get("project_id"):
            pid = body["project_id"]
            n = conn.execute(
                "DELETE FROM az_projects WHERE project_id=? AND workspace_id=?"
                " AND deleted_at IS NOT NULL", (pid, c.ws_id)).rowcount
            if n:
                conn.execute("DELETE FROM az_tasks WHERE project_id=?", (pid,))
                conn.execute("DELETE FROM az_sections WHERE project_id=?", (pid,))
        else:
            return err(400, "invalid", "Provide task_id or project_id.")
    if not n:
        return err(404, "not-found", "Item not found in trash.")
    return {"ok": True}


# --------------------------------------------- profile / settings / billing

@router.patch("/profile")
async def update_profile(request: Request, c: Ctx = Depends(ctx)):
    if (resp := require_auth(c)) is not None:
        return resp
    body = await request.json()
    allowed = {"display_name", "role_title", "about_me", "avatar_color",
               "task_default_view", "theme", "notify_mentions", "notify_status",
               "notify_daily_summary"}
    updates = {k: v for k, v in body.items() if k in allowed}
    if "display_name" in updates:
        name = str(updates["display_name"]).strip()
        if not 1 <= len(name) <= 120:
            return err(400, "invalid", "Name is required.")
        updates["display_name"] = name
    if "task_default_view" in updates and updates["task_default_view"] not in (
            "list", "board", "calendar"):
        return err(400, "invalid", "Unknown default view.")
    if "theme" in updates and updates["theme"] not in ("light", "dark", "system"):
        return err(400, "invalid", "Unknown theme.")
    if not updates:
        return err(400, "invalid", "Nothing to update.")
    with c.connect() as conn:
        sets = ", ".join(f"{k}=?" for k in updates)
        conn.execute(f"UPDATE az_users SET {sets} WHERE user_id=?",
                     (*updates.values(), c.account_id))
        if "display_name" in updates:
            initials = "".join(w[0] for w in updates["display_name"].split()[:2]).upper()
            conn.execute("UPDATE az_users SET initials=? WHERE user_id=?",
                         (initials, c.account_id))
    return {"ok": True}


@router.get("/security/sessions")
def security_sessions(c: Ctx = Depends(ctx)):
    if (resp := require_auth(c)) is not None:
        return resp
    with c.connect() as conn:
        rows = conn.execute(
            "SELECT created_at, expires_at, revoked_at"
            " FROM local_auth_sessions WHERE account_id=?"
            " ORDER BY created_at DESC LIMIT 20", (c.account_id,)).fetchall()
        sessions = [{"created_at": r["created_at"],
                     "last_seen_at": r["created_at"],
                     "active": r["revoked_at"] is None} for r in rows]
    return {"sessions": sessions}


@router.post("/security/logout-others")
def logout_others(c: Ctx = Depends(ctx)):
    if (resp := require_auth(c)) is not None:
        return resp
    digest = c.auth.session_owner_digest(c.token)
    with c.connect() as conn:
        n = conn.execute(
            "UPDATE local_auth_sessions SET revoked_at=? WHERE account_id=?"
            " AND session_digest<>? AND revoked_at IS NULL",
            (d.now(), c.account_id, digest)).rowcount
    return {"ok": True, "revoked": n}


@router.get("/billing")
def billing(c: Ctx = Depends(ctx)):
    if (resp := require_auth(c)) is not None:
        return resp
    return {"plan": c.workspace["plan"], "plans": PLANS,
            "payment_adapter": "local-sandbox",
            "scenarios": [
                {"id": "sandbox-approved", "label": "Simulated approval"},
                {"id": "sandbox-declined", "label": "Simulated decline"},
                {"id": "sandbox-retry", "label": "Simulated retry"}]}


@router.post("/billing/upgrade")
async def upgrade(request: Request, c: Ctx = Depends(ctx)):
    if (resp := require_auth(c)) is not None:
        return resp
    body = await request.json()
    plan = body.get("plan")
    scenario = body.get("scenario", "sandbox-approved")
    if plan not in PLANS or plan == "personal":
        return err(400, "invalid", "Choose a paid plan.")
    with c.connect() as conn:
        if c.role(conn) != "admin":
            return err(403, "forbidden", "Only admins can change the plan.")
    amount = PLANS[plan]["monthly_minor"]
    owner = f"asana-billing:{c.account_id}"
    fingerprint = hashlib.sha256(f"{owner}:{plan}".encode()).hexdigest()
    try:
        intent = c.backend.payments.create_intent(
            owner=owner, amount_minor=amount, currency="USD",
            fingerprint=fingerprint,
            idempotency_key=f"intent-{uuid.uuid4().hex}")
        attempt = c.backend.payments.attempt(
            flow_id=intent["flow_id"], owner=owner, amount_minor=amount,
            currency="USD", fingerprint=fingerprint, scenario_id=scenario,
            idempotency_key=f"attempt-{uuid.uuid4().hex}")
    except PaymentRejected as e:
        return JSONResponse({"ok": False, "outcome": "declined",
                             "message": str(e)}, status_code=402)
    except PaymentError as e:
        return err(400, "payment-invalid", str(e))
    outcome = str(attempt.get("status") or attempt.get("outcome") or "").upper()
    if outcome != "APPROVED":
        return JSONResponse({"ok": False, "outcome": outcome,
                             "message": "The simulated payment did not complete."
                             + (" You can retry." if outcome == "RETRYABLE" else "")},
                            status_code=402)
    with c.backend.lifecycle.connection(transaction=True) as pconn:
        c.backend.payments.consume_approval(
            pconn, flow_id=intent["flow_id"], owner=owner, amount_minor=amount,
            currency="USD", fingerprint=fingerprint)
    with c.connect() as conn:
        conn.execute("UPDATE az_workspaces SET plan=? WHERE workspace_id=?",
                     (plan, c.ws_id))
        d.record_activity(conn, workspace_id=c.ws_id, actor_user_id=c.account_id,
                          verb="upgraded", object_type="workspace",
                          object_id=c.ws_id, detail=f"plan={plan} (local sandbox)")
    return {"ok": True, "outcome": "approved", "plan": plan}


@router.get("/export/workspace.json")
def export_workspace(c: Ctx = Depends(ctx)):
    if (resp := require_auth(c)) is not None:
        return resp
    with c.connect() as conn:
        payload = {
            "workspace": c.workspace,
            "projects": d.rows_to_dicts(conn.execute(
                "SELECT * FROM az_projects WHERE workspace_id=?",
                (c.ws_id,)).fetchall()),
            "tasks": d.rows_to_dicts(conn.execute(
                "SELECT task_id, project_id, section_id, parent_task_id, name,"
                " notes, assignee_user_id, due_date, priority, completed"
                " FROM az_tasks WHERE workspace_id=?", (c.ws_id,)).fetchall()),
            "goals": d.rows_to_dicts(conn.execute(
                "SELECT * FROM az_goals WHERE workspace_id=?",
                (c.ws_id,)).fetchall()),
        }
    return JSONResponse(payload, headers={
        "Content-Disposition": 'attachment; filename="workspace-export.json"'})
