"""Structural, release-blocking invariants for the TripIt offline clone.

These tests pin the frozen facts the acceptance producers depend on but that a
route-level behaviour test does not naturally express:

* the single frozen clock is authoritative across constant, database, and
  render surfaces (``determinism.frozen-clock``);
* the frozen anonymous visual contract is sha256-intact and mask-free
  (``visual.frozen-anonymous-contract``);
* no authenticated/Pro pixel was ever fabricated
  (``evidence.no-fabricated-authenticated-pixels``);
* exactly two auth mail purposes carry secrets
  (``auth.secret-mail-purposes``);
* the physical SQLite seed rows equal the frozen manifest after reset
  (``deterministic-seed-rows`` + ``seed-reset.exact-reseed``);
* Pro checkout is test-mode only with no live-key shape reachable
  (``payments.test-mode-only``).

Every assertion is a pure function of committed ``scope``/``backend`` files and
the seeded ephemeral database. No secret value is ever read, asserted on, or
logged.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import sys
import tempfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

SITE_DIR = Path(__file__).resolve().parents[2]
CLONE_DIR = SITE_DIR / "clone"
APP_FILE = CLONE_DIR / "app.py"
SCOPE_DIR = SITE_DIR / "scope"
RUNTIME_FILE = SITE_DIR / "backend" / "runtime.json"

# Pin a throwaway data dir before import so the backend resolves its single
# sqlite file inside it.
DATA_DIR = Path(tempfile.mkdtemp(prefix="tripit-structural-tests-"))
os.environ["WEBSITEBENCH_TRIPIT_DATA_DIR"] = str(DATA_DIR)

FROZEN_CLOCK = "2026-08-04T09:00:00-04:00"
FROZEN_CLOCK_UTC = "2026-08-04T13:00:00Z"
FROZEN_DATE = "2026-08-04"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


app_module = load_module(APP_FILE, "tripit_clone_app_structural_tests")
db = sys.modules["tripit_clone_backend_db"]
app = app_module.app

PASSWORDS = {row["email"]: row["password"] for row in db.AUTH_FIXTURES}


@pytest.fixture(autouse=True)
def pinned_data_dir(monkeypatch):
    monkeypatch.setenv("WEBSITEBENCH_TRIPIT_DATA_DIR", str(DATA_DIR))
    yield


@pytest.fixture()
def client():
    app_module.reset_fixture_state()
    with TestClient(app, base_url="https://testserver") as test_client:
        yield test_client
    app_module.reset_fixture_state()


def _scope(name: str):
    return json.loads((SCOPE_DIR / name).read_text(encoding="utf-8"))


def _runtime():
    return json.loads(RUNTIME_FILE.read_text(encoding="utf-8"))


def _coverage_dimension(dimension_id: str) -> dict:
    for dimension in _scope("coverage.json")["dimensions"]:
        if dimension["id"] == dimension_id:
            return dimension
    raise AssertionError(f"missing coverage dimension {dimension_id}")


# ---------------------------------------------------------------------------
# determinism.frozen-clock
# ---------------------------------------------------------------------------


def test_frozen_clock_is_pinned_across_runtime_surfaces(client):
    # 1. The constant surface is internally consistent and matches the frozen
    #    seed manifest.
    assert db.FROZEN_CLOCK == FROZEN_CLOCK
    assert db.FROZEN_CLOCK_UTC == FROZEN_CLOCK_UTC
    assert db.FROZEN_DATE == FROZEN_DATE
    local = datetime.fromisoformat(FROZEN_CLOCK)
    utc = datetime.fromisoformat(FROZEN_CLOCK_UTC.replace("Z", "+00:00"))
    assert local.astimezone(timezone.utc) == utc
    assert FROZEN_DATE == FROZEN_CLOCK[:10]
    manifest = _scope("deterministic-seed.json")
    assert manifest["frozen_clock_iso"] == db.FROZEN_CLOCK
    assert manifest["frozen_clock_timezone"] == "America/New_York"

    # 2. The database surface: every seeded business row and migration-ledger
    #    row carries the frozen UTC instant, never a wall-clock value.
    with closing(db.connect()) as connection:
        trip_stamps = {
            row[0]
            for row in connection.execute("SELECT DISTINCT created_at FROM tripit_trips")
        }
        profile_stamps = {
            row[0]
            for row in connection.execute(
                "SELECT DISTINCT created_at FROM tripit_traveler_profiles"
            )
        }
        migration_rows = connection.execute(
            "SELECT * FROM tripit_schema_migrations"
        ).fetchall()
    assert trip_stamps == {FROZEN_CLOCK_UTC}, trip_stamps
    assert profile_stamps == {FROZEN_CLOCK_UTC}, profile_stamps
    assert migration_rows, "business migration ledger is empty"
    for row in migration_rows:
        assert FROZEN_CLOCK_UTC in {str(value) for value in tuple(row)}, tuple(row)

    # 3. The render surface: two renders of the same state, anonymous and
    #    authenticated, are byte-identical (no wall clock or randomness leaks
    #    into rendering).
    assert client.get("/").content == client.get("/").content
    signin = client.post(
        "/account/login",
        data={
            "login_email_address": "traveler@example.com",
            "login_password": PASSWORDS["traveler@example.com"],
        },
        follow_redirects=False,
    )
    assert signin.status_code == 303
    with closing(db.connect()) as connection:
        owner = db.owner_for_subject(connection, "traveler")
        trips = db.list_trips(connection, owner, "upcoming")
    trip_id = next(t["trip_id"] for t in trips if t["name"] == "New York")
    first = client.get(f"/trips/{trip_id}")
    second = client.get(f"/trips/{trip_id}")
    assert first.status_code == 200
    assert first.content == second.content


# ---------------------------------------------------------------------------
# visual.frozen-anonymous-contract
# ---------------------------------------------------------------------------


def test_visual_contract_integrity_matches_frozen_sources():
    checkpoints_doc = _scope("checkpoints.json")
    assert checkpoints_doc["status"] == "frozen"
    assert checkpoints_doc["metric"] == "pixel-mae-similarity-v1"
    assert checkpoints_doc["freeze_decision"].get("decided_at")
    viewports = checkpoints_doc["viewports"]

    checkpoints = checkpoints_doc["checkpoints"]
    assert checkpoints, "no checkpoints declared"

    for checkpoint in checkpoints:
        contract = checkpoint.get("visual_contract")
        if not isinstance(contract, dict):
            # Broad source raster (edx/petfinder shape): a top-level frozen
            # capture bound by path + sha256, witnessed by the real browser and
            # the independent audit rather than the small pixel oracle.
            source_path = SITE_DIR / checkpoint["source_artifact_path"]
            assert source_path.is_file(), source_path
            digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
            assert digest == checkpoint["source_artifact_sha256"], checkpoint["id"]
            assert {"width", "height"} <= set(viewports[checkpoint["viewport"]])
            continue

        # The frozen artifact exists and its bytes hash to the recorded sha256.
        source_path = SITE_DIR / contract["source_artifact_path"]
        assert source_path.is_file(), source_path
        digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
        assert digest == contract["source_artifact_sha256"], checkpoint["id"]

        # Contract shape: frozen metric, a bounded threshold, a comparison
        # region, and a viewport that matches the declared viewport table.
        assert contract["metric"] == "pixel-mae-similarity-v1", checkpoint["id"]
        assert 0.0 < float(contract["threshold"]) <= 1.0, checkpoint["id"]
        assert set(contract["comparison_region"]) >= {"x", "y", "width", "height"}
        declared = viewports[checkpoint["viewport"]]
        assert contract["viewport"] == {
            "width": declared["width"],
            "height": declared["height"],
        }, checkpoint["id"]

        # No ignore/mask region exists in any frozen contract or region
        # contract (the freeze decision recorded exactly zero masks).
        assert not contract.get("ignore_regions"), checkpoint["id"]
        for region in checkpoint.get("region_contracts", []):
            assert not region.get("ignore_regions"), checkpoint["id"]
            assert 0.0 < float(region["threshold"]) <= 1.0, checkpoint["id"]

    # The pixel-locked visual oracle is exactly the home surface at all three
    # viewports; every other source-direct state is a broad source raster.
    oracle = {
        c["id"] for c in checkpoints if isinstance(c.get("visual_contract"), dict)
    }
    assert oracle == {"home.desktop", "home.tablet", "home.mobile"}


# ---------------------------------------------------------------------------
# evidence.no-fabricated-authenticated-pixels
# ---------------------------------------------------------------------------


def test_no_fabricated_authenticated_pixels():
    checkpoints_doc = _scope("checkpoints.json")
    checkpoints = checkpoints_doc["checkpoints"]

    # Every checkpoint that carries pixel evidence is a directly-captured,
    # anonymous state. No authenticated or Pro surface has a visual contract.
    for checkpoint in checkpoints:
        assert checkpoint["evidence_kind"] == "direct", checkpoint["id"]
        assert checkpoint["role"] == "visitor.anonymous", checkpoint["id"]
        for url_field in ("requested_url", "final_url"):
            url = checkpoint.get(url_field, "")
            assert "/app/" not in url, (checkpoint["id"], url_field)

    # The checkpoint id set equals exactly the frozen anonymous coverage.
    direct_states = set(_coverage_dimension("source-direct-states")["required_items"])
    assert {c["id"] for c in checkpoints} == direct_states

    # A non-eligible checkpoint is never counted as acceptance evidence; every
    # eligible one is direct anonymous pixels.
    for checkpoint in checkpoints:
        if not checkpoint.get("acceptance_eligible", False):
            continue
        assert checkpoint["evidence_kind"] == "direct"

    # The authenticated families are declared full-suite-only: no visual or
    # browser pixel evidence is claimed for them.
    unavailable = _coverage_dimension("source-unavailable-states")
    assert unavailable["required_evidence_kinds"] == ["full-suite"]
    assert "visual" not in unavailable["required_evidence_kinds"]
    assert "browser" not in unavailable["required_evidence_kinds"]


# ---------------------------------------------------------------------------
# auth.secret-mail-purposes
# ---------------------------------------------------------------------------


def test_secret_mail_purposes_are_exactly_registration_and_password_reset(client):
    purposes = _runtime()["mail"]["purposes"]

    secret_purposes = {
        name for name, spec in purposes.items() if spec.get("secret_variables")
    }
    assert secret_purposes == {"registration", "password-reset"}
    for name in secret_purposes:
        assert purposes[name]["secret_variables"] == ["code"]

    business_purposes = {
        name for name, spec in purposes.items() if not spec.get("secret_variables")
    }
    assert business_purposes == {
        "share-invite",
        "import-receipt",
        "trip-update",
        "pro-receipt",
    }
    assert set(purposes) == secret_purposes | business_purposes

    # The store only ever surfaces the two auth-secret purposes; a business
    # purpose is rejected outright, so no business mail can carry a code.
    store = app_module.auth_store()
    for name in ("registration", "password-reset"):
        # No flow is pending on a fresh session, so this returns None rather
        # than raising -- the purpose itself is accepted.
        assert store.local_mail_for_session("no-such-session", purpose=name) is None
    with pytest.raises(ValueError):
        store.local_mail_for_session("no-such-session", purpose="share-invite")


# ---------------------------------------------------------------------------
# deterministic-seed-rows + seed-reset.exact-reseed
# ---------------------------------------------------------------------------


def test_seed_row_manifest_matches_coverage(client):
    seed_rows = _coverage_dimension("deterministic-seed-rows")["required_items"]
    manifest = _scope("deterministic-seed.json")
    assert manifest["authoritative_entity_count"] == len(seed_rows) == 22

    with closing(db.connect()) as connection:
        for item in seed_rows:
            entity, table, count_token = item.split("::")
            expected = int(count_token.split("=")[1])
            actual = connection.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]
            assert actual == expected, f"{entity} {table}: {actual} != {expected}"

    # The exact-reseed probe: the manifest's own expected counts agree with the
    # coverage rows the reset restores.
    probe = next(
        p for p in manifest["reset_probes"] if p["id"] == "seed-reset.exact-reseed"
    )
    for table, expected in probe["expected_entity_counts"].items():
        row = f"::{table}::count={expected}"
        assert any(item.endswith(row) for item in seed_rows), (table, expected)


# ---------------------------------------------------------------------------
# payments.test-mode-only
# ---------------------------------------------------------------------------


def test_payments_are_test_mode_only():
    payments = _runtime()["payments"]

    # The default adapter is the local sandbox with exactly the three declared
    # scenarios; no live gateway is the default.
    assert payments["default_adapter"] == "local-sandbox"
    scenarios = {s["id"]: s["outcome"] for s in payments["local_sandbox"]["scenarios"]}
    assert scenarios == {
        "sandbox-pro-approved": "approved",
        "sandbox-pro-declined": "declined",
        "sandbox-pro-retryable": "retryable",
    }

    # Stripe test mode is dormant here; if it were configured, credentials must
    # be injected by env-var name (never an inline key) and its origin must
    # equal the site origin.
    stripe_test = payments.get("stripe_test")
    if stripe_test is not None:
        for env_field in ("secret_key_env", "webhook_secret_env"):
            value = str(stripe_test.get(env_field, ""))
            assert value and value == value.upper()
            assert not value.startswith(("sk_", "whsec_"))
        site_origin = _runtime()["site"]["public_origin"]
        assert stripe_test.get("public_origin") == site_origin

    # No live Stripe key shape is embedded anywhere in the served clone (a bare
    # "sk_live_" prefix in validation code would not match this key pattern).
    live_key = re.compile(r"sk_live_[0-9A-Za-z]{16,}")
    scanned = 0
    for path in sorted(CLONE_DIR.rglob("*.py")):
        if "/tests/" in path.as_posix():
            continue
        assert not live_key.search(path.read_text(encoding="utf-8")), path
        scanned += 1
    assert scanned > 0
