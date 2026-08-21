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
        assert (
            connection.execute(
                "SELECT site_id FROM websitebench_site_binding WHERE singleton=1"
            ).fetchone()[0]
            == "33"
        )
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


def test_login_continuation_is_same_origin_and_course_cta_enrolls(
    site_client: TestClient,
) -> None:
    """Catch discarded/unsafe next targets and the authenticated login-only CTA."""

    course_path = "/learn/neural-networks-deep-learning"
    signed_out = site_client.get(course_path)
    assert signed_out.status_code == 200
    assert 'data-enrollment-login-open' in signed_out.text
    assert f'name="next" value="{course_path}"' in signed_out.text

    login = site_client.get("/login", params={"next": course_path})
    assert f'<input type="hidden" name="next" value="{course_path}">' in login.text
    accepted = site_client.post(
        "/auth/login",
        data={
            "email": "empty@coursera.test",
            "password": "Empty-Learner-33",
            "next": course_path,
        },
        follow_redirects=False,
    )
    assert accepted.status_code == 303
    assert accepted.headers["location"] == course_path

    authenticated = site_client.get(course_path)
    assert authenticated.status_code == 200
    assert 'data-enrollment-login-open' not in authenticated.text
    assert 'class="source-course-detail-actions"' in authenticated.text
    assert 'action="/enrollments"' in authenticated.text
    assert 'name="track" value="free"' in authenticated.text
    assert (
        '<input type="hidden" name="course_id" '
        'value="deep-learning-specialization">' in authenticated.text
    )
    enrolled = site_client.post(
        "/enrollments",
        data={"course_id": "deep-learning-specialization", "track": "free"},
        follow_redirects=False,
    )
    assert enrolled.status_code == 303
    assert enrolled.headers["location"] == "/my-learning"


def test_authenticated_course_cta_enrolls_the_displayed_catalog_course(
    site_client: TestClient,
) -> None:
    """Catch a generic course CTA silently enrolling Deep Learning instead."""

    _login_seeded(site_client, "empty@coursera.test", "Empty-Learner-33")
    detail = site_client.get("/learn/business-strategy")
    assert detail.status_code == 200
    assert "Foundations of Business Strategy" in detail.text
    assert '<input type="hidden" name="course_id" value="business-strategy">' in detail.text

    enrolled = site_client.post(
        "/enrollments",
        data={"course_id": "business-strategy", "track": "free"},
        follow_redirects=False,
    )
    assert enrolled.status_code == 303
    assert enrolled.headers["location"] == "/my-learning"

    learning = _learning_module()
    records = learning.list_enrollments("learner-empty")
    assert [(record["course_id"], record["track"]) for record in records] == [
        ("business-strategy", "free")
    ]
    dashboard = site_client.get("/my-learning")
    assert "Foundations of Business Strategy" in dashboard.text
    assert 'href="/learn/business-strategy"' in dashboard.text


def test_enrollment_rejects_unknown_catalog_ids_without_substitution(
    site_client: TestClient,
) -> None:
    """Catch invalid IDs being accepted or substituted with a default course."""

    _login_seeded(site_client, "empty@coursera.test", "Empty-Learner-33")
    rejected = site_client.post(
        "/enrollments",
        data={"course_id": "not-a-catalog-course", "track": "audit"},
        follow_redirects=False,
    )
    assert rejected.status_code == 422
    assert "course is unavailable" in rejected.text
    assert _learning_module().list_enrollments("learner-empty") == []


@pytest.mark.parametrize(
    "unsafe_next",
    [
        "//outside.example/path",
        "https://outside.example/path",
        "/../orders",
        "/%2e%2e/orders",
        "/%ZZ/orders",
        "/\\outside.example/path",
    ],
)
def test_login_rejects_unsafe_or_malformed_continuations(
    site_client: TestClient, unsafe_next: str
) -> None:
    """Catch login redirecting to a scheme-relative, external, or unsafe path."""

    login = site_client.get("/login", params={"next": unsafe_next})
    expected_hidden = '<input type="hidden" name="next" value="/my-learning">'
    assert expected_hidden in login.text
    response = site_client.post(
        "/auth/login",
        data={
            "email": "empty@coursera.test",
            "password": "Empty-Learner-33",
            "next": unsafe_next,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/my-learning"


def test_shared_header_switches_between_anonymous_and_learner_controls(
    site_client: TestClient,
) -> None:
    """Catch shared pages forgetting the authenticated request's chrome."""

    shared_paths = (
        "/",
        "/browse",
        "/learn/business-strategy",
        "/websitebench-auth-chrome-missing",
    )
    for path in shared_paths:
        anonymous = site_client.get(path)
        login_label = "Log In"
        join_label = "Join for Free"
        learning_label = "My Learning"
        assert f'data-login-open>{login_label}</button>' in anonymous.text, path
        assert f'class="wb-join" href="/signup">{join_label}</a>' in anonymous.text, path
        assert f'href="/my-learning">{learning_label}</a>' not in anonymous.text, path

    _login_seeded(site_client, "progress@coursera.test", "Progress-Learner-33")
    for path in shared_paths:
        authenticated = site_client.get(path)
        learning_label = "My Learning"
        logout_label = "Log out"
        login_label = "Log In"
        join_label = "Join for Free"
        assert 'class="wb-account-nav"' in authenticated.text, path
        assert f'href="/my-learning">{learning_label}</a>' in authenticated.text, path
        assert 'action="/auth/logout"' in authenticated.text, path
        assert logout_label in authenticated.text, path
        assert f'data-login-open>{login_label}</button>' not in authenticated.text, path
        assert f'href="/signup">{join_label}</a>' not in authenticated.text, path


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
    assert "Free learning track" in learning_page.text
    assert "No checkout or payment record was created" in learning_page.text

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
    assert "Free learning track" in history.text


def test_canceled_enrollment_reactivates_with_new_track_and_retains_history(
    site_client: TestClient,
) -> None:
    learning = _learning_module()
    first = learning.enroll(
        "learner-empty", course_id="deep-learning-specialization", track="free"
    )
    duplicate = learning.enroll(
        "learner-empty", course_id="deep-learning-specialization", track="free"
    )
    assert duplicate == first
    assert len(learning.list_enrollments("learner-empty")) == 1

    canceled = learning.cancel_enrollment("learner-empty", first["enrollment_id"])
    assert canceled["status"] == "canceled"
    assert canceled["canceled_at"] == "2026-08-16T00:00:00Z"

    reactivated = learning.enroll(
        "learner-empty", course_id="deep-learning-specialization", track="audit"
    )
    assert reactivated["enrollment_id"] == first["enrollment_id"]
    assert reactivated["status"] == "active"
    assert reactivated["track"] == "audit"
    assert reactivated["canceled_at"] == canceled["canceled_at"]
    assert len(learning.list_enrollments("learner-empty")) == 1

    _login_seeded(site_client, "empty@coursera.test", "Empty-Learner-33")
    history = site_client.get("/account/history")
    assert "In progress" in history.text
    assert "Audit track" in history.text
    assert "Previously canceled" in history.text


def test_authenticated_specialization_keeps_observed_free_and_routes_paid_to_checkout(
    site_client: TestClient,
) -> None:
    _login_seeded(site_client, "empty@coursera.test", "Empty-Learner-33")
    detail = site_client.get("/specializations/deep-learning")
    assert detail.status_code == 200
    assert 'action="/enrollments"' in detail.text
    assert 'value="free"' in detail.text
    assert 'value="audit"' not in detail.text
    assert 'value="paid"' not in detail.text
    assert 'href="/checkout/deep-learning"' in detail.text
    assert "View local paid option" in detail.text

    bypass = site_client.post(
        "/enrollments",
        data={"course_id": "deep-learning-specialization", "track": "paid"},
        follow_redirects=False,
    )
    assert bypass.status_code == 422
    assert "paid enrollment requires checkout" in bypass.text


@pytest.mark.parametrize(
    ("path", "payload", "expected_heading"),
    [
        (
            "/learning/quizzes/quiz-improving-networks",
            {"answer": "not-an-available-answer"},
            "Check your answer",
        ),
        (
            "/learning/review",
            {"rating": "0", "review_text": "Synthetic invalid review"},
            "Check your review",
        ),
        (
            "/account/preferences",
            {"language": "", "timezone": "", "email_updates": "1"},
            "Check preferences",
        ),
    ],
    ids=("quiz", "review", "preferences"),
)
def test_authenticated_validation_errors_render_422_with_learner_chrome(
    site_client: TestClient,
    path: str,
    payload: dict[str, str],
    expected_heading: str,
) -> None:
    """Catch validation branches calling the request renderer with stale args."""

    _login_seeded(site_client, "progress@coursera.test", "Progress-Learner-33")
    response = site_client.post(path, data=payload, follow_redirects=False)

    assert response.status_code == 422
    assert f"<h1>{expected_heading}</h1>" in response.text
    assert 'class="wb-account-nav"' in response.text
    assert 'action="/auth/logout"' in response.text
    assert 'data-login-open>登录</button>' not in response.text
    assert 'href="/signup">免费加入</a>' not in response.text


def test_active_enrollment_gates_protected_learning_and_mutations(
    site_client: TestClient,
) -> None:
    _login_seeded(site_client, "empty@coursera.test", "Empty-Learner-33")

    preview = site_client.get(
        "/learn/neural-networks-deep-learning/lesson/lesson-neural-intro"
    )
    protected = site_client.get(
        "/learn/neural-networks-deep-learning/lesson/lesson-optimization"
    )
    assert preview.status_code == 200
    assert "Public offline preview" in preview.text
    assert protected.status_code == 403
    assert "Enroll locally to open this lesson" in protected.text

    blocked_requests = (
        site_client.post(
            "/learning/bookmarks/lesson-neural-intro",
            data={"bookmarked": "1"},
            follow_redirects=False,
        ),
        site_client.post(
            "/learning/progress/lesson-neural-intro",
            follow_redirects=False,
        ),
        site_client.post(
            "/learning/quizzes/quiz-neural-foundations",
            data={"answer": "Activation function"},
            follow_redirects=False,
        ),
        site_client.post(
            "/learning/review",
            data={"rating": "5", "review_text": "Blocked without enrollment"},
            follow_redirects=False,
        ),
    )
    assert [response.status_code for response in blocked_requests] == [404] * 4

    dashboard = site_client.get("/my-learning")
    assert "data-resume-lesson=" not in dashboard.text
    assert 'action="/learning/review"' not in dashboard.text
    assert "Certificate available" not in dashboard.text

    enrolled = site_client.post(
        "/enrollments",
        data={"course_id": "deep-learning-specialization", "track": "free"},
        follow_redirects=False,
    )
    assert enrolled.status_code == 303
    protected_after_enrollment = site_client.get(
        "/learn/neural-networks-deep-learning/lesson/lesson-optimization"
    )
    assert protected_after_enrollment.status_code == 200
    assert "Mark complete" in protected_after_enrollment.text

    learning = _learning_module()
    enrollment_id = learning.list_enrollments("learner-empty")[0]["enrollment_id"]
    canceled = site_client.post(
        f"/enrollments/{enrollment_id}/cancel", follow_redirects=False
    )
    assert canceled.status_code == 303
    blocked_after_cancel = site_client.post(
        "/learning/progress/lesson-neural-intro", follow_redirects=False
    )
    assert blocked_after_cancel.status_code == 404


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
    assert (
        'href="/learn/neural-networks-deep-learning/lesson/lesson-forward-propagation"'
        in lesson.text
    )
    assert (
        'href="/learn/neural-networks-deep-learning/lesson/lesson-regularization"'
        in lesson.text
    )

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
    assert "Quiz score: 0" in wrong.text
    assert "Review the regularization lesson" in wrong.text
    assert "Quiz score: 100" in correct.text
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


def test_my_learning_tabs_filter_in_progress_completed_and_certificates(
    site_client: TestClient,
) -> None:
    _login_seeded(site_client, "progress@coursera.test", "Progress-Learner-33")

    in_progress = site_client.get("/my-learning")
    completed = site_client.get("/my-learning?status=completed")
    certificates = site_client.get("/my-learning?status=certificates")

    assert 'class="is-active" href="/my-learning">In Progress</a>' in in_progress.text
    assert "Deep Learning Specialization" in in_progress.text
    assert 'class="is-active" href="/my-learning?status=completed">Completed</a>' in completed.text
    assert "You have no completed courses yet." in completed.text
    assert 'class="is-active" href="/my-learning?status=certificates">Certificates</a>' in certificates.text
    assert "You have no certificates yet." in certificates.text


def test_learning_goal_selection_persists_and_is_reflected_on_dashboard(
    site_client: TestClient,
) -> None:
    _login_seeded(site_client, "empty@coursera.test", "Empty-Learner-33")

    goal_page = site_client.get("/onboarding/learning-goal")
    saved = site_client.post(
        "/onboarding/learning-goal",
        data={"learning_goal": "Grow in my current role"},
        follow_redirects=False,
    )
    dashboard = site_client.get("/my-learning")
    invalid = site_client.post(
        "/onboarding/learning-goal",
        data={"learning_goal": "Unrecognized goal"},
        follow_redirects=False,
    )

    assert goal_page.status_code == 200
    assert 'action="/onboarding/learning-goal"' in goal_page.text
    assert 'name="learning_goal"' in goal_page.text
    assert saved.status_code == 303
    assert saved.headers["location"] == "/my-learning"
    assert "Grow in my current role" in dashboard.text
    assert invalid.status_code == 422
    assert "Choose one available learning goal" in invalid.text


def test_bookmark_and_progress_collections_expose_owner_learning_state(
    site_client: TestClient,
) -> None:
    _login_seeded(site_client, "progress@coursera.test", "Progress-Learner-33")

    dashboard = site_client.get("/my-learning")
    bookmarks = site_client.get("/learning/bookmarks")
    progress = site_client.get("/learning/progress")

    assert 'href="/learning/bookmarks"' in dashboard.text
    assert 'href="/learning/progress"' in dashboard.text
    assert "2 of 6 lessons completed" in dashboard.text
    assert bookmarks.status_code == 200
    assert "Saved lessons" in bookmarks.text
    assert "Optimization methods" in bookmarks.text
    assert 'href="/learn/neural-networks-deep-learning/lesson/lesson-optimization"' in bookmarks.text
    assert progress.status_code == 200
    assert "Course progress" in progress.text
    assert "2 of 6 lessons completed" in progress.text
    assert "33%" in progress.text
    assert "Optimization methods" in progress.text


def test_bookmark_and_progress_collections_require_authentication() -> None:
    with TestClient(app, base_url="https://33.offline.invalid") as client:
        bookmarks = client.get("/learning/bookmarks")
        progress = client.get("/learning/progress")

    assert bookmarks.status_code == progress.status_code == 401
    assert "Sign in" in bookmarks.text
    assert "Sign in" in progress.text


def test_enrollment_history_links_to_owner_bound_record_detail(
    site_client: TestClient,
) -> None:
    _login_seeded(site_client, "progress@coursera.test", "Progress-Learner-33")
    history = site_client.get("/account/history")
    enrollment_id = re.search(
        r'data-enrollment-id="([0-9]+)"', history.text
    ).group(1)
    detail = site_client.get(f"/account/history/{enrollment_id}")

    assert f'href="/account/history/{enrollment_id}"' in history.text
    assert detail.status_code == 200
    assert "Enrollment details" in detail.text
    assert "In progress" in detail.text
    assert "Audit track" in detail.text
    assert f'action="/enrollments/{enrollment_id}/cancel"' in detail.text
    assert 'href="/account/history"' in detail.text

    with TestClient(app, base_url="https://33.offline.invalid") as other:
        _login_seeded(other, "empty@coursera.test", "Empty-Learner-33")
        foreign = other.get(f"/account/history/{enrollment_id}")

    assert foreign.status_code == 404
    assert "Enrollment not found" in foreign.text


def test_progress_replay_keeps_resume_at_first_incomplete_lesson(
    site_client: TestClient,
) -> None:
    learning = _learning_module()

    learning.complete_lesson("learner-in-progress", "lesson-error-analysis")
    assert learning.learning_state("learner-in-progress")["resume_lesson_id"] == (
        "lesson-optimization"
    )

    learning.complete_lesson("learner-in-progress", "lesson-optimization")
    assert learning.learning_state("learner-in-progress")["resume_lesson_id"] == (
        "lesson-regularization"
    )

    learning.complete_lesson("learner-in-progress", "lesson-neural-intro")
    assert learning.learning_state("learner-in-progress")["resume_lesson_id"] == (
        "lesson-regularization"
    )
    assert (
        learning.learning_state("learner-in-progress")["completed_lessons"].count(
            "lesson-neural-intro"
        )
        == 1
    )


def test_unknown_bookmark_and_progress_lessons_return_safe_branded_404(
    site_client: TestClient,
) -> None:
    with TestClient(
        app,
        base_url="https://33.offline.invalid",
        raise_server_exceptions=False,
    ) as browser:
        _login_seeded(browser, "progress@coursera.test", "Progress-Learner-33")
        bookmark = browser.post(
            "/learning/bookmarks/lesson-does-not-exist",
            data={"bookmarked": "1"},
            follow_redirects=False,
        )
        progress = browser.post(
            "/learning/progress/lesson-does-not-exist",
            follow_redirects=False,
        )

    assert bookmark.status_code == progress.status_code == 404
    assert "Learning item not found" in bookmark.text
    assert "Learning item not found" in progress.text
    assert "Traceback" not in bookmark.text + progress.text


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
    assert ">Updated offline review</textarea>" in dashboard.text

    attempt = learning.submit_quiz(
        "learner-in-progress",
        "quiz-neural-foundations",
        "Activation function",
    )
    with pytest.raises(LookupError, match="Quiz attempt not found"):
        learning.get_quiz_attempt("learner-empty", attempt["attempt_id"])


def test_business_state_persists_across_backend_reopen(site_client: TestClient) -> None:
    learning = _learning_module()
    initial_backend, initial_auth = learning.services()
    created = learning.enroll(
        "learner-empty", course_id="deep-learning-specialization", track="audit"
    )
    learning.complete_lesson("learner-empty", "lesson-neural-intro")
    learning.upsert_review(
        "learner-empty", rating=4, review_text="Persistent local review"
    )
    anonymous_session = initial_auth.create_anonymous_session()
    authenticated_session = initial_auth.sign_in(
        anonymous_session,
        email="empty@coursera.test",
        password="Empty-Learner-33",
    )["session_token"]
    database_path = initial_backend.lifecycle.database_path

    learning.close_services()
    reopened_backend, reopened_auth = learning.services()
    assert reopened_backend is not initial_backend
    assert reopened_auth is not initial_auth
    assert reopened_backend.lifecycle.database_path == database_path
    resolved_session = reopened_auth.resolve_session(authenticated_session)
    assert resolved_session is not None
    assert resolved_session["authenticated"] is True
    assert resolved_session["account"]["subject_id"] == "learner-empty"
    assert (
        learning.list_enrollments("learner-empty")[0]["enrollment_id"]
        == created["enrollment_id"]
    )
    assert (
        "lesson-neural-intro"
        in learning.learning_state("learner-empty")["completed_lessons"]
    )
    assert (
        learning.get_review("learner-empty", "deep-learning-specialization")[
            "review_text"
        ]
        == "Persistent local review"
    )


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
        "learner-empty", course_id="deep-learning-specialization", track="audit"
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
    _backend, auth = learning.services()
    registration_session = auth.create_anonymous_session()
    auth.start_registration(
        registration_session,
        email="reset-candidate@coursera.test",
        display_name="Reset Candidate",
        password="Reset-Candidate-33",
    )
    recovery_session = auth.create_anonymous_session()
    auth.start_password_reset(
        recovery_session,
        email="progress@coursera.test",
    )
    login_session = auth.create_anonymous_session()
    auth.sign_in(
        login_session,
        email="progress@coursera.test",
        password="Progress-Learner-33",
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
    assert first["auth"] == {
        "accounts": [
            (
                "learner-empty",
                "empty@coursera.test",
                "Empty Learner",
                1,
            ),
            (
                "learner-in-progress",
                "progress@coursera.test",
                "Progress Learner",
                1,
            ),
        ],
        "sessions": {"anonymous": 0, "authenticated": 0, "revoked": 0},
        "registration_challenges": {"active": 0, "verified": 0},
        "recovery_challenges": {"active": 0, "verified": 0},
        "outbox": [],
        "rate_limits": [],
    }


def test_local_inbox_presence_is_cleared_after_each_equivalent_reset(
    site_client: TestClient,
) -> None:
    learning = _learning_module()
    with (
        TestClient(app, base_url="https://33.offline.invalid") as registration_browser,
        TestClient(app, base_url="https://33.offline.invalid") as recovery_browser,
    ):
        registration_browser.get("/signup")
        registration_started = registration_browser.post(
            "/auth/registration/start",
            data={
                "email": "reset-inbox@coursera.test",
                "display_name": "Reset Inbox",
                "password": "Reset-Inbox-33",
            },
            follow_redirects=False,
        )
        assert registration_started.status_code == 303
        registration_inbox = registration_browser.get(
            "/local-inbox?purpose=registration"
        )

        recovery_browser.get("/account-recovery")
        recovery_started = recovery_browser.post(
            "/auth/recovery/start",
            data={"email": "progress@coursera.test"},
            follow_redirects=False,
        )
        assert recovery_started.status_code == 303
        recovery_inbox = recovery_browser.get("/local-inbox?purpose=password-reset")

        assert registration_inbox.headers.get("x-local-inbox-purpose") == (
            "registration"
        )
        assert recovery_inbox.headers.get("x-local-inbox-purpose") == ("password-reset")

        learning.reset()
        after_first_reset = (
            registration_browser.get("/local-inbox?purpose=registration"),
            recovery_browser.get("/local-inbox?purpose=password-reset"),
        )
        assert all(
            response.headers.get("x-local-inbox-purpose") is None
            for response in after_first_reset
        )

        learning.reset()
        after_second_reset = (
            registration_browser.get("/local-inbox?purpose=registration"),
            recovery_browser.get("/local-inbox?purpose=password-reset"),
        )
        assert all(
            response.headers.get("x-local-inbox-purpose") is None
            for response in after_second_reset
        )
