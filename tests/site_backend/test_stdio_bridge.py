from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from websitebench.local_clone_auth import LocalAuthStore
from websitebench.site_backend import SiteBackend
from websitebench.site_backend.stdio_bridge import (
    BridgeProtocolError,
    BridgeService,
    serve_jsonl,
    validate_allowlist,
)

from .helpers import runtime_config


REPOSITORY = Path(__file__).resolve().parents[2]


def _services(tmp_path: Path, *, direct: bool = False):
    config = runtime_config()
    if direct:
        config["mail"] = {
            "enabled": False,
            "sender": {
                "display_name": "Alpha Clone",
                "address_env": "RESEND_FROM_EMAIL",
            },
            "purposes": {},
        }
    backend = SiteBackend.open(config, data_root=tmp_path)
    backend.lifecycle.initialize()
    auth = LocalAuthStore(backend.lifecycle.database_path, site_id="alpha")
    auth.ensure_schema()
    return backend, auth


def test_bridge_allowlist_is_site_bound_and_closed() -> None:
    descriptor = {
        "schema_version": "websitebench.node-backend-bridge.v1",
        "site_id": "alpha",
        "allowed_operations": ["health", "session.ensure"],
    }
    assert validate_allowlist(descriptor, expected_site_id="alpha") == {
        "health",
        "session.ensure",
    }
    descriptor["allowed_operations"].append("os.exec")
    with pytest.raises(BridgeProtocolError, match="unsupported"):
        validate_allowlist(descriptor, expected_site_id="alpha")
    descriptor["allowed_operations"] = ["health"]
    with pytest.raises(BridgeProtocolError, match="site_id"):
        validate_allowlist(descriptor, expected_site_id="beta")


def test_direct_registration_and_payments_resolve_owner_from_session(
    tmp_path: Path,
) -> None:
    backend, auth = _services(tmp_path, direct=True)
    service = BridgeService(
        backend,
        auth,
        frozenset(
            {
                "session.ensure",
                "auth.register-direct",
                "payment.create",
                "payment.attempt",
                "payment.consume",
            }
        ),
    )
    anonymous = service.handle("session.ensure", {"session_token": None})
    registration = service.handle(
        "auth.register-direct",
        {
            "session_token": anonymous["session_token"],
            "email": "owner@example.test",
            "display_name": "Owner",
            "password": "correct horse battery staple",
        },
    )
    token = registration["session_token"]
    facts = {
        "session_token": token,
        "amount_minor": 1250,
        "currency": "USD",
        "fingerprint": "a" * 64,
    }
    flow = service.handle(
        "payment.create", {**facts, "idempotency_key": "create-one"}
    )
    attempt = service.handle(
        "payment.attempt",
        {
            **facts,
            "flow_id": flow["flow_id"],
            "scenario_id": "sandbox-approved",
            "idempotency_key": "attempt-one",
        },
    )
    assert attempt["status"] == "APPROVED"
    consumed = service.handle(
        "payment.consume", {**facts, "flow_id": flow["flow_id"]}
    )
    assert consumed["owner"] == auth.session_owner_digest(token)


def test_jsonl_bridge_rejects_extra_arguments_without_echoing_them(
    tmp_path: Path,
) -> None:
    backend, auth = _services(tmp_path)
    request = {
        "id": "one",
        "operation": "session.ensure",
        "arguments": {"session_token": None, "command": "cat /etc/passwd"},
    }
    output = io.StringIO()
    serve_jsonl(
        backend,
        auth,
        frozenset({"session.ensure"}),
        io.StringIO(json.dumps(request) + "\n"),
        output,
    )
    response = json.loads(output.getvalue())
    assert response["ok"] is False
    assert response["error"]["type"] == "BridgeProtocolError"
    assert "cat /etc/passwd" not in output.getvalue()


@pytest.mark.parametrize(
    ("site_id", "payments_enabled"),
    [
        ("hipcamp", True),
        ("linkedin", True),
        ("notion", True),
        ("ubereats", True),
        ("workable", False),
    ],
)
def test_node_clone_descriptor_and_client_are_fixed_shape(
    site_id: str, payments_enabled: bool
) -> None:
    site = REPOSITORY / "materials" / site_id
    runtime = json.loads((site / "backend/runtime.json").read_text(encoding="utf-8"))
    descriptor = json.loads(
        (site / "backend/node-bridge.json").read_text(encoding="utf-8")
    )
    allowed = validate_allowlist(descriptor, expected_site_id=site_id)
    assert any(operation.startswith("auth.") for operation in allowed)
    assert any(operation.startswith("payment.") for operation in allowed) is payments_enabled
    assert runtime["payments"].get("enabled", True) is payments_enabled

    client = (site / "clone/backend/site_backend_bridge.mjs").read_text(
        encoding="utf-8"
    )
    assert "site_backend_integration.py" in client
    assert "shell: false" in client
    assert "[integration, \"--stdio\"]" in client
    assert "exec(" not in client and "eval(" not in client
