"""Platform-wide Harbor capability requirements.

These nodes are mandatory for every WebsiteBench Harbor instance.  Keeping the
policy outside historical manifest schemas lets the loader continue to parse
immutable corpus identities while applying the current release contract.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


POLICY_BASELINES_SCHEMA = "websitebench.harbor.policy-baselines.v1"
LEGACY_PRE_AUTH_CHECKOUT_POLICY = "legacy-pre-auth-checkout-v1"
POLICY_BASELINES_FILE = "policy-baselines.json"


AUTH_CHECKOUT_REQUIRED_NODES: dict[str, tuple[str, ...]] = {
    "contract": ("contract::auth-checkout/offline-harbor-profile",),
    "api": (
        "api::auth/registration-verification-login",
        "api::auth/error-expiry-replay-guards",
        "api::checkout/sandbox-success-decline-retry",
        "api::checkout/idempotent-order-persistence",
    ),
    "ui": (
        "ui::auth/registration-and-login",
        "ui::checkout/sandbox-payment",
    ),
    "journey": ("journey::auth-checkout/register-to-durable-order",),
    "robustness": (
        "robustness::auth/restart-and-owner-isolation",
        "robustness::checkout/retry-idempotency-persistence",
    ),
}


def auth_checkout_policy_required(
    corpus_root: Path,
    *,
    instance_id: str,
    manifest_sha256: str,
) -> bool:
    """Return whether the current auth/checkout policy applies to an instance.

    A pre-policy instance retains its earlier behavior only through an exact
    SHA-bound registry entry. Editing a pinned manifest fails closed instead of
    silently inheriting the compatibility exception.
    """

    path = corpus_root / POLICY_BASELINES_FILE
    if not path.is_file():
        return True
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {POLICY_BASELINES_FILE}: {exc}") from exc
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != POLICY_BASELINES_SCHEMA
    ):
        raise ValueError(f"unsupported {POLICY_BASELINES_FILE} schema")
    instances = value.get("instances")
    if not isinstance(instances, dict):
        raise ValueError(f"{POLICY_BASELINES_FILE}.instances must be an object")
    entry = instances.get(instance_id)
    if entry is None:
        return True
    if not isinstance(entry, dict):
        raise ValueError(f"policy baseline for {instance_id!r} must be an object")
    if entry.get("manifest_sha256") != manifest_sha256:
        raise ValueError(
            f"policy baseline SHA mismatch for {instance_id!r}; migrate the "
            "instance to the current auth/checkout policy or review a new pin"
        )
    if entry.get("policy") != LEGACY_PRE_AUTH_CHECKOUT_POLICY:
        raise ValueError(f"unsupported policy baseline for {instance_id!r}")
    return False


def missing_auth_checkout_nodes(
    tests: Mapping[str, Any],
) -> dict[str, tuple[str, ...]]:
    """Return mandatory nodes absent from an instance test matrix."""

    missing: dict[str, tuple[str, ...]] = {}
    for dimension, required in AUTH_CHECKOUT_REQUIRED_NODES.items():
        declared = tests.get(dimension)
        present = set(declared) if isinstance(declared, Sequence) else set()
        absent = tuple(node for node in required if node not in present)
        if absent:
            missing[dimension] = absent
    return missing


def auth_checkout_policy_payload() -> dict[str, Any]:
    """Return the canonical machine-readable policy embedded in bundles."""

    return {
        "schema_version": "websitebench.harbor.auth-checkout-policy.v1",
        "applies_to": "all-instances",
        "deployment_profile": "offline-harbor",
        "mail_adapter": "local-outbox",
        "payment_adapter": "local-sandbox",
        "required_capabilities": {
            "registration": True,
            "trusted_admin_registration_outbox": True,
            "verification_expiry_and_single_use": True,
            "sign_out_and_sign_in": True,
            "wrong_password_and_duplicate_email_rejection": True,
            "account_restart_persistence": True,
            "cross_account_isolation": True,
            "sandbox_payment_success_decline_retry": True,
            "idempotent_order_commit": True,
            "order_restart_persistence": True,
        },
        "forbidden_effects": {
            "external_mail_delivery": True,
            "stripe_test_or_live_network": True,
            "payment_credentials": True,
        },
        "required_nodes": {
            dimension: list(nodes)
            for dimension, nodes in AUTH_CHECKOUT_REQUIRED_NODES.items()
        },
    }
