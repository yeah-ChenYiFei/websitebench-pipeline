"""Materialize one authoring instance into a self-contained Harbor bundle."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import time
from importlib.resources import files
from pathlib import Path
from typing import Any

import yaml

from .manifest import (
    HarborManifestError,
    LoadedInstance,
    load_instance,
    safe_regular_file,
    safe_tree_files,
)
from .policy import auth_checkout_policy_payload
from .bundle_v2 import validate_bundle


TEMPLATE_PACKAGE = "websitebench.harbor.templates"
COMMON_TEMPLATES = (
    "environment/Dockerfile",
    "tests/Dockerfile",
    "tests/test.sh",
    "tests/browser_lib.py",
    "tests/service_lib.py",
    "tests/compute_reward.py",
    "tests/merge_ctrf.py",
    "tests/verifier_contract.json",
)
V2_TEMPLATE_MAP = {
    "environment/Dockerfile.v2": "environment/Dockerfile",
    "tests/Dockerfile.v2": "tests/Dockerfile",
    "tests/test_v2.sh": "tests/test.sh",
    "tests/run_v2.py": "tests/run_v2.py",
}
V2_JUDGE_MODULES = (
    "judge_v2.py",
    "dsl_v2.py",
    "mailbox.py",
    "evaluate.py",
    "sandbox_v2.py",
)


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _copy_regular(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as reader, destination.open("xb") as writer:
        shutil.copyfileobj(reader, writer)
    shutil.copymode(source, destination)


def _copy_tree(
    source_root: Path,
    relative: str,
    destination: Path,
) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for source, child_relative in safe_tree_files(source_root, relative):
        _copy_regular(source, destination / child_relative)


def _copy_template(relative: str, destination: Path) -> None:
    resource = files(TEMPLATE_PACKAGE).joinpath(relative)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with resource.open("rb") as reader, destination.open("xb") as writer:
        shutil.copyfileobj(reader, writer)
    if relative.endswith(".sh"):
        destination.chmod(0o755)


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _task_toml(instance: LoadedInstance) -> str:
    metadata = instance.data["metadata"]
    budgets = instance.data["budgets"]
    tags = metadata.get("tags", [])
    keywords = ", ".join(_toml_string(item) for item in tags)
    task_name = f"websitebench/{instance.data['instance_id']}"
    return (
        'schema_version = "1.4"\n'
        'artifacts = ["/app/repo"]\n\n'
        "[task]\n"
        f"name = {_toml_string(task_name)}\n"
        'version = "1.0.0"\n'
        f"description = {_toml_string('Reconstruct the browser-only offline site ' + instance.site.data['display_name'])}\n"
        f"authors = [{{ name = {_toml_string(metadata['author_name'])}, "
        f"email = {_toml_string(metadata['author_email'])} }}]\n"
        f"keywords = [{keywords}]\n\n"
        "[metadata]\n"
        f"difficulty = {_toml_string(metadata['difficulty'])}\n"
        'category = "web-development"\n'
        'task_type = "fullstack-reconstruction"\n'
        'language = "web"\n\n'
        "[verifier]\n"
        'environment_mode = "separate"\n'
        f"timeout_sec = {float(budgets['verifier_timeout_sec']):.1f}\n\n"
        "[verifier.environment]\n"
        'network_mode = "no-network"\n'
        f"cpus = {budgets['cpus']}\n"
        f"memory_mb = {budgets['memory_mb']}\n"
        f"storage_mb = {budgets['storage_mb']}\n\n"
        "[agent]\n"
        f"timeout_sec = {float(budgets['agent_timeout_sec']):.1f}\n\n"
        "[environment]\n"
        'network_mode = "allowlist"\n'
        'allowed_hosts = ["reference"]\n'
        'os = "linux"\n'
        f"build_timeout_sec = {float(budgets['build_timeout_sec']):.1f}\n"
        f"cpus = {budgets['cpus']}\n"
        f"memory_mb = {budgets['memory_mb']}\n"
        f"storage_mb = {budgets['storage_mb']}\n"
    )


def _task_toml_v2(instance: LoadedInstance) -> str:
    metadata = instance.data["metadata"]
    budgets = instance.data["budgets"]
    tags = metadata.get("tags", [])
    keywords = ", ".join(_toml_string(item) for item in tags)
    task_name = f"websitebench/{instance.data['instance_id']}"
    mailbox = instance.site.data["mailbox"]
    agent_hosts = ["reference"] + (
        ["mailbox"]
        if mailbox["mode"] == "local-sidecar"
        else list(mailbox["external_allowlist"])
    )
    verifier_network = (
        'network_mode = "no-network"\n'
        if mailbox["mode"] == "local-sidecar"
        else 'network_mode = "allowlist"\n'
        + "allowed_hosts = ["
        + ", ".join(_toml_string(item) for item in mailbox["external_allowlist"])
        + "]\n"
    )
    return (
        'schema_version = "1.4"\n'
        'artifacts = ["/app/repo"]\n\n'
        "[task]\n"
        f"name = {_toml_string(task_name)}\n"
        'version = "2.0.0"\n'
        f"description = {_toml_string('Reconstruct the browser-only offline site ' + instance.site.data['display_name'])}\n"
        f"authors = [{{ name = {_toml_string(metadata['author_name'])}, "
        f"email = {_toml_string(metadata['author_email'])} }}]\n"
        f"keywords = [{keywords}]\n\n"
        "[metadata]\n"
        f"difficulty = {_toml_string(metadata['difficulty'])}\n"
        'category = "web-development"\n'
        'task_type = "fullstack-reconstruction"\n'
        'language = "web"\n\n'
        "[verifier]\n"
        'environment_mode = "separate"\n'
        f"timeout_sec = {float(budgets['verifier_timeout_sec']):.1f}\n\n"
        "[verifier.environment]\n" + verifier_network + f"cpus = {budgets['cpus']}\n"
        f"memory_mb = {budgets['memory_mb']}\n"
        f"storage_mb = {budgets['storage_mb']}\n\n"
        "[agent]\n"
        f"timeout_sec = {float(budgets['agent_timeout_sec']):.1f}\n\n"
        "[environment]\n"
        'network_mode = "allowlist"\n'
        "allowed_hosts = ["
        + ", ".join(_toml_string(item) for item in agent_hosts)
        + "]\n"
        'os = "linux"\n'
        f"build_timeout_sec = {float(budgets['build_timeout_sec']):.1f}\n"
        f"cpus = {budgets['cpus']}\n"
        f"memory_mb = {budgets['memory_mb']}\n"
        f"storage_mb = {budgets['storage_mb']}\n"
    )


def _classification(relative: str) -> str:
    if relative.startswith("environment/reference/"):
        return "reference-sidecar-only"
    if relative.startswith("environment/seed/"):
        return "agent-public"
    if relative.startswith("environment/"):
        return "build-control"
    if relative.startswith("solution/"):
        return "oracle-only"
    if relative.startswith("tests/") or relative.startswith("authoring/"):
        return "verifier-only"
    if relative in {"instruction.md", "task.toml"}:
        return "agent-public"
    return "bundle-metadata"


def _build_opencli_profile_guide(profile: dict[str, Any]) -> list[dict[str, str]]:
    guide: list[dict[str, str]] = []
    for step in profile.get("steps", []):
        if not isinstance(step, dict):
            continue
        guide.append(
            {
                "id": str(step.get("id", "")),
                "command": str(step.get("command", "")),
                "route": str(step.get("route", "")),
                "selector": str(step.get("selector", "")),
                "intent": str(step.get("intent", "")),
            }
        )
    return guide


def _format_opencli_markdown(profile_id: str, profile: dict[str, Any]) -> str:
    label = str(profile.get("label", profile_id))
    tier = str(profile.get("tier", "p0"))
    lines = [
        "# OpenCLI interaction profile",
        "",
        f"Profile: {label}",
        f"Tier: {tier}",
        "",
        "## Command sequence",
    ]
    for index, step in enumerate(profile.get("steps", []), start=1):
        if not isinstance(step, dict):
            continue
        intent = step.get("intent")
        route = step.get("route", "")
        command = step.get("command", "")
        selector = step.get("selector")
        line = f"{index}. `{command}` on `{route}`"
        if selector:
            line = line + f", selector `{selector}`"
        if intent:
            line = line + f" -> {intent}"
        lines.append(line)
    semantics = profile.get("local_semantics")
    if isinstance(semantics, list) and semantics:
        lines.append("")
        lines.append("## Local semantics checks")
        lines.extend(f"- {item}" for item in semantics if isinstance(item, str))
    failures = profile.get("failure_paths")
    if isinstance(failures, list) and failures:
        lines.append("")
        lines.append("## Failure paths")
        lines.extend(f"- {item}" for item in failures if isinstance(item, str))
    recoveries = profile.get("recovery_paths")
    if isinstance(recoveries, list) and recoveries:
        lines.append("")
        lines.append("## Recovery paths")
        lines.extend(f"- {item}" for item in recoveries if isinstance(item, str))
    lines.append("")
    lines.append(
        "Output should be sanitized. Do not persist credentials, session "
        "secrets, headers, raw request bodies, or unredacted assertion payloads."
    )
    return "\n".join(lines) + "\n"


def _write_opencli_artifacts(root: Path, instance: LoadedInstance) -> None:
    """Write the OpenCLI bundle artifacts for an instance.

    Only one condition is a legitimate no-op: the site declares no ``opencli``
    block at all. Every other malformed input is a materialization bug that used
    to return silently, producing a bundle quietly missing five files; those now
    raise instead.
    """

    site_opencli = instance.site.data.get("opencli")
    if not isinstance(site_opencli, dict):
        return

    def _fail(detail: str) -> None:
        raise HarborManifestError(
            "Harbor materialization failed:\n- instance.opencli: " + detail
        )

    profile_id = instance.data.get("opencli_profile")
    if not isinstance(profile_id, str):
        _fail("opencli_profile must be a string when site.opencli is configured")
    contract_relative = site_opencli.get("contract")
    if not isinstance(contract_relative, str):
        _fail("site.opencli.contract must be a relative path")

    try:
        payload = json.loads(
            safe_regular_file(instance.site.root, contract_relative).read_text(
                encoding="utf-8"
            )
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        _fail(f"site.opencli.contract is unreadable: {exc}")
    if not isinstance(payload, dict):
        _fail("site.opencli.contract must contain a JSON object")
    profiles = payload.get("profiles")
    if not isinstance(profiles, dict):
        _fail("site.opencli.contract.profiles must be an object")
    profile = profiles.get(profile_id)
    if not isinstance(profile, dict):
        _fail(f"site.opencli.contract has no profile {profile_id!r}")

    _write_json(
        root / "tests/opencli/interactions.json",
        {
            "schema_version": "websitebench.harbor.opencli.interactions.v1",
            "site_id": instance.site.data["site_id"],
            "instance_id": instance.data["instance_id"],
            "opencli_version": payload.get("opencli_version"),
            "profile_id": profile_id,
            "profile": profile,
            "network_requirements": site_opencli.get("network_requirements"),
        },
    )
    _write_json(
        root / "environment/seed/.websitebench/opencli-interactions-guide.json",
        {
            "schema_version": "websitebench.harbor.opencli.interactions.v1",
            "profile_id": profile_id,
            "label": profile.get("label"),
            "tier": profile.get("tier"),
            "guide": _build_opencli_profile_guide(profile),
            "local_semantics": profile.get("local_semantics", []),
            "failure_paths": profile.get("failure_paths", []),
            "recovery_paths": profile.get("recovery_paths", []),
        },
    )
    (root / "environment/seed/.websitebench/opencli-guide.md").write_text(
        _format_opencli_markdown(profile_id, profile),
        encoding="utf-8",
        newline="\n",
    )
    _write_json(
        root / "tests/opencli/interactions-runner.json",
        {
            "schema_version": "websitebench.harbor.opencli.interactions-runner.v1",
            "site_id": instance.site.data["site_id"],
            "instance_id": instance.data["instance_id"],
            "profile_id": profile_id,
            "contract": {
                "opencli_version": payload.get("opencli_version"),
                "schema_version": payload.get("schema_version"),
                "network": profile.get("network"),
            },
            "profile": profile,
            "fixtures": {
                "verifier_root": "/tests/fixtures/site",
                "contract_root": "/tests/opencli",
            },
            "commands": _build_opencli_profile_guide(profile),
            "failure_paths": profile.get("failure_paths", []),
            "recovery_paths": profile.get("recovery_paths", []),
            "result_binding": {
                "reference": "/run/verifier-final/opencli/reference.json",
                "candidate": "/run/verifier-final/opencli/candidate.json",
            },
        },
    )
    (root / "environment/seed/.websitebench/opencli-profile.txt").write_text(
        f"{profile_id}\n",
        encoding="utf-8",
        newline="\n",
    )


def _bundle_manifest(root: Path, instance: LoadedInstance) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        if relative == "bundle-manifest.json":
            continue
        payload = path.read_bytes()
        entries.append(
            {
                "path": relative,
                "bytes": len(payload),
                "visibility": _classification(relative),
            }
        )
    return {
        "schema_version": "websitebench.harbor.bundle.v1",
        "instance_id": instance.data["instance_id"],
        "site_id": instance.site.data["site_id"],
        "files": entries,
    }


def _bundle_manifest_v2(root: Path, instance: LoadedInstance) -> dict[str, Any]:
    manifest = _bundle_manifest(root, instance)
    manifest["schema_version"] = "websitebench.harbor.bundle.v2"
    manifest["judge"] = {
        "kind": "deterministic",
        "reward_source": "task_completion",
        "model_runtime": False,
        "formal_workers": 4,
        "candidate_tree": "read-only",
    }
    return manifest


def _required_nodes(instance: LoadedInstance) -> dict[str, Any]:
    groups = instance.data["tests"]
    return {
        "schema_version": "websitebench.harbor.required-nodes.v1",
        "exact_node_set": True,
        "groups": groups,
        "nodes": [node for group in groups.values() for node in group],
        "dimension_max_points": instance.site.data["scoring"]["dimensions"],
    }


def _runtime_contract(instance: LoadedInstance) -> dict[str, Any]:
    return {
        "schema_version": "websitebench.harbor.runtime-contract.v1",
        "site_id": instance.site.data["site_id"],
        "instance_id": instance.data["instance_id"],
        "runtime": instance.site.data["runtime"],
        "paths": {
            "candidate_root": "/app/repo",
            "reference_root": "/tests/reference",
            "output_root": "/run/verifier-final",
        },
        "rules": {
            "agent_reference_access": "browser-only",
            "agent_exploration_driver": "browser-use-cli",
            "formal_ui_driver": "playwright",
            "formal_api_checks": "direct-http",
            "reference_source_in_agent_image": False,
            "candidate_and_reference_reset_before_scenario": True,
            "verifier_launches_fresh_reference_and_candidate": True,
            "live_reference_and_untrusted_candidate_must_not_overlap": True,
        },
    }


def _agent_contract(instance: LoadedInstance) -> dict[str, Any]:
    runtime = instance.site.data["runtime"]
    return {
        "schema_version": "websitebench.harbor.agent-browser-contract.v1",
        "site_id": instance.site.data["site_id"],
        "instance_id": instance.data["instance_id"],
        "reference_access": "browser-only",
        "exploration_driver": "browser-use-cli",
        "reference_url_env": runtime["reference_url_env"],
        "candidate_url_env": runtime["candidate_url_env"],
        "candidate_port": runtime["candidate_port"],
        "candidate_ready_path": runtime["ready_path"],
        "candidate_start": "/app/repo/run.sh",
        "candidate_data_dir_env": "WEBSITEBENCH_DATA_DIR",
        "rules": [
            "Do not attempt to locate or read the reference implementation.",
            "Use Browser Use CLI to inspect behavior and rendered states.",
            "Implement the candidate in /app/repo and self-check through the browser.",
            "Formal scoring is performed by trusted Playwright and direct HTTP checks.",
        ],
    }


def _agent_contract_v2(instance: LoadedInstance) -> dict[str, Any]:
    runtime = instance.site.data["runtime"]
    mailbox = instance.site.data["mailbox"]
    return {
        "schema_version": "websitebench.harbor.agent-browser-contract.v2",
        "site_id": instance.site.data["site_id"],
        "instance_id": instance.data["instance_id"],
        "reference_access": "browser-only",
        "exploration_driver": "browser-use-cli",
        "reference_url_env": runtime["reference_url_env"],
        "candidate_url_env": runtime["candidate_url_env"],
        "candidate_port": runtime["candidate_port"],
        "candidate_ready_path": runtime["ready_path"],
        "candidate_start": "/app/repo/deploy.sh",
        "candidate_data_dir_env": "WEBSITEBENCH_DATA_DIR",
        "mailbox": {
            "mode": mailbox["mode"],
            "namespace_env": mailbox["namespace_env"],
            "gateway_url_env": "WEBSITEBENCH_MAILBOX_URL",
            "capability_env": "WEBSITEBENCH_MAILBOX_CAPABILITY",
            "smtp_namespace_header": "X-WebsiteBench-Namespace",
            "smtp_capability_header": "X-WebsiteBench-Capability",
        },
        "delivery": {
            "artifact": "/app/repo",
            "entrypoint": "deploy.sh",
            "health_path": "/healthz",
            "runtime_writes": "WEBSITEBENCH_DATA_DIR_ONLY",
        },
        "rules": [
            "Do not attempt to locate or read hidden suites, frozen reference facts, or verifier outputs.",
            "Use Browser Use CLI to inspect the configured browser-only reference.",
            "Keep every runtime dependency or built artifact under /app/repo.",
            "deploy.sh must not download dependencies or contact unauthorized networks.",
        ],
    }


def _runtime_contract_v2(instance: LoadedInstance) -> dict[str, Any]:
    return {
        "schema_version": "websitebench.harbor.runtime-contract.v2",
        "site_id": instance.site.data["site_id"],
        "instance_id": instance.data["instance_id"],
        "entrypoint": "/app/repo/deploy.sh",
        "ready_path": instance.site.data["runtime"]["ready_path"],
        "candidate_data_dir_env": "WEBSITEBENCH_DATA_DIR",
        "candidate_tree": "read-only",
        "workers": 4,
        "worker_isolation": [
            "port",
            "data_dir",
            "mailbox_namespace",
            "browser_context",
            "os_uid",
        ],
        "network": {
            "judge": "loopback-only",
            "mailbox_mode": instance.site.data["mailbox"]["mode"],
            "mailbox_external_allowlist": instance.site.data["mailbox"][
                "external_allowlist"
            ],
        },
        "scoring": {
            "reward_source": "task_completion",
            "visual_report_only": True,
            "cicd_report_only": True,
        },
    }


def _evaluation_contract_v2(instance: LoadedInstance) -> dict[str, Any]:
    observations_path = safe_regular_file(
        instance.root, instance.data["reference_observations"]["artifact"]
    )
    observations = json.loads(observations_path.read_text(encoding="utf-8"))
    return {
        "schema_version": "websitebench.harbor.evaluation-contract.v2",
        "workers": 4,
        "ready_path": instance.site.data["runtime"]["ready_path"],
        "browser": instance.site.data["runtime"]["browser"],
        "reference_render_environment": observations["render_environment"],
        "mailbox": instance.site.data["mailbox"],
        "budgets": {
            "memory_mb": instance.data["budgets"]["memory_mb"],
            "storage_mb": instance.data["budgets"]["storage_mb"],
            "cpus": instance.data["budgets"]["cpus"],
            "startup_timeout_sec": 30,
        },
        "paths": {
            "task_suite": "/tests/fixtures/task-suite.json",
            "visual_suite": "/tests/fixtures/visual-suite.json",
            "cicd_suite": "/tests/fixtures/cicd-suite.json",
            "reference_observations": "/tests/fixtures/reference-observations.json",
            "fixtures": "/tests/fixtures",
            "network_policy": "/tests/network-policy.json",
        },
        "output": "/run/verifier-final",
        "candidate": "/app/repo",
    }


def _docker_compose(instance: LoadedInstance) -> dict[str, Any]:
    runtime = instance.site.data["runtime"]
    return {
        "services": {
            "main": {
                "depends_on": {
                    "reference": {
                        "condition": "service_healthy",
                    }
                },
                "environment": {
                    runtime["reference_url_env"]: (
                        f"http://reference:{runtime['reference_port']}"
                    ),
                    runtime["candidate_url_env"]: (
                        f"http://127.0.0.1:{runtime['candidate_port']}"
                    ),
                },
            },
            "reference": {
                "build": {
                    "context": "./reference",
                },
                "environment": {
                    "PORT": str(runtime["reference_port"]),
                },
            },
        }
    }


def _docker_compose_v2(instance: LoadedInstance) -> dict[str, Any]:
    value = _docker_compose(instance)
    mailbox = instance.site.data["mailbox"]
    if mailbox["mode"] == "local-sidecar":
        agent_capability = hashlib.sha256(
            f"agent-mailbox:{instance.data['instance_id']}".encode("utf-8")
        ).hexdigest()
        main = value["services"]["main"]
        main["depends_on"]["mailbox"] = {"condition": "service_healthy"}
        main["environment"].update(
            {
                "WEBSITEBENCH_MAILBOX_URL": "http://mailbox:8025",
                "WEBSITEBENCH_SMTP_HOST": "mailbox",
                "WEBSITEBENCH_SMTP_PORT": "1025",
                "WEBSITEBENCH_MAILBOX_NAMESPACE": "agent",
                "WEBSITEBENCH_MAILBOX_CAPABILITY": agent_capability,
            }
        )
        value["services"]["reference"]["environment"].update(
            {
                "WEBSITEBENCH_SMTP_HOST": "mailbox",
                "WEBSITEBENCH_SMTP_PORT": "1025",
                "WEBSITEBENCH_MAILBOX_NAMESPACE": "agent",
                "WEBSITEBENCH_MAILBOX_CAPABILITY": agent_capability,
            }
        )
        value["services"]["mailbox"] = {
            "build": {"context": "./mailbox"},
            "environment": {
                "PYTHONDONTWRITEBYTECODE": "1",
                "WEBSITEBENCH_MAILBOX_INITIAL_NAMESPACE": "agent",
                "WEBSITEBENCH_MAILBOX_INITIAL_CAPABILITY": agent_capability,
            },
        }
    else:
        value["services"]["main"]["environment"].update(
            {
                "WEBSITEBENCH_MAILBOX_URL": "${WEBSITEBENCH_MAILBOX_URL:?required}",
                "WEBSITEBENCH_MAILBOX_CREDENTIAL": (
                    "${WEBSITEBENCH_MAILBOX_CREDENTIAL:?required}"
                ),
                "WEBSITEBENCH_MAILBOX_ALLOWLIST": ",".join(
                    mailbox["external_allowlist"]
                ),
                "WEBSITEBENCH_MAILBOX_NAMESPACE": "agent",
            }
        )
    return value


def _populate(root: Path, instance: LoadedInstance) -> None:
    for relative in COMMON_TEMPLATES:
        _copy_template(relative, root / relative)
    if instance.auth_checkout_policy_required:
        _copy_template(
            "tests/platform_auth_checkout_gate.py",
            root / "tests/platform_auth_checkout_gate.py",
        )

    site_paths = instance.site.data["paths"]
    instance_paths = instance.data["paths"]
    _copy_tree(
        instance.site.root,
        site_paths["public"],
        root / "environment/seed/.websitebench/site",
    )
    _copy_tree(
        instance.root,
        instance_paths["public"],
        root / "environment/seed",
    )
    _copy_tree(
        instance.site.root,
        site_paths["reference"],
        root / "environment/reference",
    )
    _copy_tree(
        instance.site.root,
        site_paths["reference"],
        root / "tests/reference",
    )
    (root / "environment/docker-compose.yaml").write_text(
        yaml.safe_dump(_docker_compose(instance), sort_keys=False),
        encoding="utf-8",
        newline="\n",
    )
    _copy_tree(instance.site.root, site_paths["verifier"], root / "tests/site")
    _copy_tree(instance.root, instance_paths["verifier"], root / "tests/instance")
    _copy_tree(
        instance.site.root,
        site_paths["hidden_fixtures"],
        root / "tests/fixtures/site",
    )
    _copy_tree(
        instance.root,
        instance_paths["hidden_fixtures"],
        root / "tests/fixtures/instance",
    )
    oracle = site_paths.get("oracle")
    if oracle:
        _copy_tree(instance.site.root, oracle, root / "solution/site")
    _copy_regular(
        safe_regular_file(instance.root, instance_paths["oracle_solution"]),
        root / "solution/solve.sh",
    )
    (root / "solution/solve.sh").chmod(0o755)

    _copy_regular(
        safe_regular_file(instance.root, instance_paths["instruction"]),
        root / "instruction.md",
    )
    (root / "task.toml").write_text(
        _task_toml(instance), encoding="utf-8", newline="\n"
    )
    _write_json(root / "tests/required-nodes.json", _required_nodes(instance))
    if instance.auth_checkout_policy_required:
        _write_json(
            root / "tests/platform-auth-checkout-policy.json",
            auth_checkout_policy_payload(),
        )
    _write_json(root / "tests/runtime-contract.json", _runtime_contract(instance))
    _write_json(
        root / "environment/seed/.websitebench/browser-contract.json",
        _agent_contract(instance),
    )
    if instance.auth_checkout_policy_required:
        _write_json(
            root / "environment/seed/.websitebench/auth-checkout-policy.json",
            auth_checkout_policy_payload(),
        )
    _write_opencli_artifacts(root, instance)
    _write_json(root / "authoring/site.normalized.json", instance.site.data)
    _write_json(root / "authoring/instance.normalized.json", instance.data)

    _write_json(
        root / "bundle-manifest.json",
        _bundle_manifest(root, instance),
    )


def _copy_v2_judge_package(root: Path) -> None:
    package = root / "tests/websitebench/harbor"
    package.mkdir(parents=True, exist_ok=True)
    (root / "tests/websitebench/__init__.py").write_text(
        '"""Private verifier package."""\n', encoding="utf-8", newline="\n"
    )
    (package / "__init__.py").write_text(
        '"""Deterministic Harbor v2 verifier."""\n', encoding="utf-8", newline="\n"
    )
    source_root = Path(__file__).resolve().parent
    for filename in V2_JUDGE_MODULES:
        _copy_regular(source_root / filename, package / filename)


def _populate_v2(root: Path, instance: LoadedInstance) -> None:
    if instance.data["reference_observations"]["status"] != "captured":
        raise HarborManifestError(
            [
                "instance.reference_observations.status: v2 bundles cannot be "
                "published until capture-reference completes every reference task"
            ]
        )
    for source, destination in V2_TEMPLATE_MAP.items():
        _copy_template(source, root / destination)
    _copy_v2_judge_package(root)

    site_paths = instance.site.data["paths"]
    instance_paths = instance.data["paths"]
    _copy_tree(
        instance.site.root,
        site_paths["public"],
        root / "environment/seed/.websitebench/site",
    )
    _copy_tree(instance.root, instance_paths["public"], root / "environment/seed")
    _copy_tree(
        instance.site.root,
        site_paths["reference"],
        root / "environment/reference",
    )
    (root / "environment/docker-compose.yaml").write_text(
        yaml.safe_dump(_docker_compose_v2(instance), sort_keys=False),
        encoding="utf-8",
        newline="\n",
    )
    if instance.site.data["mailbox"]["mode"] == "local-sidecar":
        mailbox_root = root / "environment/mailbox"
        mailbox_root.mkdir(parents=True, exist_ok=True)
        _copy_regular(
            Path(__file__).resolve().parent / "mailbox.py",
            mailbox_root / "mailbox.py",
        )
        (mailbox_root / "Dockerfile").write_text(
            "FROM python:3.12-slim\n"
            "WORKDIR /srv/mailbox\n"
            "COPY mailbox.py .\n"
            "HEALTHCHECK --interval=2s --timeout=2s --retries=30 "
            'CMD python -c "import urllib.request; '
            "urllib.request.urlopen('http://127.0.0.1:8025/healthz', timeout=1)\"\n"
            'CMD ["python", "mailbox.py", "--smtp-port", "1025", "--http-port", "8025", '
            '"--bind-host", "0.0.0.0"]\n',
            encoding="utf-8",
            newline="\n",
        )
    _copy_tree(
        instance.site.root,
        site_paths["verifier"],
        root / "tests/site",
    )
    _copy_tree(instance.root, instance_paths["verifier"], root / "tests/instance")
    _copy_tree(
        instance.site.root,
        site_paths["hidden_fixtures"],
        root / "tests/fixtures/site",
    )
    _copy_tree(
        instance.root,
        instance_paths["hidden_fixtures"],
        root / "tests/fixtures",
    )
    oracle = site_paths.get("oracle")
    if oracle:
        _copy_tree(instance.site.root, oracle, root / "solution/site")
    _copy_regular(
        safe_regular_file(instance.root, instance_paths["oracle_solution"]),
        root / "solution/solve.sh",
    )
    (root / "solution/solve.sh").chmod(0o755)
    _copy_regular(
        safe_regular_file(instance.root, instance_paths["instruction"]),
        root / "instruction.md",
    )
    (root / "task.toml").write_text(
        _task_toml_v2(instance), encoding="utf-8", newline="\n"
    )
    _write_json(root / "tests/runtime-contract.json", _runtime_contract_v2(instance))
    _write_json(
        root / "tests/evaluation-contract.json", _evaluation_contract_v2(instance)
    )
    _write_json(
        root / "tests/judge-dependencies.json",
        {
            "schema_version": "websitebench.harbor.judge-dependencies.v1",
            "runtime": [
                "python==3.12.11",
                "greenlet==3.5.4",
                "imageio==2.37.4",
                "iniconfig==2.3.0",
                "lazy-loader==0.5",
                "networkx==3.6.1",
                "numpy==2.5.1",
                "packaging==26.2",
                "pillow==12.3.0",
                "playwright==1.61.0",
                "pluggy==1.6.0",
                "pyee==13.0.1",
                "pygments==2.20.0",
                "pytest==9.1.1",
                "scikit-image==0.26.0",
                "scipy==1.18.0",
                "tifffile==2026.7.14",
                "typing-extensions==4.16.0",
            ],
            "font_profile": "websitebench-linux-fonts-v1",
            "model_sdks": [],
            "model_credentials": [],
            "verdict_sources": ["comparator", "rgb_ssim", "trusted_check_exit_status"],
        },
    )
    _write_json(
        root / "tests/network-policy.json",
        {
            "schema_version": "websitebench.harbor.judge-network-policy.v1",
            "default": "deny",
            "loopback": True,
            "public_internet": False,
            "model_services": False,
            "mailbox_external_allowlist": instance.site.data["mailbox"][
                "external_allowlist"
            ],
        },
    )
    _write_json(
        root / "tests/calibration-contract.json",
        {
            "schema_version": "websitebench.harbor.calibration-contract.v2",
            "thresholds": instance.data["calibration"],
            "runs": ["nop", "oracle-first", "oracle-second"],
            "oracle_solve_timeout_sec": instance.data["budgets"]["build_timeout_sec"],
            "repeat_projection": "discrete-verdicts-and-scores",
        },
    )
    _write_json(
        root / "environment/seed/.websitebench/browser-contract.json",
        _agent_contract_v2(instance),
    )
    _write_opencli_artifacts(root, instance)
    _write_json(root / "authoring/site.normalized.json", instance.site.data)
    _write_json(root / "authoring/instance.normalized.json", instance.data)
    _write_json(root / "bundle-manifest.json", _bundle_manifest_v2(root, instance))
    validate_bundle(root)


def materialize_instance(
    instance_path: Path | str,
    destination: Path | str,
    *,
    corpus_root: Path | None = None,
    allow_legacy_v1: bool = False,
) -> Path:
    """Create one bundle and never overwrite an existing destination.

    POSIX and ordinary Windows filesystems publish the completed temporary tree
    with one atomic rename. Some Windows filter drivers permanently reject that
    rename for large freshly populated trees; in that case the destination is
    copied transactionally and removed again if publication fails.
    """

    instance = load_instance(
        instance_path,
        corpus_root=corpus_root,
        allow_legacy_v1=allow_legacy_v1,
    )
    output = Path(destination).resolve()
    if output.exists():
        raise FileExistsError(f"destination already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{output.name}.", dir=str(output.parent))
    ).resolve()
    try:
        if instance.data.get("schema_version") == "websitebench.harbor.instance.v2":
            _populate_v2(temporary, instance)
        else:
            _populate(temporary, instance)
        # Windows indexers and antivirus scanners can briefly hold one of the
        # freshly copied files open, which makes an otherwise valid directory
        # rename fail with WinError 5. Retrying preserves the atomic publish
        # contract without falling back to a partially visible copy.
        for attempt in range(40):
            try:
                os.replace(temporary, output)
                break
            except PermissionError:
                if os.name != "nt":
                    raise
                if attempt == 39:
                    try:
                        shutil.copytree(temporary, output)
                    except BaseException:
                        shutil.rmtree(output, ignore_errors=True)
                        raise
                    shutil.rmtree(temporary)
                    break
                time.sleep(0.25)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return output
