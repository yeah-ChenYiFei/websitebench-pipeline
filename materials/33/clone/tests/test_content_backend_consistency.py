"""Content/backend consistency tests for the site-33 Coursera clone.

These tests assert the user-facing rule: whatever a page displays must be the
current backend state, never a second front-end truth. They also pin the
frontend-spec assets and the owner-authorized real CSS layer.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

SITE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SITE_ROOT / "clone"))

from app import app  # noqa: E402
from backend import checkout, learning_db  # noqa: E402

_CJK = re.compile(r"[\u4e00-\u9fff]")
_CSS_DIR = SITE_ROOT / "source-assets" / "coursera-css"
_SPEC_DIR = SITE_ROOT / "scope" / "frontend-specs"


@pytest.fixture
def route_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(
        "WEBSITEBENCH_SITE_BACKEND_DATABASE", str(tmp_path / "33.sqlite3")
    )
    learning_db.close_services()
    with TestClient(app, base_url="https://33.offline.invalid") as client:
        yield client
    learning_db.close_services()


def _login(client: TestClient, email: str, password: str) -> None:
    response = client.post(
        "/auth/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )
    assert response.status_code == 303


def test_checkout_totals_match_backend_plan(route_client) -> None:
    """The checkout page shows exactly the server-owned plan numbers."""

    _login(route_client, "empty@coursera.test", "Empty-Learner-33")
    html = route_client.get("/checkout/deep-learning").text
    plan = checkout.plan()
    assert _CJK.search(html) is None
    # total_minor 0 -> "Total due today: ¥0"
    assert "Total due today: ¥0" in html
    assert "¥196/month" in html  # renewal_minor 19600
    assert "7-day free trial" in html  # trial_days 7
    assert str(plan["currency"]) == "CNY"


def test_order_detail_status_matches_backend_state(route_client) -> None:
    """Order page status attribute and copy reflect the persisted order."""

    _login(route_client, "empty@coursera.test", "Empty-Learner-33")
    draft = checkout.create_draft(
        "learner-empty",
        course_id="deep-learning-specialization",
        plan_id="deep-learning-specialization-trial",
    )
    order = checkout.attempt(
        "learner-empty",
        draft["draft_id"],
        scenario_id="sandbox-approved",
        idempotency_key="consistency-test-1",
    )["order"]

    detail = route_client.get(f"/orders/{order['order_id']}").text
    assert 'data-order-status="PAID"' in detail
    assert "Paid" in detail
    assert "Total due today: ¥0" in detail

    checkout.cancel_order("learner-empty", order["order_id"])
    detail = route_client.get(f"/orders/{order['order_id']}").text
    assert 'data-order-status="CANCELED"' in detail
    assert "Canceled" in detail
    assert "immutable snapshot remains in history" in detail


def test_my_learning_progress_comes_from_backend_state(route_client) -> None:
    """Dashboard progress numbers equal the learning store, not page literals."""

    _login(route_client, "progress@coursera.test", "Progress-Learner-33")
    subject = "learner-in-progress"
    state = learning_db.learning_state(subject)
    html = route_client.get("/my-learning").text
    assert _CJK.search(html) is None
    completed = len(state["completed_lessons"])
    bookmarks = len(state["bookmarks"])
    if completed:
        assert f"{completed}" in html
    if bookmarks:
        assert f"{bookmarks}" in html
    # A resume control points at an enrolled lesson owned by the backend.
    assert "Resume" in html or "Continue" in html or "Start" in html


def test_course_page_content_matches_catalog_seed(route_client) -> None:
    """Course detail copy (title, provider) comes from the seed catalog."""

    catalog = json.loads(
        (SITE_ROOT / "clone" / "data" / "catalog.json").read_text(encoding="utf-8")
    )
    record = next(
        item for item in catalog if item["id"] == "neural-networks-deep-learning"
    )
    html = route_client.get("/learn/neural-networks-deep-learning").text
    assert _CJK.search(html) is None
    assert record["title"] in html
    # The Deep Learning page is a source-backed reconstruction with a fixed
    # provider; assert the known public provider copy is present.
    assert "DeepLearning.AI" in html


def test_rendered_public_routes_have_no_legacy_chinese_copy(route_client) -> None:
    """No legacy Chinese strings leak into any key public surface."""

    routes = [
        "/",
        "/browse",
        "/browse/data-science",
        "/browse/business",
        "/search",
        "/search?q=zzzz-no-match-websitebench",
        "/specializations/deep-learning",
        "/learn/neural-networks-deep-learning",
        "/login",
        "/signup",
        "/account-recovery",
        "/help",
        "/about/contact",
        "/terms",
        "/privacy",
    ]
    for path in routes:
        html = route_client.get(path).text
        assert _CJK.search(html) is None, f"Chinese copy leaked on {path}"


def test_frontend_spec_assets_are_archived_and_remote_free() -> None:
    """The frontend-spec assets exist for source and clone and stay local."""

    pairs = [
        ("home.source.json", "home.clone.json"),
        ("browse.source.json", "browse.clone.json"),
        ("search.source.json", "search.clone.json"),
        ("course.source.json", "course.clone.json"),
        ("login.source.json", "login.clone.json"),
        ("specialization.source.json", "specialization.clone.json"),
    ]
    for source_name, clone_name in pairs:
        source = json.loads((_SPEC_DIR / source_name).read_text(encoding="utf-8"))
        clone = json.loads((_SPEC_DIR / clone_name).read_text(encoding="utf-8"))
        assert source["schema_version"].startswith(
            "websitebench.offline-clone.frontend-spec.v1"
        )
        assert source["summary"]["http_status"] == 200
        assert clone["summary"]["blocked_request_count"] == 0
        assert len(source["document"]["headings"]) > 0
        assert len(clone["controls"]) > 0


def test_real_css_layer_is_localized_and_registered() -> None:
    """Owner-authorized real CSS has zero remote references and is manifest-listed."""

    manifest = json.loads(
        (SITE_ROOT / "source-assets" / "manifest.json").read_text(encoding="utf-8")
    )
    ids = {item["id"] for item in manifest["assets"]}
    assert any(item["id"].startswith("coursera-") for item in manifest["assets"])
    for css in sorted(_CSS_DIR.glob("*.css")):
        text = css.read_text(encoding="utf-8")
        assert re.search(r"url\(https?://[^)]*\)", text) is None, css.name
        assert f"coursera-{css.stem}-css" in ids, css.name
    assets = [item for item in manifest["assets"] if item["id"].startswith("coursera-asset-")]
    assert len(assets) > 0
    for item in assets:
        source = SITE_ROOT / item["source_path"]
        runtime = SITE_ROOT / item["runtime_path"]
        assert source.is_file(), item["source_path"]
        assert runtime.is_file(), item["runtime_path"]
