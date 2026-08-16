from __future__ import annotations

import importlib
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import app


SITE_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_PATH = SITE_ROOT / "backend" / "runtime.json"


def _learning_module():
    return importlib.import_module("backend.learning_db")


@pytest.fixture
def site_client(tmp_path, monkeypatch):
    database = tmp_path / "33.sqlite3"
    monkeypatch.setenv("WEBSITEBENCH_SITE_BACKEND_DATABASE", str(database))
    learning = _learning_module()
    learning.close_services()
    with TestClient(app, base_url="https://33.offline.invalid") as client:
        yield client
    learning.close_services()


def test_runtime_hooks_create_site_bound_schema_content_and_two_seed_users(
    tmp_path, monkeypatch
) -> None:
    runtime = json.loads(RUNTIME_PATH.read_text(encoding="utf-8"))
    assert runtime["database"]["migration_hook"] == "backend.learning_db:migrate"
    assert runtime["database"]["seed_hook"] == "backend.learning_db:seed"

    database = tmp_path / "33.sqlite3"
    monkeypatch.setenv("WEBSITEBENCH_SITE_BACKEND_DATABASE", str(database))
    learning = _learning_module()
    learning.close_services()
    backend, auth = learning.services()

    assert backend.config.site_id == "33"
    assert backend.lifecycle.database_path == database
    assert backend.session_cookie == {
        "name": "__Host-websitebench-33-session",
        "secure": True,
        "httponly": True,
        "samesite": "Lax",
        "path": "/",
    }
    with backend.lifecycle.connection() as connection:
        assert connection.execute(
            "SELECT site_id FROM websitebench_site_binding WHERE singleton=1"
        ).fetchone()[0] == "33"
        counts = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "coursera_modules",
                "coursera_lessons",
                "coursera_quizzes",
                "coursera_profiles",
            )
        }
        migrations = {
            row[0]
            for row in connection.execute(
                "SELECT migration_id FROM websitebench_backend_migrations"
            )
        }
    assert counts == {
        "coursera_modules": 3,
        "coursera_lessons": 6,
        "coursera_quizzes": 3,
        "coursera_profiles": 2,
    }
    assert migrations >= {
        "site-migration:backend.learning_db:migrate",
        "site-seed:backend.learning_db:seed",
    }
    assert auth.account_exists("progress@coursera.test")
    assert auth.account_exists("empty@coursera.test")
    learning.close_services()


def test_registration_validation_local_inbox_login_logout_and_provider_boundaries(
    site_client: TestClient,
) -> None:
    signup = site_client.get("/signup")
    assert signup.status_code == 200
    assert 'action="/auth/registration/start"' in signup.text
    for provider in ("google", "facebook", "apple"):
        assert f'href="/auth/provider/{provider}"' in signup.text

    invalid = site_client.post(
        "/auth/registration/start",
        data={
            "email": "person@example.com",
            "display_name": "Example Person",
            "password": "Local-Password-33",
        },
        follow_redirects=False,
    )
    assert invalid.status_code == 422
    assert "Use a synthetic .test address" in invalid.text

    started = site_client.post(
        "/auth/registration/start",
        data={
            "email": "new.learner@coursera.test",
            "display_name": "New Learner",
            "password": "Local-Password-33",
        },
        follow_redirects=False,
    )
    assert started.status_code == 303
    assert started.headers["location"] == "/local-inbox?purpose=registration"
    inbox = site_client.get(started.headers["location"])
    assert "Coursera local inbox" in inbox.text
    assert "No real email was sent" in inbox.text
    code_match = re.search(r'data-verification-code="([0-9]{6})"', inbox.text)
    assert code_match is not None

    wrong = site_client.post(
        "/auth/registration/verify",
        data={"code": "000000"},
        follow_redirects=False,
    )
    assert wrong.status_code == 400
    assert "verification code is invalid" in wrong.text

    verified = site_client.post(
        "/auth/registration/verify",
        data={"code": code_match.group(1)},
        follow_redirects=False,
    )
    assert verified.status_code == 303
    assert verified.headers["location"] == "/onboarding"
    onboarded = site_client.post(
        "/onboarding",
        data={"current_role": "Engineer", "learning_goal": "Learn safely offline"},
        follow_redirects=False,
    )
    assert onboarded.status_code == 303
    assert onboarded.headers["location"] == "/my-learning"

    signed_out = site_client.post("/auth/logout", follow_redirects=False)
    assert signed_out.status_code == 303
    rejected = site_client.post(
        "/auth/login",
        data={"email": "new.learner@coursera.test", "password": "wrong-password"},
        follow_redirects=False,
    )
    assert rejected.status_code == 401
    accepted = site_client.post(
        "/auth/login",
        data={
            "email": "new.learner@coursera.test",
            "password": "Local-Password-33",
        },
        follow_redirects=False,
    )
    assert accepted.status_code == 303
    assert accepted.headers["location"] == "/my-learning"

    for provider in ("google", "facebook", "apple"):
        boundary = site_client.get(f"/auth/provider/{provider}")
        assert boundary.status_code == 200
        assert "Offline identity boundary" in boundary.text
        assert "No external sign-in was opened" in boundary.text


def test_password_recovery_is_local_non_enumerating_and_rotates_credentials(
    site_client: TestClient,
) -> None:
    site_client.get("/account-recovery")
    started = site_client.post(
        "/auth/recovery/start",
        data={"email": "progress@coursera.test"},
        follow_redirects=False,
    )
    assert started.status_code == 303
    inbox = site_client.get("/local-inbox?purpose=password-reset")
    assert "Coursera local inbox" in inbox.text
    code_match = re.search(r'data-verification-code="([0-9]{6})"', inbox.text)
    assert code_match is not None

    wrong = site_client.post(
        "/auth/recovery/complete",
        data={"code": "000000", "new_password": "Changed-Password-33"},
        follow_redirects=False,
    )
    assert wrong.status_code == 400
    completed = site_client.post(
        "/auth/recovery/complete",
        data={
            "code": code_match.group(1),
            "new_password": "Changed-Password-33",
        },
        follow_redirects=False,
    )
    assert completed.status_code == 303
    assert completed.headers["location"] == "/my-learning"

    site_client.post("/auth/logout", follow_redirects=False)
    old_password = site_client.post(
        "/auth/login",
        data={
            "email": "progress@coursera.test",
            "password": "Progress-Learner-33",
        },
        follow_redirects=False,
    )
    assert old_password.status_code == 401
    new_password = site_client.post(
        "/auth/login",
        data={
            "email": "progress@coursera.test",
            "password": "Changed-Password-33",
        },
        follow_redirects=False,
    )
    assert new_password.status_code == 303

    site_client.post("/auth/logout", follow_redirects=False)
    site_client.cookies.clear()
    site_client.get("/account-recovery")
    unknown = site_client.post(
        "/auth/recovery/start",
        data={"email": "unknown@coursera.test"},
        follow_redirects=False,
    )
    assert unknown.status_code == 303
    assert "If a matching local account exists" in unknown.headers["x-auth-message"]
    empty_inbox = site_client.get("/local-inbox?purpose=password-reset")
    assert "No local message is available" in empty_inbox.text


def _login_seeded(client: TestClient, email: str, password: str) -> None:
    client.get("/login")
    response = client.post(
        "/auth/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )
    assert response.status_code == 303


def test_enrollment_history_cancel_idempotency_and_owner_isolation(
    site_client: TestClient,
) -> None:
    signed_out = site_client.get("/my-learning")
    assert signed_out.status_code == 401
    assert "Sign in to view My Learning" in signed_out.text

    _login_seeded(site_client, "empty@coursera.test", "Empty-Learner-33")
    invalid = site_client.post(
        "/enrollments",
        data={"course_id": "deep-learning-specialization", "track": ""},
        follow_redirects=False,
    )
    assert invalid.status_code == 422

    first = site_client.post(
        "/enrollments",
        data={"course_id": "deep-learning-specialization", "track": "free"},
        follow_redirects=False,
    )
    duplicate = site_client.post(
        "/enrollments",
        data={"course_id": "deep-learning-specialization", "track": "free"},
        follow_redirects=False,
    )
    assert first.status_code == duplicate.status_code == 303
    learning_page = site_client.get("/my-learning")
    enrollment_ids = re.findall(r'data-enrollment-id="([0-9]+)"', learning_page.text)
    assert len(enrollment_ids) == 1
    enrollment_id = enrollment_ids[0]
    assert "Free track" in learning_page.text
    assert "No checkout or payment was created" in learning_page.text

    with TestClient(app, base_url="https://33.offline.invalid") as other:
        _login_seeded(other, "progress@coursera.test", "Progress-Learner-33")
        foreign = other.post(
            f"/enrollments/{enrollment_id}/cancel",
            follow_redirects=False,
        )
        assert foreign.status_code == 404
        assert "Enrollment not found" in foreign.text

    canceled = site_client.post(
        f"/enrollments/{enrollment_id}/cancel",
        follow_redirects=False,
    )
    canceled_again = site_client.post(
        f"/enrollments/{enrollment_id}/cancel",
        follow_redirects=False,
    )
    assert canceled.status_code == canceled_again.status_code == 303
    history = site_client.get("/account/history")
    assert history.status_code == 200
    assert f'data-enrollment-id="{enrollment_id}"' in history.text
    assert "Canceled" in history.text
    assert "Free track" in history.text


def test_authenticated_specialization_offers_all_local_tracks_without_checkout(
    site_client: TestClient,
) -> None:
    _login_seeded(site_client, "empty@coursera.test", "Empty-Learner-33")
    detail = site_client.get("/specializations/deep-learning")
    assert detail.status_code == 200
    assert 'action="/enrollments"' in detail.text
    assert 'value="free"' in detail.text
    assert 'value="audit"' in detail.text
    assert 'value="paid"' in detail.text
    assert "No checkout or payment occurs in Task 4" in detail.text
    assert 'action="/checkout' not in detail.text


def test_learning_preview_navigation_bookmarks_progress_quizzes_and_certificate(
    site_client: TestClient,
) -> None:
    preview = site_client.get(
        "/learn/neural-networks-deep-learning/lesson/lesson-neural-intro"
    )
    assert preview.status_code == 200
    assert "Public offline preview" in preview.text
    protected = site_client.get(
        "/learn/neural-networks-deep-learning/lesson/lesson-optimization"
    )
    assert protected.status_code == 401
    assert "Sign in to open this lesson" in protected.text

    _login_seeded(site_client, "progress@coursera.test", "Progress-Learner-33")
    lesson = site_client.get(
        "/learn/neural-networks-deep-learning/lesson/lesson-optimization"
    )
    assert lesson.status_code == 200
    assert "Module 2 of 3" in lesson.text
    assert 'href="/learn/neural-networks-deep-learning/lesson/lesson-forward-propagation"' in lesson.text
    assert 'href="/learn/neural-networks-deep-learning/lesson/lesson-regularization"' in lesson.text

    for _ in range(2):
        bookmarked = site_client.post(
            "/learning/bookmarks/lesson-regularization",
            data={"bookmarked": "1"},
            follow_redirects=False,
        )
        completed = site_client.post(
            "/learning/progress/lesson-optimization",
            follow_redirects=False,
        )
        assert bookmarked.status_code == completed.status_code == 303

    learning = _learning_module()
    state = learning.learning_state("learner-in-progress")
    assert state["bookmarks"].count("lesson-regularization") == 1
    assert state["completed_lessons"].count("lesson-optimization") == 1
    assert state["resume_lesson_id"] == "lesson-regularization"
    assert state["certificate_available"] is False

    wrong = site_client.post(
        "/learning/quizzes/quiz-improving-networks",
        data={"answer": "Remote checkout"},
        follow_redirects=False,
    )
    correct = site_client.post(
        "/learning/quizzes/quiz-improving-networks",
        data={"answer": "Regularization"},
        follow_redirects=False,
    )
    assert wrong.status_code == correct.status_code == 200
    assert "score: 0" in wrong.text
    assert "Review the regularization lesson" in wrong.text
    assert "score: 100" in correct.text
    assert "Correct: regularization" in correct.text

    for lesson_id in (
        "lesson-neural-intro",
        "lesson-forward-propagation",
        "lesson-optimization",
        "lesson-regularization",
        "lesson-error-analysis",
        "lesson-transfer-learning",
    ):
        site_client.post(f"/learning/progress/{lesson_id}", follow_redirects=False)
    for quiz_id, answer in (
        ("quiz-neural-foundations", "Activation function"),
        ("quiz-improving-networks", "Regularization"),
        ("quiz-ml-strategy", "Error analysis"),
    ):
        site_client.post(
            f"/learning/quizzes/{quiz_id}",
            data={"answer": answer},
            follow_redirects=False,
        )
    completed_state = learning.learning_state("learner-in-progress")
    assert completed_state["certificate_available"] is True
    dashboard = site_client.get("/my-learning")
    assert "Certificate available" in dashboard.text
    assert 'data-resume-lesson="lesson-transfer-learning"' in dashboard.text


def test_review_preferences_are_updatable_and_quiz_attempts_are_owner_scoped(
    site_client: TestClient,
) -> None:
    _login_seeded(site_client, "progress@coursera.test", "Progress-Learner-33")
    first_review = site_client.post(
        "/learning/review",
        data={"rating": "3", "review_text": "Useful local practice"},
        follow_redirects=False,
    )
    updated_review = site_client.post(
        "/learning/review",
        data={"rating": "5", "review_text": "Updated offline review"},
        follow_redirects=False,
    )
    preferences = site_client.post(
        "/account/preferences",
        data={"language": "Spanish", "timezone": "Asia/Shanghai", "email_updates": "1"},
        follow_redirects=False,
    )
    assert first_review.status_code == updated_review.status_code == 303
    assert preferences.status_code == 303

    learning = _learning_module()
    review = learning.get_review("learner-in-progress", "deep-learning-specialization")
    assert review["rating"] == 5
    assert review["review_text"] == "Updated offline review"
    assert learning.review_count("learner-in-progress") == 1
    assert learning.get_review("learner-empty", "deep-learning-specialization") is None
    saved_preferences = learning.get_preferences("learner-in-progress")
    assert saved_preferences == {
        "language": "Spanish",
        "timezone": "Asia/Shanghai",
        "email_updates": True,
    }
    dashboard = site_client.get("/my-learning")
    assert 'action="/learning/review"' in dashboard.text
    assert '<option value="5" selected>' in dashboard.text
    assert '>Updated offline review</textarea>' in dashboard.text

    attempt = learning.submit_quiz(
        "learner-in-progress",
        "quiz-neural-foundations",
        "Activation function",
    )
    with pytest.raises(LookupError, match="Quiz attempt not found"):
        learning.get_quiz_attempt("learner-empty", attempt["attempt_id"])


def test_business_state_persists_across_backend_reopen(site_client: TestClient) -> None:
    learning = _learning_module()
    created = learning.enroll(
        "learner-empty", course_id="deep-learning-specialization", track="audit"
    )
    learning.complete_lesson("learner-empty", "lesson-neural-intro")
    learning.upsert_review(
        "learner-empty", rating=4, review_text="Persistent local review"
    )
    database_path = learning.services()[0].lifecycle.database_path

    learning.close_services()
    reopened = learning.services()[0]
    assert reopened.lifecycle.database_path == database_path
    assert learning.list_enrollments("learner-empty")[0]["enrollment_id"] == created[
        "enrollment_id"
    ]
    assert "lesson-neural-intro" in learning.learning_state("learner-empty")[
        "completed_lessons"
    ]
    assert learning.get_review("learner-empty", "deep-learning-specialization")[
        "review_text"
    ] == "Persistent local review"


def test_concurrent_enrollment_and_progress_are_lossless_and_idempotent(
    site_client: TestClient,
) -> None:
    learning = _learning_module()

    def enroll_once(_index: int):
        return learning.enroll(
            "learner-empty", course_id="deep-learning-specialization", track="free"
        )["enrollment_id"]

    def complete_once(_index: int):
        learning.complete_lesson("learner-empty", "lesson-neural-intro")
        return True

    with ThreadPoolExecutor(max_workers=4) as executor:
        enrollment_ids = list(executor.map(enroll_once, range(8)))
        assert all(executor.map(complete_once, range(8)))
    assert len(set(enrollment_ids)) == 1
    assert len(learning.list_enrollments("learner-empty")) == 1
    assert learning.learning_state("learner-empty")["completed_lessons"] == [
        "lesson-neural-intro"
    ]


def test_two_equivalent_resets_restore_identical_seed_state(
    site_client: TestClient,
) -> None:
    learning = _learning_module()
    learning.reset()
    first = learning.state_snapshot()

    learning.enroll(
        "learner-empty", course_id="deep-learning-specialization", track="paid"
    )
    learning.complete_lesson("learner-empty", "lesson-neural-intro")
    learning.submit_quiz(
        "learner-empty", "quiz-neural-foundations", "Activation function"
    )
    learning.upsert_review("learner-empty", rating=2, review_text="Reset me")
    learning.update_preferences(
        "learner-empty",
        language="French",
        timezone="Europe/Paris",
        email_updates=True,
    )

    learning.reset()
    second = learning.state_snapshot()
    learning.reset()
    third = learning.state_snapshot()
    assert first == second == third
    assert len(first["modules"]) == 3
    assert len(first["lessons"]) == 6
    assert len(first["quizzes"]) == 3
    assert [row[1] for row in first["profiles"]] == [
        "learner-empty",
        "learner-in-progress",
    ]
