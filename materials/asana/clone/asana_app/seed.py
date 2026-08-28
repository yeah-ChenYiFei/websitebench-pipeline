"""Deterministic synthetic demo data for the Asana offline clone.

Every record is synthetic; nothing here is captured from the source site.
Seeding is idempotent per workspace: it runs once when a new account's
workspace is created.
"""

from __future__ import annotations

import datetime as dt
import sqlite3

from .db import new_id, now, record_activity

SYNTHETIC_TEAMMATES = [
    ("Mia Chen", "mia.chen@demo.asana.offline.invalid", "MC", "#aa62e3", "Product Manager"),
    ("Leo Park", "leo.park@demo.asana.offline.invalid", "LP", "#4573d2", "Design Lead"),
    ("Ana Souza", "ana.souza@demo.asana.offline.invalid", "AS", "#f1bd6c", "Engineer"),
    ("Sam Rivera", "sam.rivera@demo.asana.offline.invalid", "SR", "#5da283", "Marketing"),
]


def _date(offset_days: int) -> str:
    return (dt.date.today() + dt.timedelta(days=offset_days)).isoformat()


def ensure_synthetic_users(connection: sqlite3.Connection) -> list[str]:
    ids = []
    for name, email, initials, color, title in SYNTHETIC_TEAMMATES:
        row = connection.execute(
            "SELECT user_id FROM az_users WHERE email=?", (email,)
        ).fetchone()
        if row:
            ids.append(row["user_id"])
            continue
        uid = new_id("user")
        connection.execute(
            "INSERT INTO az_users(user_id, email, display_name, initials,"
            " avatar_color, role_title, synthetic, created_at)"
            " VALUES (?,?,?,?,?,?,1,?)",
            (uid, email, name, initials, color, title, now()),
        )
        ids.append(uid)
    return ids


def seed_workspace(
    connection: sqlite3.Connection,
    *,
    workspace_id: str,
    owner_user_id: str,
) -> None:
    """Populate a fresh workspace with a synthetic demo state."""

    teammates = ensure_synthetic_users(connection)
    for uid in teammates:
        connection.execute(
            "INSERT OR IGNORE INTO az_workspace_members(workspace_id, user_id,"
            " role, joined_at) VALUES (?,?,'member',?)",
            (workspace_id, uid, now()),
        )

    portfolio_id = new_id("portfolio")
    connection.execute(
        "INSERT INTO az_portfolios(portfolio_id, workspace_id, name, color,"
        " owner_user_id, created_at) VALUES (?,?,?,?,?,?)",
        (portfolio_id, workspace_id, "Research Projects 2026", "#796eff",
         owner_user_id, now()),
    )

    projects = [
        ("Product launch plan", "#4573d2", "rocket",
         "Cross-functional launch plan for the spring release.", portfolio_id),
        ("Website redesign", "#f06a6a", "palette",
         "Refresh the marketing site with the new brand system.", portfolio_id),
        ("User research study", "#5da283", "chat",
         "Interview program and synthesis for Q3 discovery.", portfolio_id),
    ]
    section_names = ["To do", "In progress", "Done"]
    all_users = [owner_user_id] + teammates

    demo_tasks = {
        "Product launch plan": [
            ("Draft launch brief", 0, 0, -2, "High", "On track", 1,
             "Summarize goals, audience, and success metrics for the launch."),
            ("Align stakeholders on messaging", 0, 1, 1, "Medium", "On track", 0,
             "Collect feedback from product marketing and sales."),
            ("Build launch timeline", 1, 2, 3, "High", "At risk", 0,
             "Sequence beta, announcement, and rollout milestones."),
            ("Prepare press kit", 1, 3, 7, "Low", None, 0,
             "Screenshots, boilerplate, and spokesperson quotes."),
            ("QA release candidate", 2, 4, -1, "High", "Off track", 1,
             "Full regression pass on the release branch."),
        ],
        "Website redesign": [
            ("Audit current pages", 0, 0, -5, "Medium", None, 1,
             "Inventory templates and traffic to prioritize the rebuild."),
            ("Design new homepage hero", 1, 1, 2, "High", "On track", 0,
             "Explore three hero concepts with the new brand palette."),
            ("Migrate pricing page", 1, 2, 5, "Medium", "On track", 0,
             "Port pricing tiers to the new component library."),
            ("Accessibility review", 0, 3, 9, "High", None, 0,
             "WCAG 2.2 AA sweep across the redesigned templates."),
        ],
        "User research study": [
            ("Recruit 10 participants", 0, 0, -3, "High", "On track", 1,
             "Screen for teams of 5-50 using work management tools."),
            ("Write interview guide", 0, 1, 0, "Medium", None, 1,
             "Focus on planning rituals and tool-switching pain."),
            ("Run interview sessions", 1, 2, 4, "High", "On track", 0,
             "Five 45-minute remote sessions per week."),
            ("Synthesize findings", 2, 3, 12, "Medium", None, 0,
             "Affinity-map notes and draft opportunity areas."),
        ],
    }

    project_ids: dict[str, str] = {}
    first_task_ids: dict[str, list[str]] = {}
    for pi, (pname, color, icon, desc, pf) in enumerate(projects):
        project_id = new_id("project")
        project_ids[pname] = project_id
        connection.execute(
            "INSERT INTO az_projects(project_id, workspace_id, portfolio_id,"
            " name, description, color, icon, owner_user_id, starred, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (project_id, workspace_id, pf, pname, desc, color, icon,
             owner_user_id, 1 if pi == 0 else 0, now()),
        )
        connection.execute(
            "INSERT INTO az_project_memberships(project_id, user_id, access)"
            " VALUES (?,?,'admin')", (project_id, owner_user_id),
        )
        section_ids = []
        for si, sname in enumerate(section_names):
            sid = new_id("section")
            section_ids.append(sid)
            connection.execute(
                "INSERT INTO az_sections(section_id, project_id, name, sort_order)"
                " VALUES (?,?,?,?)", (sid, project_id, sname, si),
            )
        task_ids = []
        for ti, (tname, sec, assignee_i, due_off, priority, status, done, notes) in \
                enumerate(demo_tasks[pname]):
            task_id = new_id("task")
            task_ids.append(task_id)
            section_id = section_ids[2] if done else section_ids[sec]
            connection.execute(
                "INSERT INTO az_tasks(task_id, workspace_id, project_id,"
                " section_id, name, notes, assignee_user_id, creator_user_id,"
                " due_date, priority, task_status, completed, completed_at,"
                " sort_order, created_at, modified_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (task_id, workspace_id, project_id, section_id, tname, notes,
                 all_users[assignee_i % len(all_users)], owner_user_id,
                 _date(due_off), priority, status, done,
                 now() - 86400 if done else None, ti, now() - 86400 * 3, now()),
            )
        first_task_ids[pname] = task_ids

    # Subtasks and a dependency chain on the launch plan.
    launch = first_task_ids["Product launch plan"]
    for sub_i, sub in enumerate(["Collect metric baselines", "Review with leadership"]):
        connection.execute(
            "INSERT INTO az_tasks(task_id, workspace_id, project_id, section_id,"
            " parent_task_id, name, creator_user_id, assignee_user_id, due_date,"
            " sort_order, created_at, modified_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (new_id("task"), workspace_id, project_ids["Product launch plan"],
             None, launch[0], sub, owner_user_id,
             all_users[sub_i % len(all_users)], _date(2 + sub_i), sub_i,
             now(), now()),
        )
    connection.execute(
        "INSERT OR IGNORE INTO az_task_dependencies(task_id, depends_on_task_id)"
        " VALUES (?,?)", (launch[2], launch[1]),
    )
    connection.execute(
        "INSERT OR IGNORE INTO az_task_dependencies(task_id, depends_on_task_id)"
        " VALUES (?,?)", (launch[3], launch[2]),
    )

    # Synthetic conversation on the first launch task.
    for author, body, age in [
        (teammates[0], "I drafted the first outline — feedback welcome.", 7200),
        (teammates[1], "Looks solid. Can we add the beta cohort size?", 3600),
    ]:
        connection.execute(
            "INSERT INTO az_comments(comment_id, task_id, author_user_id, body,"
            " created_at) VALUES (?,?,?,?,?)",
            (new_id("comment"), launch[0], author, body, now() - age),
        )
    connection.execute(
        "INSERT OR IGNORE INTO az_task_collaborators(task_id, user_id)"
        " VALUES (?,?)", (launch[0], teammates[0]),
    )

    # Goals, a sample automation rule, one pending invite.
    for gname, progress, status in [
        ("Ship spring release on time", 45, "on_track"),
        ("Grow research participant panel to 100", 20, "at_risk"),
    ]:
        connection.execute(
            "INSERT INTO az_goals(goal_id, workspace_id, name, owner_user_id,"
            " time_period, progress, status, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (new_id("goal"), workspace_id, gname, owner_user_id, "FY26",
             progress, status, now()),
        )
    connection.execute(
        "INSERT INTO az_rules(rule_id, project_id, name, trigger, action,"
        " created_at) VALUES (?,?,?,?,?,?)",
        (new_id("rule"), project_ids["Product launch plan"],
         "Move completed tasks to Done", "task_completed",
         "move_to_section:Done", now()),
    )

    record_activity(
        connection, workspace_id=workspace_id, actor_user_id=owner_user_id,
        verb="seeded", object_type="workspace", object_id=workspace_id,
        object_name="Demo workspace", detail="Synthetic demo data created",
    )
