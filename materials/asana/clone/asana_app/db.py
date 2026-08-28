"""Business schema for the Asana offline clone.

All state lives in the site-bound SQLite database opened through the generated
``websitebench.site_backend`` seam. The auth tables belong to LocalAuthStore;
these tables model the workspace/project/task domain. Data here is entirely
synthetic — no source-site records are ever imported.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from typing import Any

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS az_users (
    user_id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    initials TEXT NOT NULL,
    avatar_color TEXT NOT NULL DEFAULT '#f06a6a',
    role_title TEXT NOT NULL DEFAULT '',
    about_me TEXT NOT NULL DEFAULT '',
    synthetic INTEGER NOT NULL DEFAULT 0,
    task_default_view TEXT NOT NULL DEFAULT 'list',
    theme TEXT NOT NULL DEFAULT 'light',
    notify_mentions INTEGER NOT NULL DEFAULT 1,
    notify_status INTEGER NOT NULL DEFAULT 1,
    notify_daily_summary INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS az_workspaces (
    workspace_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    plan TEXT NOT NULL DEFAULT 'personal',
    owner_user_id TEXT NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS az_workspace_members (
    workspace_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'member',
    joined_at INTEGER NOT NULL,
    PRIMARY KEY (workspace_id, user_id)
);
CREATE TABLE IF NOT EXISTS az_portfolios (
    portfolio_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    name TEXT NOT NULL,
    color TEXT NOT NULL DEFAULT '#796eff',
    owner_user_id TEXT NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS az_projects (
    project_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    portfolio_id TEXT,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    color TEXT NOT NULL DEFAULT '#4573d2',
    icon TEXT NOT NULL DEFAULT 'list',
    status TEXT NOT NULL DEFAULT 'on_track',
    status_note TEXT NOT NULL DEFAULT '',
    default_view TEXT NOT NULL DEFAULT 'list',
    owner_user_id TEXT NOT NULL,
    archived INTEGER NOT NULL DEFAULT 0,
    deleted_at INTEGER,
    starred INTEGER NOT NULL DEFAULT 0,
    share_mode TEXT NOT NULL DEFAULT 'workspace',
    created_from_template TEXT,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS az_sections (
    section_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    name TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS az_tasks (
    task_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    project_id TEXT,
    section_id TEXT,
    parent_task_id TEXT,
    name TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    assignee_user_id TEXT,
    creator_user_id TEXT NOT NULL,
    due_date TEXT,
    start_date TEXT,
    priority TEXT,
    task_status TEXT,
    completed INTEGER NOT NULL DEFAULT 0,
    completed_at INTEGER,
    liked_by TEXT NOT NULL DEFAULT '[]',
    sort_order INTEGER NOT NULL DEFAULT 0,
    deleted_at INTEGER,
    created_at INTEGER NOT NULL,
    modified_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS az_task_dependencies (
    task_id TEXT NOT NULL,
    depends_on_task_id TEXT NOT NULL,
    PRIMARY KEY (task_id, depends_on_task_id)
);
CREATE TABLE IF NOT EXISTS az_task_collaborators (
    task_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    PRIMARY KEY (task_id, user_id)
);
CREATE TABLE IF NOT EXISTS az_comments (
    comment_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    author_user_id TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    edited_at INTEGER
);
CREATE TABLE IF NOT EXISTS az_attachments (
    attachment_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    filename TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    content_type TEXT NOT NULL,
    data BLOB NOT NULL,
    uploader_user_id TEXT NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS az_activity (
    activity_id INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id TEXT NOT NULL,
    actor_user_id TEXT NOT NULL,
    verb TEXT NOT NULL,
    object_type TEXT NOT NULL,
    object_id TEXT NOT NULL,
    object_name TEXT NOT NULL DEFAULT '',
    detail TEXT NOT NULL DEFAULT '',
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS az_notifications (
    notification_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    text TEXT NOT NULL,
    task_id TEXT,
    read INTEGER NOT NULL DEFAULT 0,
    archived INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS az_goals (
    goal_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    name TEXT NOT NULL,
    owner_user_id TEXT NOT NULL,
    time_period TEXT NOT NULL DEFAULT 'FY26',
    progress INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'on_track',
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS az_saved_views (
    view_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    name TEXT NOT NULL,
    query_json TEXT NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS az_project_memberships (
    project_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    access TEXT NOT NULL DEFAULT 'editor',
    PRIMARY KEY (project_id, user_id)
);
CREATE TABLE IF NOT EXISTS az_rules (
    rule_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    name TEXT NOT NULL,
    trigger TEXT NOT NULL,
    action TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS az_invites (
    invite_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    email TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'member',
    invited_by TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_az_tasks_project ON az_tasks(project_id, section_id, sort_order);
CREATE INDEX IF NOT EXISTS idx_az_tasks_assignee ON az_tasks(assignee_user_id);
CREATE INDEX IF NOT EXISTS idx_az_activity_ws ON az_activity(workspace_id, created_at);
"""


def now() -> int:
    return int(time.time())


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def ensure_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA_SQL)


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return None if row is None else {k: row[k] for k in row.keys()}


def rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [{k: r[k] for k in r.keys()} for r in rows]


def record_activity(
    connection: sqlite3.Connection,
    *,
    workspace_id: str,
    actor_user_id: str,
    verb: str,
    object_type: str,
    object_id: str,
    object_name: str = "",
    detail: str = "",
) -> None:
    connection.execute(
        "INSERT INTO az_activity(workspace_id, actor_user_id, verb, object_type,"
        " object_id, object_name, detail, created_at) VALUES (?,?,?,?,?,?,?,?)",
        (workspace_id, actor_user_id, verb, object_type, object_id, object_name,
         detail, now()),
    )


def notify(
    connection: sqlite3.Connection,
    *,
    user_id: str,
    workspace_id: str,
    kind: str,
    text: str,
    task_id: str | None = None,
) -> None:
    connection.execute(
        "INSERT INTO az_notifications(user_id, workspace_id, kind, text, task_id,"
        " created_at) VALUES (?,?,?,?,?,?)",
        (user_id, workspace_id, kind, text, task_id, now()),
    )


def liked_by(value: str) -> list[str]:
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return []
    return parsed if isinstance(parsed, list) else []
