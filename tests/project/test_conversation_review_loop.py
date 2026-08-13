from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType

from jsonschema import Draft202012Validator, FormatChecker


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
TOOL_ROOT = REPOSITORY_ROOT / "tools" / "offline_clone"
PROMPT_ROOT = REPOSITORY_ROOT / "prompts" / "offline-clone"
SCHEMA_ROOT = REPOSITORY_ROOT / "websitebench" / "schemas"


def _load_script(name: str) -> ModuleType:
    path = TOOL_ROOT / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _review_record() -> dict[str, object]:
    digest = "a" * 64
    return {
        "schema_version": "clawbench.independent-agent-review.v1",
        "review_id": "example-r4-1",
        "site_id": "example-shop",
        "checkpoint": "R4-runtime-release",
        "round": 1,
        "packet": {
            "sha256": digest,
            "inputs": [
                {
                    "role": "source-contract",
                    "path": "packet/source-contract.json",
                    "sha256": digest,
                }
            ],
            "forbidden_inputs_absent": True,
        },
        "independence": {
            "task_id": "/root/review_example_r4_1",
            "model": "gpt-test",
            "fork_turns": "none",
            "prompt_sha256": digest,
            "conversation_visible": False,
            "concern_corpus_visible": False,
            "producer_summary_visible": False,
            "prior_findings_visible_before_blind_freeze": False,
            "filesystem_boundary": "sealed packet only",
            "paths_read": ["packet/source-contract.json"],
        },
        "runtime_identity": {
            "manifest_sha256": digest,
            "candidate_tree_sha256": digest,
            "commit_and_dirty_patch_sha256": digest,
            "url": "http://127.0.0.1:8123/",
            "process_identity": "pid:123",
            "process_started_at": "2026-07-26T00:00:00Z",
            "reset_seed": "review-seed",
            "bundle_sha256": None,
            "matches_packet": True,
        },
        "passes": {
            "blind_discovery": {
                "frozen_report_sha256": digest,
                "frozen_at": "2026-07-26T00:10:00Z",
                "surface_inventory": ["home/default/desktop/anonymous"],
                "denominator_audit": ["entrypoint-affordance"],
            },
            "directed_verification": {
                "performed": True,
                "disclosed_after_blind_freeze": True,
                "obligations": [],
            },
        },
        "coverage": {
            "p0_required": 1,
            "p0_executed": 1,
            "p0_coverage_complete": True,
            "denominators": [
                {
                    "id": "p0-journeys",
                    "required": 1,
                    "executed": 1,
                }
            ],
        },
        "findings": [],
        "decision": "accepted",
        "open_p0": 0,
        "open_p1": 0,
        "stale": False,
    }


def test_prompts_route_feedback_to_machine_verification() -> None:
    policy = (
        REPOSITORY_ROOT / "docs" / "source-evidence-access-policy.md"
    ).read_text(encoding="utf-8")
    curator = (PROMPT_ROOT / "conversation-curation.md").read_text(
        encoding="utf-8"
    )

    assert "configured" in policy
    assert "exact quotes" in curator
    assert not (PROMPT_ROOT / "human-fidelity-review.md").exists()


def test_build_prompt_binds_runtime_and_machine_evidence() -> None:
    build = (PROMPT_ROOT / "build.md").read_text(encoding="utf-8")

    assert "machine" in build
    assert "candidate/runtime identity" in build
    assert "full-local-model" in build
    assert "truthful-simulation" in build


def test_concern_corpus_schema_preserves_quote_provenance() -> None:
    schema = json.loads(
        (
            SCHEMA_ROOT / "conversation-concern-corpus.schema.json"
        ).read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(schema)
    quote = "A visible category must lead to the matching products."
    corpus = {
        "schema_version": "clawbench.conversation-concern-corpus.v1",
        "generated_at": "2026-07-26T00:00:00Z",
        "scope": "Example private clone feedback",
        "visibility": "maintainer-only",
        "sources": [
            {
                "archive_id": "example-archive",
                "thread_id": "019f9a36-3b74-7422-aec1-9da6586d7830",
                "parent_thread_ids": [],
                "snapshot_kind": "point-in-time",
                "authoritative_path": "rollout-example.jsonl",
                "sha256": "a" * 64,
            }
        ],
        "concerns": [
            {
                "id": "concern-example-destination",
                "source": {
                    "archive_id": "example-archive",
                    "thread_id": "019f9a36-3b74-7422-aec1-9da6586d7830",
                    "message_ordinal": 1,
                    "raw_jsonl_line": 2,
                    "timestamp": "2026-07-26T00:00:00Z",
                },
                "exact_user_quote": quote,
                "quote_sha256": hashlib.sha256(quote.encode()).hexdigest(),
                "derivation": {
                    "risk_class": "semantic-destination-mismatch",
                    "generalized_observation": (
                        "Entry semantics and destination inventory can diverge."
                    ),
                    "neutral_probe": (
                        "Census entries and compare labels with destinations."
                    ),
                    "earliest_checkpoint": "R2-frontend",
                    "required_evidence": ["browser trace"],
                    "machine_checkable": True,
                },
                "visibility": "maintainer-only",
            }
        ],
    }
    Draft202012Validator(
        schema,
        format_checker=FormatChecker(),
    ).validate(corpus)


def test_concern_validator_resolves_quote_at_raw_user_record(
    tmp_path: Path,
) -> None:
    archive_root = tmp_path / "archives"
    archive = archive_root / "example-archive"
    archive.mkdir(parents=True)
    quote = "The entry label and destination inventory must agree."
    raw_path = archive / "rollout-example.jsonl"
    raw_path.write_text(
        json.dumps(
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": quote}],
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (archive / "manifest.json").write_text(
        json.dumps(
            {
                "thread": {
                    "id": "019f9a36-3b74-7422-aec1-9da6586d7830"
                },
                "snapshot": {
                    "authoritative_file": raw_path.name,
                    "sha256": _sha256(raw_path),
                },
            }
        ),
        encoding="utf-8",
    )
    corpus = {
        "schema_version": "clawbench.conversation-concern-corpus.v1",
        "generated_at": "2026-07-26T00:00:00Z",
        "scope": "Example private clone feedback",
        "visibility": "maintainer-only",
        "sources": [
            {
                "archive_id": archive.name,
                "thread_id": "019f9a36-3b74-7422-aec1-9da6586d7830",
                "parent_thread_ids": [],
                "snapshot_kind": "point-in-time",
                "authoritative_path": f"{archive.name}/{raw_path.name}",
                "sha256": _sha256(raw_path),
            }
        ],
        "concerns": [
            {
                "id": "concern-example-raw-provenance",
                "source": {
                    "archive_id": archive.name,
                    "thread_id": "019f9a36-3b74-7422-aec1-9da6586d7830",
                    "message_ordinal": 1,
                    "raw_jsonl_line": 1,
                    "timestamp": None,
                },
                "exact_user_quote": quote,
                "quote_sha256": hashlib.sha256(quote.encode()).hexdigest(),
                "derivation": {
                    "risk_class": "semantic-destination-mismatch",
                    "generalized_observation": (
                        "Entry and destination semantics can diverge."
                    ),
                    "neutral_probe": "Compare all entry and destination pairs.",
                    "earliest_checkpoint": "R2-frontend",
                    "required_evidence": ["browser trace"],
                    "machine_checkable": True,
                },
                "visibility": "maintainer-only",
            }
        ],
    }
    corpus_path = tmp_path / "corpus.json"
    corpus_path.write_text(json.dumps(corpus), encoding="utf-8")
    validator = _load_script("validate_conversation_concerns")
    errors = validator.validate_corpus(
        corpus_path,
        SCHEMA_ROOT / "conversation-concern-corpus.schema.json",
        archive_root,
    )
    assert errors == []


def test_historical_review_schema_remains_readable() -> None:
    schema_path = SCHEMA_ROOT / "independent-agent-review.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    assert schema["title"]


def test_conversation_archive_validator_checks_raw_and_rendered_hashes(
    tmp_path: Path,
) -> None:
    raw_path = tmp_path / "rollout-example.jsonl"
    raw_path.write_bytes(
        b'{"type":"session_meta"}\n{"type":"response_item"}\n'
    )
    messages_path = tmp_path / "MESSAGES.md"
    messages_path.write_text("# Messages\n", encoding="utf-8")
    manifest_path = tmp_path / "manifest.json"
    manifest = {
        "schema_version": "codex.conversation.archive.v1",
        "thread": {"id": "019f9a36-3b74-7422-aec1-9da6586d7830"},
        "snapshot": {
            "kind": "point-in-time",
            "authoritative_file": raw_path.name,
            "bytes": raw_path.stat().st_size,
            "sha256": _sha256(raw_path),
            "jsonl_records": 2,
            "all_records_valid_json": True,
            "record_type_counts": {
                "session_meta": 1,
                "response_item": 1,
            },
        },
        "rendered_messages": {
            "bytes": messages_path.stat().st_size,
            "sha256": _sha256(messages_path),
        },
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    sums_path = tmp_path / "SHA256SUMS.txt"
    sums_path.write_text(
        "\n".join(
            [
                f"{_sha256(raw_path)}  {raw_path.name}",
                f"{_sha256(messages_path)}  MESSAGES.md",
                f"{_sha256(manifest_path)}  manifest.json",
                "",
            ]
        ),
        encoding="utf-8",
    )

    validator = _load_script("validate_conversation_archives")
    result = validator.validate_archive(tmp_path)
    assert result["status"] == "valid"

    messages_path.write_text("# altered\n", encoding="utf-8")
    try:
        validator.validate_archive(tmp_path)
    except validator.ArchiveValidationError as error:
        assert "MESSAGES.md" in str(error)
    else:
        raise AssertionError("checksum mismatch should fail")
