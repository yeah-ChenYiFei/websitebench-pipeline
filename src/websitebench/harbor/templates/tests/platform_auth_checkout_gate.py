#!/usr/bin/env python3
"""Platform-owned semantic enforcement for mandatory auth/checkout nodes."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any


POLICY_SCHEMA = "websitebench.harbor.auth-checkout-policy.v1"


def _json(path: Path, *, optional: bool = False) -> dict[str, Any]:
    if optional and not path.is_file():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def _runtime(root: Path) -> tuple[dict[str, Any], str]:
    raw = (root / "backend" / "runtime.json").read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("backend/runtime.json must contain an object")
    return value, hashlib.sha256(raw).hexdigest()


def _status(value: Any, allowed: set[int]) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value in allowed


def _replace_mandatory_results(
    report: dict[str, Any],
    checks: dict[str, tuple[bool, list[str]]],
) -> dict[str, Any]:
    result = copy.deepcopy(report)
    tests = result["results"]["tests"]
    by_name = {test["name"]: test for test in tests}
    for node, (platform_passed, failures) in checks.items():
        test = by_name[node]
        site_passed = test.get("status") == "passed"
        passed = platform_passed and site_passed
        test["status"] = "passed" if passed else "failed"
        extra = test.get("extra")
        if not isinstance(extra, dict):
            extra = {}
            test["extra"] = extra
        extra.pop("clawbench_score", None)
        extra["websitebench_platform_enforced"] = True
        if not passed:
            messages = list(failures)
            if not site_passed:
                messages.insert(0, "site verifier did not pass this node")
            test["message"] = "; ".join(messages)
        else:
            test.pop("message", None)
    statuses = [test.get("status") for test in tests]
    result["results"]["summary"] = {
        "tests": len(tests),
        "passed": statuses.count("passed"),
        "failed": statuses.count("failed"),
        "skipped": statuses.count("skipped"),
    }
    result["results"]["tool"] = {
        "name": "websitebench-harbor-platform-auth-checkout-gate"
    }
    return result


def enforce(
    *,
    policy_path: Path,
    required_path: Path,
    site_report_path: Path,
    candidate_facts_path: Path,
    reference_facts_path: Path,
    candidate_root: Path,
    reference_root: Path,
    output_path: Path,
    evidence_path: Path,
) -> None:
    policy = _json(policy_path)
    required = _json(required_path)
    report = _json(site_report_path)
    if policy.get("schema_version") != POLICY_SCHEMA:
        raise ValueError("unsupported platform auth/checkout policy")
    policy_nodes = {
        node for nodes in policy.get("required_nodes", {}).values() for node in nodes
    }
    required_nodes = set(required.get("nodes", []))
    if not policy_nodes or not policy_nodes.issubset(required_nodes):
        raise ValueError("required nodes do not contain the platform policy")
    tests = report.get("results", {}).get("tests")
    if not isinstance(tests, list):
        raise ValueError("site CTRF has no results.tests array")
    names = [test.get("name") for test in tests if isinstance(test, dict)]
    if set(names) != required_nodes or len(names) != len(set(names)):
        raise ValueError("site CTRF does not have the exact required node set")

    candidate = _json(candidate_facts_path, optional=True)
    reference = _json(reference_facts_path, optional=True)
    facts = candidate.get("auth_checkout", {})
    reference_auth = reference.get("auth_checkout", {})
    browser = candidate.get("browser", {})
    if not isinstance(facts, dict):
        facts = {}
    if not isinstance(reference_auth, dict):
        reference_auth = {}
    if not isinstance(browser, dict):
        browser = {}

    runtime_failures: list[str] = []
    candidate_runtime: dict[str, Any] = {}
    candidate_runtime_sha256 = ""
    try:
        reference_runtime, reference_runtime_sha256 = _runtime(reference_root)
        candidate_runtime, candidate_runtime_sha256 = _runtime(candidate_root)
        if candidate_runtime != reference_runtime:
            runtime_failures.append(
                "candidate backend/runtime.json differs from reference"
            )
        if facts.get("backend_runtime_sha256") != candidate_runtime_sha256:
            runtime_failures.append("candidate service runtime hash is not file-bound")
        if reference_auth.get("backend_runtime_sha256") != reference_runtime_sha256:
            runtime_failures.append("reference service runtime hash is not file-bound")
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        runtime_failures.append(f"runtime contract unreadable: {type(exc).__name__}")

    try:
        site_id = candidate_runtime["site"]["id"]
        profile = candidate_runtime["deployment"]["profiles"]["offline-harbor"]
        if facts.get("site_id") != site_id:
            runtime_failures.append("service site_id differs from runtime contract")
        if profile["mail_adapter"] != "local-outbox":
            runtime_failures.append("offline mail adapter is not local-outbox")
        if profile["payment_adapter"] != "local-sandbox":
            runtime_failures.append("offline payment adapter is not local-sandbox")
        if facts.get("mail_delivery") != "LOCAL_ONLY":
            runtime_failures.append("service mail mode is not LOCAL_ONLY")
        if facts.get("payment_adapter") != profile["payment_adapter"]:
            runtime_failures.append(
                "service payment adapter differs from runtime contract"
            )
    except (KeyError, TypeError):
        runtime_failures.append("runtime contract has no offline-harbor profile")

    database_isolated = (
        isinstance(facts.get("database_identity"), str)
        and len(facts["database_identity"]) == 64
        and isinstance(reference_auth.get("database_identity"), str)
        and facts["database_identity"] != reference_auth["database_identity"]
    )
    profile_ok = (
        not runtime_failures
        and database_isolated
        and facts.get("plaintext_registration_codes") == 0
        and facts.get("outbox_status") == 200
        and facts.get("outbox_local_only") is True
        and facts.get("outbox_without_token_status") in {403, 404}
        and facts.get("outbox_wrong_token_status") in {403, 404}
        and facts.get("public_outbox_status") in {403, 404}
    )

    auth_happy = (
        _status(facts.get("registration_status"), {302, 303})
        and _status(facts.get("verification_status"), {302, 303})
        and _status(facts.get("logout_status"), {302, 303})
        and _status(facts.get("login_status"), {302, 303})
    )
    account_progression = (
        isinstance(facts.get("expired_accounts"), int)
        and isinstance(facts.get("replay_accounts"), int)
        and isinstance(facts.get("accounts"), int)
        and facts["replay_accounts"] == facts["expired_accounts"] + 1
        and facts["accounts"] == facts["replay_accounts"] + 1
    )
    auth_negative = (
        _status(facts.get("wrong_password_status"), {400, 401})
        and _status(facts.get("duplicate_status"), {400, 409})
        and _status(facts.get("expired_verification_status"), {400, 409, 410, 422})
        and _status(facts.get("replay_status"), {400, 409, 410, 422})
        and _status(facts.get("post_logout_protected_status"), {302, 303, 401, 403})
        and _status(facts.get("wrong_password_protected_status"), {302, 303, 401, 403})
        and account_progression
    )
    payment_success = (
        facts.get("order_detail_status") == 200
        and facts.get("order_detail_has_item") is True
    ) or (
        facts.get("confirmation_status") == 200
        and facts.get("confirmation_confirmed") is True
    )
    payment_flow = (
        facts.get("checkout_status") == 200
        and _status(facts.get("decline_status"), {302, 303})
        and facts.get("decline_orders") == 0
        and _status(facts.get("retry_status"), {302, 303})
        and payment_success
        and facts.get("payment_attempts") == 2
    )
    idempotent = (
        _status(
            facts.get("replay_order_status", facts.get("replay_payment_status")),
            {302, 303},
        )
        and (
            facts.get("replay_same_order") is True
            or facts.get("replay_same_confirmation") is True
        )
        and facts.get("orders") == 1
        and facts.get("completed_checkouts") == 1
    )
    auth_controls = facts.get("auth_ui_controls")
    if not isinstance(auth_controls, int):
        auth_controls = min(
            int(browser.get("registration_controls", 0)),
            int(browser.get("login_controls", 0)),
        )
    checkout_options = facts.get("checkout_ui_options")
    if not isinstance(checkout_options, int):
        checkout_options = int(browser.get("checkout_payment_options", 0))
    simulation_disclosed = facts.get("checkout_simulation_disclosed")
    if not isinstance(simulation_disclosed, bool):
        simulation_disclosed = browser.get("checkout_simulation_disclosed") is True
    remote_requests = facts.get(
        "ui_remote_requests", browser.get("remote_requests", [])
    )
    ui_auth = auth_controls >= 3 and remote_requests == []
    ui_checkout = (
        checkout_options == 3 and simulation_disclosed and remote_requests == []
    )
    foreign_status = facts.get(
        "foreign_order_status", facts.get("foreign_checkout_status")
    )
    auth_robustness = (
        _status(facts.get("restart_login_status"), {302, 303})
        and facts.get("restart_order_visible") is True
        and foreign_status == 404
        and account_progression
        and database_isolated
    )
    checkout_robustness = (
        idempotent and facts.get("restart_orders") == 1 and facts.get("orders") == 1
    )

    def result(ok: bool, message: str) -> tuple[bool, list[str]]:
        return ok, [] if ok else [message]

    checks = {
        "contract::auth-checkout/offline-harbor-profile": (
            profile_ok,
            runtime_failures
            + (
                []
                if database_isolated
                else ["candidate/reference database identity overlaps"]
            )
            + (
                []
                if facts.get("plaintext_registration_codes") == 0
                else ["plaintext OTP persistence detected"]
            ),
        ),
        "api::auth/registration-verification-login": result(
            auth_happy, "registration/verification/logout/login sequence failed"
        ),
        "api::auth/error-expiry-replay-guards": result(
            auth_negative,
            "auth negative, expiry, replay, or account-count guard failed",
        ),
        "api::checkout/sandbox-success-decline-retry": result(
            payment_flow, "sandbox success, decline, or retry behavior failed"
        ),
        "api::checkout/idempotent-order-persistence": result(
            idempotent, "idempotent order persistence failed"
        ),
        "ui::auth/registration-and-login": result(
            ui_auth, "auth UI controls or offline-network guard failed"
        ),
        "ui::checkout/sandbox-payment": result(
            ui_checkout, "sandbox checkout UI or disclosure failed"
        ),
        "journey::auth-checkout/register-to-durable-order": result(
            profile_ok and auth_happy and auth_negative and payment_flow and idempotent,
            "full auth/checkout journey failed",
        ),
        "robustness::auth/restart-and-owner-isolation": result(
            auth_robustness, "restart persistence or cross-account isolation failed"
        ),
        "robustness::checkout/retry-idempotency-persistence": result(
            checkout_robustness, "checkout retry/idempotency/restart persistence failed"
        ),
    }
    if set(checks) != policy_nodes:
        raise ValueError("platform gate implementation does not match policy nodes")

    enforced = _replace_mandatory_results(report, checks)
    output_path.write_text(
        json.dumps(enforced, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    evidence_path.write_text(
        json.dumps(
            {
                "schema_version": "websitebench.harbor.auth-checkout-gate.v1",
                "candidate_runtime_sha256": candidate_runtime_sha256,
                "nodes": {
                    node: {"passed": passed, "failures": failures}
                    for node, (passed, failures) in checks.items()
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--required", type=Path, required=True)
    parser.add_argument("--site-report", type=Path, required=True)
    parser.add_argument("--candidate-facts", type=Path, required=True)
    parser.add_argument("--reference-facts", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--reference-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    enforce(
        policy_path=args.policy,
        required_path=args.required,
        site_report_path=args.site_report,
        candidate_facts_path=args.candidate_facts,
        reference_facts_path=args.reference_facts,
        candidate_root=args.candidate_root,
        reference_root=args.reference_root,
        output_path=args.output,
        evidence_path=args.evidence,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
