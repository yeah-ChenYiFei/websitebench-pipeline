from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend import assignment_db, learning_db


UTC = timezone.utc
START = datetime(2026, 8, 20, 9, 0, tzinfo=UTC)
CORRECT = {
    1: [0],
    2: [0, 1],
    3: [2, 3],
    4: [1],
    5: [2],
    6: [0],
    7: [1],
    8: [0, 2],
    9: [0],
    10: [2, 3],
}


@pytest.fixture
def assignment_environment(tmp_path, monkeypatch):
    database = tmp_path / "33.sqlite3"
    monkeypatch.setenv("WEBSITEBENCH_SITE_BACKEND_DATABASE", str(database))
    learning_db.close_services()
    learning_db.services()
    yield database
    learning_db.close_services()


def test_migration_is_repeatable_and_enrolled_seed_is_distinct(
    assignment_environment,
) -> None:
    backend, _auth = learning_db.services()
    with backend.lifecycle.connection(transaction=True) as connection:
        assignment_db.migrate(connection)
        assignment_db.migrate(connection)
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'coursera_assignment_%'"
            )
        }
    assert tables == {
        "coursera_assignment_attempts",
        "coursera_assignment_drafts",
        "coursera_assignment_results",
    }
    assert assignment_db.course_access("learner-in-progress")["enrolled"] is True
    with pytest.raises(LookupError, match="Active enrollment"):
        assignment_db.course_access("learner-empty")


def test_notes_are_owner_scoped_searchable_and_deletable(
    assignment_environment,
) -> None:
    note = assignment_db.save_note("learner-in-progress", "  Gradient descent insight  ")
    assert note["text"] == "Gradient descent insight"
    assert assignment_db.list_notes("learner-in-progress", "gradient") == [note]
    assert assignment_db.list_notes("learner-empty") == []

    with pytest.raises(LookupError, match="Note not found"):
        assignment_db.delete_note("learner-empty", int(note["note_id"]))
    assignment_db.delete_note("learner-in-progress", int(note["note_id"]))
    assert assignment_db.list_notes("learner-in-progress") == []


def test_attempt_resumes_and_draft_survives_service_restart(
    assignment_environment,
) -> None:
    attempt = assignment_db.start_or_resume_attempt("learner-in-progress", now=START)
    resumed = assignment_db.start_or_resume_attempt(
        "learner-in-progress", now=START + timedelta(minutes=2)
    )
    assert resumed["attempt_id"] == attempt["attempt_id"]
    assert resumed["remaining_seconds"] == 48 * 60

    saved = assignment_db.save_draft(
        "learner-in-progress",
        str(attempt["attempt_id"]),
        {1: [0], 2: [1, 0]},
        now=START + timedelta(minutes=3),
    )
    assert saved["answers"] == {1: (0,), 2: (0, 1)}

    learning_db.close_services()
    reopened = assignment_db.get_attempt(
        "learner-in-progress",
        str(attempt["attempt_id"]),
        now=START + timedelta(minutes=4),
    )
    assert reopened["answers"] == {1: (0,), 2: (0, 1)}
    with pytest.raises(LookupError, match="Attempt not found"):
        assignment_db.get_attempt(
            "learner-empty", str(attempt["attempt_id"]), now=START
        )
    with pytest.raises(LookupError, match="Attempt not found"):
        assignment_db.save_draft(
            "learner-empty",
            str(attempt["attempt_id"]),
            {99: [99]},
            now=START,
        )


def test_expired_attempt_auto_submits_current_draft_with_zero_for_unanswered(
    assignment_environment,
) -> None:
    attempt = assignment_db.start_or_resume_attempt("learner-in-progress", now=START)
    assignment_db.save_draft(
        "learner-in-progress",
        str(attempt["attempt_id"]),
        {1: [0]},
        now=START + timedelta(minutes=1),
    )

    expired = assignment_db.get_attempt(
        "learner-in-progress",
        str(attempt["attempt_id"]),
        now=START + timedelta(minutes=51),
    )
    assert expired["status"] == "submitted"
    assert expired["submission_reason"] == "expired"
    assert expired["score"] == 1
    assert len(expired["question_results"]) == 10
    assert expired["question_results"][1]["selected"] == ()


def test_manual_submission_validates_name_scores_and_is_immutable(
    assignment_environment,
) -> None:
    attempt = assignment_db.start_or_resume_attempt("learner-in-progress", now=START)
    attempt_id = str(attempt["attempt_id"])
    with pytest.raises(ValueError, match="legal name"):
        assignment_db.submit_attempt(
            "learner-in-progress",
            attempt_id,
            CORRECT,
            "Different Learner",
            now=START + timedelta(minutes=5),
        )
    with pytest.raises(ValueError, match="Answer every question"):
        assignment_db.submit_attempt(
            "learner-in-progress",
            attempt_id,
            {1: [0]},
            "  Progress   Learner ",
            now=START + timedelta(minutes=5),
        )

    result = assignment_db.submit_attempt(
        "learner-in-progress",
        attempt_id,
        CORRECT,
        "  Progress   Learner ",
        now=START + timedelta(minutes=5),
    )
    assert result["score"] == 10
    assert result["max_score"] == 10
    assert result["percentage"] == 100
    assert result["passed"] is True
    assert result["provenance"] == "clone-local-course-knowledge-derived"

    duplicate = assignment_db.submit_attempt(
        "learner-in-progress",
        attempt_id,
        {1: [2]},
        "wrong and ignored for immutable duplicate",
        now=START + timedelta(minutes=6),
    )
    assert duplicate == result
    assert assignment_db.gradebook("learner-in-progress")[0]["score"] == 10


def test_three_attempts_then_twenty_four_hour_wait(
    assignment_environment,
) -> None:
    now = START
    for expected_number in (1, 2, 3):
        attempt = assignment_db.start_or_resume_attempt(
            "learner-in-progress", now=now
        )
        assert attempt["attempt_number"] == expected_number
        assignment_db.submit_attempt(
            "learner-in-progress",
            str(attempt["attempt_id"]),
            CORRECT,
            "Progress Learner",
            now=now + timedelta(minutes=1),
        )
        now += timedelta(minutes=2)

    with pytest.raises(ValueError, match="24 hours"):
        assignment_db.start_or_resume_attempt("learner-in-progress", now=now)

    next_attempt = assignment_db.start_or_resume_attempt(
        "learner-in-progress", now=now + timedelta(hours=25)
    )
    assert next_attempt["attempt_number"] == 4


def test_site_reset_clears_assignment_state_and_restores_note_identity(
    assignment_environment,
) -> None:
    first_note = assignment_db.save_note("learner-in-progress", "Before reset")
    assert first_note["note_id"] == 1
    assignment_db.start_or_resume_attempt("learner-in-progress", now=START)

    learning_db.reset()

    assert assignment_db.list_notes("learner-in-progress") == []
    assert assignment_db.gradebook("learner-in-progress") == []
    assert assignment_db.course_access("learner-in-progress")["enrolled"] is True
    second_note = assignment_db.save_note("learner-in-progress", "After reset")
    assert second_note["note_id"] == 1
