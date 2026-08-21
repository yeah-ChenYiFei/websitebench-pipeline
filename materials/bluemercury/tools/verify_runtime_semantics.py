#!/usr/bin/env python3
"""Black-box persistence, reset, payment-sandbox, and ownership probe."""

from __future__ import annotations

import json
import os
import re
import secrets
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "clone" / "app.py"
COOKIE_NAME = "__Host-wb-bluemercury"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def free_port() -> int:
    with socket.socket() as handle:
        handle.bind(("127.0.0.1", 0))
        return int(handle.getsockname()[1])


def request(base: str, path: str, *, method: str = "GET", data: dict[str, str] | None = None, session: str | None = None, headers: dict[str, str] | None = None) -> tuple[int, dict[str, str], bytes]:
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    request_headers = dict(headers or {})
    if body is not None:
        request_headers["Content-Type"] = "application/x-www-form-urlencoded"
    if session:
        request_headers["Cookie"] = f"{COOKIE_NAME}={session}"
    call = urllib.request.Request(base + path, data=body, headers=request_headers, method=method)
    opener = urllib.request.build_opener(urllib.request.HTTPHandler(), NoRedirect())
    try:
        response = opener.open(call, timeout=5)
    except urllib.error.HTTPError as exc:
        response = exc
    return int(response.status), dict(response.headers.items()), response.read()


def start(port: int, data_dir: Path, reset_token: str) -> subprocess.Popen[bytes]:
    environment = os.environ.copy()
    environment.update({"HOST": "127.0.0.1", "PORT": str(port), "DATA_DIR": str(data_dir), "SEED": "20", "TZ": "Etc/UTC", "BLUEMERCURY_ADMIN_RESET_TOKEN": reset_token})
    process = subprocess.Popen([sys.executable, str(APP)], cwd=APP.parent, env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    for _ in range(50):
        if process.poll() is not None:
            raise RuntimeError(process.stderr.read().decode("utf-8", "replace"))
        try:
            status, _, payload = request(f"http://127.0.0.1:{port}", "/__websitebench/health")
            if status == 200 and payload == b'{"status":"ok"}':
                return process
        except OSError:
            pass
        time.sleep(0.1)
    process.terminate()
    raise RuntimeError("candidate health timeout")


def stop(process: subprocess.Popen[bytes]) -> None:
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def main() -> None:
    owner = "owner-" + secrets.token_hex(12)
    foreign = "foreign-" + secrets.token_hex(12)
    reset_token = secrets.token_urlsafe(32)
    with tempfile.TemporaryDirectory(prefix="bluemercury-runtime-probe-") as name:
        data_dir = Path(name) / "data"
        data_dir.mkdir()
        port = free_port()
        base = f"http://127.0.0.1:{port}"
        first = start(port, data_dir, reset_token)
        try:
            status, headers, _ = request(base, "/products/skinceuticals-c-e-ferulic", method="POST", data={"variant_id": "32352032096331", "quantity": "1"}, session=owner)
            assert status == 302 and headers.get("Location") == "/cart"
            status, _, checkout_page = request(base, "/checkout", session=owner)
            assert status == 200
            submission_match = re.search(rb'name="submission_key" value="([A-Za-z0-9_-]+)"', checkout_page)
            assert submission_match
            checkout = {"email": "shopper@example.test", "first_name": "Alex", "last_name": "Mercury", "address": "100 Test Avenue", "city": "Testville", "state": "NY", "postal_code": "10001", "country": "US", "fixture_id": "synthetic-standard-us", "submission_key": submission_match.group(1).decode(), "scenario_id": "sandbox-approved"}
            status, headers, _ = request(base, "/checkout", method="POST", data=checkout, session=owner)
            assert status == 302 and headers.get("Location", "").startswith("/orders/BM-")
            order_path = headers["Location"]
            assert request(base, order_path, session=owner)[0] == 200
            assert request(base, order_path, session=foreign)[0] == 404
            database_path = data_dir / "bluemercury.sqlite3"
            connection = sqlite3.connect(database_path)
            connection.row_factory = sqlite3.Row
            contact_records = [json.loads(row["contact_json"]) for row in connection.execute("SELECT contact_json FROM bluemercury_orders")]
            outbox_recipients = [row["recipient"] for row in connection.execute("SELECT recipient FROM websitebench_mail_jobs")]
            columns = [row["name"] for row in connection.execute("PRAGMA table_info(bluemercury_orders)")]
            credential_columns = [name for name in columns if re.search(r"card|cvv|cvc|expiry|wallet|bank|token", name, re.I)]
            connection.close()
            assert contact_records == [{"synthetic_profile_id": "synthetic-standard-us"}]
            assert outbox_recipients and all(value.endswith("@example.test") for value in outbox_recipients)
            assert credential_columns == []
        finally:
            stop(first)

        second = start(port, data_dir, reset_token)
        try:
            persisted_status = request(base, order_path, session=owner)[0]
            reset_without_token_status = request(base, "/__admin/reset", method="POST")[0]
            reset_wrong_token_status = request(base, "/__admin/reset", method="POST", headers={"X-WebsiteBench-Admin-Token":"wrong", "X-WebsiteBench-Confirm-Site":"bluemercury"})[0]
            reset_cross_origin_status = request(base, "/__admin/reset", method="POST", headers={"X-WebsiteBench-Admin-Token":reset_token, "X-WebsiteBench-Confirm-Site":"bluemercury", "Origin":"https://evil.example"})[0]
            reset_headers = {"X-WebsiteBench-Admin-Token":reset_token, "X-WebsiteBench-Confirm-Site":"bluemercury"}
            reset_status, _, reset_body = request(base, "/__admin/reset", method="POST", headers=reset_headers)
            after_reset_status = request(base, order_path, session=owner)[0]
            assert persisted_status == 200
            assert reset_without_token_status == 403
            assert reset_wrong_token_status == 403
            assert reset_cross_origin_status == 403
            assert reset_status == 200 and json.loads(reset_body) == {"status": "ok"}
            assert after_reset_status == 404
        finally:
            stop(second)

        runtime = json.loads((ROOT / "backend" / "runtime.json").read_text(encoding="utf-8"))
        report = {
            "schema_version": "bluemercury.runtime-semantics.v1",
            "site_id": runtime["site"]["id"],
            "database": runtime["database"]["filename"],
            "payment_adapter": runtime["payments"]["default_adapter"],
            "synthetic_checkout": "approved",
            "owner_order_status": 200,
            "foreign_order_status": 404,
            "restart_owner_order_status": persisted_status,
            "reset_status": reset_status,
            "reset_without_token_status": reset_without_token_status,
            "reset_wrong_token_status": reset_wrong_token_status,
            "reset_cross_origin_status": reset_cross_origin_status,
            "after_reset_order_status": after_reset_status,
            "retention_scan": {
                "database_scanned": True,
                "synthetic_fields_retained": ["synthetic_profile_id"],
                "contact_records": contact_records,
                "payment_credential_columns": credential_columns,
                "payment_credentials_retained": False,
                "outbox_recipient_policy": "example.test-only",
                "outbox_recipients_example_test_only": all(value.endswith("@example.test") for value in outbox_recipients)
            },
            "sensitive_values_retained": bool(credential_columns),
            "authority": "diagnostic-only"
        }
        output = ROOT / "artifacts" / "diagnostics" / "backend-runtime-semantics.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
