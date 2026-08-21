from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

SITE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SITE_ROOT / "clone"))

from app import app  # noqa: E402


COURSE = "/learn/neural-networks-deep-learning"
MODULE = f"{COURSE}/home/module/1"
LESSON = f"{COURSE}/lecture/Cuf2f/welcome"


def _login(client: TestClient) -> None:
    response = client.post(
        "/auth/login",
        data={
            "email": "progress@coursera.test",
            "password": "Progress-Learner-33",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303


def test_weekly_target_is_owner_scoped_and_persists_on_course_home() -> None:
    with TestClient(app, base_url="https://33.offline.invalid") as client:
        _login(client)
        saved = client.post(
            f"{COURSE}/weekly-target",
            data={"minutes": "90"},
            follow_redirects=False,
        )
        assert saved.status_code == 303
        page = client.get(MODULE)

    assert 'name="minutes"' in page.text
    assert 'value="90"' in page.text
    assert "90 minutes per week" in page.text


def test_lesson_reaction_and_issue_report_persist_for_enrolled_owner() -> None:
    with TestClient(app, base_url="https://33.offline.invalid") as client:
        _login(client)
        reaction = client.post(
            f"{LESSON}/reaction",
            data={"reaction": "like"},
            follow_redirects=False,
        )
        report = client.post(
            f"{LESSON}/report",
            data={"reason": "Transcript timing is unclear"},
            follow_redirects=False,
        )
        lesson = client.get(LESSON)

    assert reaction.status_code == 303
    assert report.status_code == 303
    assert 'name="reaction" value="like" aria-pressed="true"' in lesson.text
    assert "Issue recorded locally" in lesson.text


def test_course_disclosures_and_notes_filter_have_observable_local_actions() -> None:
    with TestClient(app, base_url="https://33.offline.invalid") as client:
        _login(client)
        module = client.get(MODULE)
        lesson = client.get(LESSON)
        notes = client.get(f"{COURSE}/home/notes")

    assert 'data-control-action="toggle-objectives"' in module.text
    assert 'aria-controls="learning-objectives"' in module.text
    assert 'id="learning-objectives"' in module.text
    assert 'data-control-action="toggle-player"' in lesson.text
    assert 'data-control-action="switch-lesson-tab"' in lesson.text
    assert f'action="{COURSE}/home/notes"' in notes.text


def test_my_learning_more_options_exposes_real_management_destinations() -> None:
    with TestClient(app, base_url="https://33.offline.invalid") as client:
        _login(client)
        dashboard = client.get("/my-learning")

    assert '<details class="program-options">' in dashboard.text
    assert "More options" in dashboard.text
    assert 'href="/account/history"' in dashboard.text
    assert 'href="/orders"' in dashboard.text
