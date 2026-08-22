from __future__ import annotations

import importlib
import sqlite3
from collections import Counter


def _catalog_module():
    return importlib.import_module("catalog")


def test_catalog_has_forty_plus_records_and_complete_deep_learning_series() -> None:
    records = _catalog_module().load_catalog_seed()

    assert len(records) >= 40
    deep_learning_ids = {
        record["id"]
        for record in records
        if record.get("id") == "deep-learning-specialization"
        or record.get("parent_specialization_id") == "deep-learning-specialization"
    }
    assert deep_learning_ids == {
        "deep-learning-specialization",
        "neural-networks-deep-learning",
        "improving-deep-neural-networks",
        "structuring-machine-learning-projects",
        "convolutional-neural-networks",
        "sequence-models",
    }
    assert sum(record["type"] == "specialization" for record in records) >= 1
    assert (
        sum(
            record.get("parent_specialization_id")
            == "deep-learning-specialization"
            for record in records
        )
        == 5
    )


def test_catalog_covers_every_browse_subject_with_three_or_more_matches() -> None:
    records = _catalog_module().load_catalog_seed()

    subjects = Counter(record["subject"] for record in records)
    for subject in (
        "Arts and Humanities", "Business", "Computer Science", "Data Science",
        "Health", "Information Technology", "Language Learning", "Math and Logic",
        "Personal Development", "Physical Science and Engineering", "Social Sciences",
    ):
        assert subjects[subject] >= 3, subject


def test_every_catalog_record_has_complete_detail_and_evidence_fields() -> None:
    records = _catalog_module().load_catalog_seed()
    required_fields = {
        "id",
        "title",
        "type",
        "subject",
        "level",
        "topic",
        "duration",
        "rating",
        "language",
        "schedule",
        "provider",
        "instructors",
        "prerequisites",
        "reviews_summary",
        "pricing",
        "enrollment_tracks",
        "syllabus",
        "source_evidence_classification",
    }
    classifications = {
        "directly-observed",
        "structural-only",
        "inferred-architecture",
        "truthful-simulation",
    }

    for record in records:
        assert required_fields <= record.keys(), record["id"]
        assert all(record[field] not in (None, "", []) for field in required_fields)
        assert record["type"] in {"course", "specialization", "professional-certificate"}
        assert record["level"] in {"Beginner", "Intermediate", "Advanced", "Mixed"}
        assert isinstance(record["rating"], (int, float))
        assert 0 < record["rating"] <= 5
        assert isinstance(record["instructors"], list)
        assert isinstance(record["enrollment_tracks"], list)
        assert isinstance(record["syllabus"], list)
        assert record["source_evidence_classification"] in classifications


def test_catalog_reset_replaces_mutations_and_is_deterministic() -> None:
    catalog = _catalog_module()
    connection = sqlite3.connect(":memory:")

    catalog.reset_catalog(connection)
    connection.execute(
        "UPDATE coursera_catalog SET title = ? WHERE id = ?",
        ("Poisoned title", "deep-learning-specialization"),
    )
    connection.execute(
        "INSERT INTO coursera_catalog (id, title, record_json) VALUES (?, ?, ?)",
        ("rogue-record", "Rogue", "{}"),
    )
    connection.commit()

    catalog.reset_catalog(connection)
    first_reset = connection.execute(
        "SELECT id, title, record_json FROM coursera_catalog ORDER BY id"
    ).fetchall()
    catalog.reset_catalog(connection)
    second_reset = connection.execute(
        "SELECT id, title, record_json FROM coursera_catalog ORDER BY id"
    ).fetchall()

    assert first_reset == second_reset
    assert len(first_reset) >= 40
    assert first_reset[0][0] == "academic-english"
    assert first_reset[-1][0] == "world-history-perspectives"
    assert (
        connection.execute(
            "SELECT title FROM coursera_catalog WHERE id = ?",
            ("deep-learning-specialization",),
        ).fetchone()[0]
        == "Deep Learning Specialization"
    )
    assert (
        connection.execute(
            "SELECT COUNT(*) FROM coursera_catalog WHERE id = 'rogue-record'"
        ).fetchone()[0]
        == 0
    )
