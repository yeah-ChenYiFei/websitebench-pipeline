from __future__ import annotations

import pytest

import enrolled_course


def test_enrolled_course_identity_and_observed_navigation_are_stable() -> None:
    assert enrolled_course.COURSE_ID == "neural-networks-deep-learning"
    assert enrolled_course.ASSIGNMENT_ID == "3KFZW"
    assert enrolled_course.PROGRAM["title"] == "Deep Learning"
    assert enrolled_course.PROGRAM["course_titles"] == (
        "Neural Networks and Deep Learning",
        "Improving Deep Neural Networks: Hyperparameter Tuning, Regularization and Optimization",
        "Structuring Machine Learning Projects",
        "Convolutional Neural Networks",
        "Sequence Models",
    )
    assert enrolled_course.COURSE["provider"] == "DeepLearning.AI"
    assert enrolled_course.COURSE["position"] == "Course 1 of 5"
    assert tuple(module["label"] for module in enrolled_course.MODULES) == (
        "Week 1",
        "Week 2",
        "Week 3",
        "Week 4",
    )


def test_assignment_has_all_observed_questions_and_local_assets_in_order() -> None:
    questions = enrolled_course.QUESTIONS
    assert len(questions) == 10
    assert sum(int(question["points"]) for question in questions) == 10
    assert enrolled_course.ATTEMPT_RULES == {
        "duration_minutes": 50,
        "submissions_per_attempt": 1,
        "attempts_remaining_after_timeout": 2,
        "wait_after_attempts_hours": 24,
        "auto_submit_on_timeout": True,
        "legal_name_required": True,
    }
    assert questions[0]["prompt"] == (
        'Which of the following best describes the role of AI in the expression '
        '"an AI-powered society"?'
    )
    assert questions[0]["options"][0] == (
        "AI is an essential ingredient in realizing tasks, in industry and in personal life."
    )
    assert questions[9]["prompt"] == (
        "Assuming the trends described in the figure are accurate. Which of the "
        "following statements are true? Choose all that apply."
    )
    image_paths = [
        str(question.get("image"))
        for question in questions
        if question.get("image")
    ] + [
        str(option["image"])
        for question in questions
        for option in question["options"]
        if isinstance(option, dict)
    ]
    assert image_paths == [
        "/static/enrolled/assignment/q3-image-1.png",
        "/static/enrolled/assignment/q9-image-1.png",
        "/static/enrolled/assignment/q10-image-1.png",
        "/static/enrolled/assignment/q5-image-1.png",
        "/static/enrolled/assignment/q5-image-2.png",
        "/static/enrolled/assignment/q5-image-3.png",
        "/static/enrolled/assignment/q5-image-4.png",
    ]


def test_answer_validation_normalizes_real_controls_and_rejects_forgery() -> None:
    assert enrolled_course.validate_answers(
        {1: [0], 2: [1, 0, 1], 5: [2]}, require_complete=False
    ) == {1: (0,), 2: (0, 1), 5: (2,)}

    with pytest.raises(ValueError, match="Unknown question"):
        enrolled_course.validate_answers({11: [0]}, require_complete=False)
    with pytest.raises(ValueError, match="Invalid option"):
        enrolled_course.validate_answers({1: [9]}, require_complete=False)
    with pytest.raises(ValueError, match="one answer"):
        enrolled_course.validate_answers({1: [0, 1]}, require_complete=False)
    with pytest.raises(ValueError, match="Answer every question"):
        enrolled_course.validate_answers({1: [0]}, require_complete=True)


def test_server_scorer_returns_local_provenance_and_literal_points() -> None:
    answers = {
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
    scored = enrolled_course.score_answers(answers)
    assert len(scored) == 10
    assert sum(int(item["points_awarded"]) for item in scored) == 10
    assert all(item["correct"] is True for item in scored)
    assert enrolled_course.ANSWER_KEY_PROVENANCE == "clone-local-course-knowledge-derived"

