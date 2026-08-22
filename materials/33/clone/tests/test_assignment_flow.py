from __future__ import annotations

import re
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient

from app import app
from backend import learning_db


COURSE = "/learn/neural-networks-deep-learning"
ASSIGNMENT = f"{COURSE}/assignment-submission/3KFZW/introduction-to-deep-learning"
CORRECT_PAIRS = [
    ("q_1", "0"),
    ("q_2", "0"),
    ("q_2", "1"),
    ("q_3", "2"),
    ("q_3", "3"),
    ("q_4", "1"),
    ("q_5", "2"),
    ("q_6", "0"),
    ("q_7", "1"),
    ("q_8", "0"),
    ("q_8", "2"),
    ("q_9", "0"),
    ("q_10", "2"),
    ("q_10", "3"),
]


@pytest.fixture
def site_client(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "WEBSITEBENCH_SITE_BACKEND_DATABASE", str(tmp_path / "33.sqlite3")
    )
    learning_db.close_services()
    with TestClient(app, base_url="https://33.offline.invalid") as client:
        yield client
    learning_db.close_services()


def _login_enrolled(client: TestClient) -> None:
    response = client.post(
        "/auth/learning-demo", data={"next": "/my-learning"}, follow_redirects=False
    )
    assert response.status_code == 303


def _login_empty(client: TestClient) -> None:
    response = client.post(
        "/auth/local-learner", data={"next": "/my-learning"}, follow_redirects=False
    )
    assert response.status_code == 303


def _post_pairs(client: TestClient, path: str, pairs: list[tuple[str, str]]):
    return client.post(
        path,
        content=urlencode(pairs),
        headers={"content-type": "application/x-www-form-urlencoded"},
        follow_redirects=False,
    )


def test_my_learning_uses_source_tabs_and_five_course_program(site_client) -> None:
    _login_enrolled(site_client)
    in_progress = site_client.get("/my-learning?myLearningTab=IN_PROGRESS")
    completed = site_client.get("/my-learning?myLearningTab=COMPLETED")
    certificates = site_client.get("/my-learning?myLearningTab=CERTIFICATES")

    assert in_progress.status_code == 200
    assert 'data-authenticated-surface="my-learning-enrolled"' in in_progress.text
    assert "Deep Learning" in in_progress.text
    for title in (
        "Neural Networks and Deep Learning",
        "Improving Deep Neural Networks: Hyperparameter Tuning, Regularization and Optimization",
        "Structuring Machine Learning Projects",
        "Convolutional Neural Networks",
        "Sequence Models",
    ):
        assert title in in_progress.text
    assert "Get started" in in_progress.text
    assert "Completion date unlocked on Day 3" in in_progress.text
    assert "Your first completion is waiting" in completed.text
    assert "Your first certificate is waiting!" in certificates.text
    assert "Verify My ID" in certificates.text


def test_enrolled_course_read_routes_render_observed_shell_and_content(site_client) -> None:
    _login_enrolled(site_client)
    welcome = site_client.get(f"{COURSE}/home/welcome", follow_redirects=False)
    assert welcome.status_code == 303
    assert welcome.headers["location"] == f"{COURSE}/home/module/1"

    expected = {
        f"{COURSE}/home/module/1": (
            "Introduction to Deep Learning",
            "Welcome to the Deep Learning Specialization",
            "Weekly learning target",
            "Course timeline",
        ),
        f"{COURSE}/lecture/Cuf2f/welcome": (
            "Welcome",
            "Transcript",
            "Notes",
            "Files",
            "Save note",
            "Go to next item",
        ),
        f"{COURSE}/home/assignments": (
            "Grades",
            "Item",
            "Status",
            "Due",
            "Weight",
            "Grade",
        ),
        f"{COURSE}/home/notes": ("Notes", "You have no notes", "All notes"),
        f"{COURSE}/course-inbox": ("Messages", "There are no messages yet."),
        f"{COURSE}/home/info": (
            "About this Course",
            "Syllabus",
            "How It Works",
            "Course 1 of Specialization",
            "Related Courses",
        ),
        f"{COURSE}/resources/course-notation-sheet": ("Course Notation Sheet",),
        f"{COURSE}/resources/course-acknowledgments": ("Course Acknowledgments",),
        ASSIGNMENT: (
            "Introduction to Deep Learning",
            "What to expect",
            "Coursera Honor Code",
            "Start assignment",
            "50 minutes",
        ),
    }
    for path, snippets in expected.items():
        response = site_client.get(path)
        assert response.status_code == 200, path
        for snippet in snippets:
            assert snippet in response.text, (path, snippet)
        if path.startswith(COURSE):
            for navigation in (
                "Week 1",
                "Week 2",
                "Week 3",
                "Week 4",
                "Grades",
                "Notes",
                "Messages",
                "Resources",
                "Course Info",
            ):
                assert navigation in response.text, (path, navigation)


def test_signed_out_and_unenrolled_course_access_are_non_disclosing(site_client) -> None:
    target = f"{COURSE}/home/module/1"
    signed_out = site_client.get(target)
    assert signed_out.status_code == 401
    assert "Sign in" in signed_out.text
    assert f"/login?next={target}" in signed_out.text

    _login_empty(site_client)
    unenrolled = site_client.get(target)
    assert unenrolled.status_code == 403
    assert "Active enrollment required" in unenrolled.text
    forged = site_client.get(f"{COURSE}/resources/not-a-resource")
    assert forged.status_code == 404
    assert "Learning item not found" in forged.text


def test_honor_code_start_draft_reload_submit_result_and_grades(site_client) -> None:
    _login_enrolled(site_client)
    missing_honor = site_client.post(f"{ASSIGNMENT}/start", follow_redirects=False)
    assert missing_honor.status_code == 422
    assert "Honor Code" in missing_honor.text

    started = site_client.post(
        f"{ASSIGNMENT}/start",
        data={"honor_code": "accepted"},
        follow_redirects=False,
    )
    assert started.status_code == 303
    assert started.headers["location"] == f"{ASSIGNMENT}/attempt"
    attempt = site_client.get(started.headers["location"])
    assert attempt.status_code == 200
    assert "Question 1 of 10" in attempt.text
    assert "Question 10 of 10" in attempt.text
    assert "Save draft" in attempt.text
    assert "Submit" in attempt.text
    attempt_id = re.search(r'name="attempt_id" value="([a-f0-9]+)"', attempt.text)
    assert attempt_id is not None

    draft = _post_pairs(
        site_client,
        f"{ASSIGNMENT}/attempt/draft",
        [("attempt_id", attempt_id.group(1)), ("q_1", "0"), ("q_2", "0"), ("q_2", "1")],
    )
    assert draft.status_code == 303
    assert draft.headers["location"] == f"{ASSIGNMENT}/attempt?saved=1"
    reloaded = site_client.get(f"{ASSIGNMENT}/attempt")
    assert 'name="q_1" value="0" checked' in reloaded.text
    assert 'name="q_2" value="1" checked' in reloaded.text

    submitted = _post_pairs(
        site_client,
        f"{ASSIGNMENT}/attempt/submit",
        [("attempt_id", attempt_id.group(1)), *CORRECT_PAIRS, ("legal_name", "Progress Learner")],
    )
    assert submitted.status_code == 303
    assert submitted.headers["location"] == f"{ASSIGNMENT}/result/{attempt_id.group(1)}"
    result = site_client.get(submitted.headers["location"])
    assert result.status_code == 200
    assert "10 / 10" in result.text
    assert "100%" in result.text
    assert "Passed" in result.text
    assert "local course-knowledge" in result.text
    assert result.text.count("Correct") >= 10

    grades = site_client.get(f"{COURSE}/home/assignments")
    assert "10 / 10" in grades.text
    assert "Passed" in grades.text


def test_attempt_validation_and_owner_isolation(site_client) -> None:
    _login_enrolled(site_client)
    site_client.post(f"{ASSIGNMENT}/start", data={"honor_code": "accepted"})
    attempt = site_client.get(f"{ASSIGNMENT}/attempt")
    attempt_id = re.search(r'name="attempt_id" value="([a-f0-9]+)"', attempt.text)
    assert attempt_id is not None

    invalid = _post_pairs(
        site_client,
        f"{ASSIGNMENT}/attempt/draft",
        [("attempt_id", attempt_id.group(1)), ("q_99", "0")],
    )
    assert invalid.status_code == 422
    assert "Check your answers" in invalid.text

    site_client.post("/auth/logout")
    _login_empty(site_client)
    foreign = site_client.get(f"{ASSIGNMENT}/result/{attempt_id.group(1)}")
    assert foreign.status_code in {403, 404}
    assert "10 / 10" not in foreign.text

