"""Behavioral checks for the site-local interaction inventory and markup audit."""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import app
from backend import learning_db
from interaction_contract import audit_markup, load_control_contract


SITE_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = SITE_ROOT / "scope" / "interaction-controls.json"
ASSIGNMENT_PATH = (
    "/learn/neural-networks-deep-learning/assignment-submission/3KFZW/"
    "introduction-to-deep-learning"
)


@pytest.fixture
def route_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(
        "WEBSITEBENCH_SITE_BACKEND_DATABASE", str(tmp_path / "33.sqlite3")
    )
    learning_db.close_services()
    with TestClient(app, base_url="https://33.offline.invalid") as client:
        yield client
    learning_db.close_services()


class _StartTags(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: list[tuple[str, dict[str, str]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append(
            (tag, {name: "" if value is None else value for name, value in attrs})
        )


_SIMPLE_SELECTOR = re.compile(
    r"^(?P<tag>[a-z][a-z0-9-]*)?\[(?P<attribute>[a-z0-9_-]+)"
    r"(?:=(?P<quote>['\"])(?P<value>.*?)['\"])?\]$"
)


def _selector_matches(markup: str, selector: str) -> bool:
    match = _SIMPLE_SELECTOR.fullmatch(selector)
    assert match is not None, f"test selector parser does not support {selector!r}"
    parser = _StartTags()
    parser.feed(markup)
    for tag, attrs in parser.tags:
        if match["tag"] and tag != match["tag"]:
            continue
        if match["attribute"] not in attrs:
            continue
        if match["value"] is None or attrs[match["attribute"]] == match["value"]:
            return True
    return False


def test_auditor_rejects_inert_controls_and_accepts_explicit_boundaries():
    """Catch a placeholder navigation or enabled no-op button reaching a page."""

    broken = '<a href="#">Open</a><button type="button">Save</button>'
    assert {item.code for item in audit_markup(broken, route="/")} == {
        "placeholder-link",
        "inert-button",
    }

    valid = (
        '<form action="/prefs" method="post"><button type="submit">Save</button></form>'
        '<button type="button" disabled aria-describedby="why">Verify</button>'
        '<p id="why">Unavailable offline.</p>'
    )
    assert audit_markup(valid, route="/") == ()


def test_auditor_recognizes_the_rendered_header_login_client_action(route_client):
    """Catch the real header login trigger being reported as an inert button."""

    findings = audit_markup(route_client.get("/").text, route="/")

    assert not any(
        finding.code == "inert-button" and finding.label == "Log In"
        for finding in findings
    )


def test_auditor_finalizes_placeholder_link_with_its_visible_label():
    """Catch a placeholder link diagnostic that loses the anchor's visible text."""

    assert [(finding.code, finding.label) for finding in audit_markup(
        '<a href="#">Open</a>', route="/"
    )] == [("placeholder-link", "Open")]


def test_auditor_catches_remaining_semantic_interaction_failures():
    """Catch routes that would escape locally, silent submits, image maps, or unexplained boundaries."""

    markup = """
        <a href="">Empty</a>
        <a href="javascript:void(0)">Script</a>
        <a href="/learn/neural-networks-deep-learning"><img alt="Neural Networks course card"></a>
        <button type="button" data-control-action="open-login">Log in</button>
        <button type="submit">Outside form</button>
        <form action="https://example.test/submit"><button type="submit">Remote form</button></form>
        <img src="diagram.png" usemap="#diagram">
        <map name="diagram"><area href="/help" alt="Help"></map>
        <button disabled aria-describedby="missing">Unavailable</button>
    """

    assert {item.code for item in audit_markup(markup, route="/search")} == {
        "placeholder-link",
        "orphan-submit",
        "nonlocal-submit",
        "image-map-control",
        "unexplained-disabled-control",
    }


def test_auditor_requires_accessible_names_for_local_image_card_links():
    """Catch a clickable card whose image omits the name available to assistive technology."""

    accessible = '<a href="/learn/neural-networks-deep-learning"><img alt="Neural Networks course card"></a>'
    assert audit_markup(accessible, route="/search") == ()

    unnamed = '<a href="/learn/neural-networks-deep-learning"><img src="card.png"></a>'
    assert {item.code for item in audit_markup(unnamed, route="/search")} == {
        "unlabeled-link"
    }


def test_auditor_resolves_aria_labelledby_and_finalizes_visible_labels():
    """Catch a label that is available only after parsing its referenced text."""

    markup = (
        '<span id="continue-label">Continue learning</span>'
        '<a href="/learn/neural-networks-deep-learning" aria-labelledby="continue-label">'
        '<img src="course.png" alt=""></a>'
        '<button type="button" aria-labelledby="continue-label"></button>'
    )

    findings = audit_markup(markup, route="/my-learning")
    assert [(item.code, item.label) for item in findings] == [
        ("inert-button", "Continue learning")
    ]


def test_loader_builds_typed_site_controls_and_binds_every_trace():
    """Catch an incomplete inventory that cannot trace a control to its local behavior."""

    controls = load_control_contract(CONTRACT_PATH)

    assert controls
    assert {control.id for control in controls} >= {
        "header-login",
        "header-search",
        "home-promo-next",
        "home-ai-bestsellers",
        "home-faq-toggle",
        "business-faq-toggle",
        "specialization-enrollment-login",
        "specialization-free-enrollment",
        "specialization-paid-checkout",
        "checkout-submit",
        "my-learning-course",
        "assignment-submit",
        "preferences-save",
        "support-guidance",
        "not-found-recovery",
    }
    assert {
        trace_id for control in controls for trace_id in control.trace_ids
    } == {f"trace-{number:03d}" for number in range(1, 24)}
    assert all(control.target.startswith("/") for control in controls)
    assert all(control.evidence_refs for control in controls)


def test_every_control_selector_matches_its_declared_rendered_route_state(route_client):
    """Catch an inventory selector that drifts from the control rendered by its route state."""

    rendered = {
        "header-login": ("/", route_client.get("/").text),
        "header-search": ("/", route_client.get("/").text),
        "home-promo-next": ("/", route_client.get("/").text),
        "home-ai-bestsellers": ("/", route_client.get("/").text),
        "home-faq-toggle": ("/", route_client.get("/").text),
        "business-faq-toggle": (
            "/browse/business",
            route_client.get("/browse/business").text,
        ),
        "public-browse-category": ("/browse", route_client.get("/browse").text),
        "public-course": ("/search", route_client.get("/search").text),
        "specialization-enrollment-login": (
            "/specializations/deep-learning",
            route_client.get("/specializations/deep-learning").text,
        ),
        "signup-registration": ("/signup", route_client.get("/signup").text),
        "login-submit": ("/login", route_client.get("/login").text),
        "password-recovery": (
            "/account-recovery",
            route_client.get("/account-recovery").text,
        ),
        "support-guidance": ("/help", route_client.get("/help").text),
        "not-found-recovery": (
            "/websitebench-nonexistent-route",
            route_client.get("/websitebench-nonexistent-route").text,
        ),
    }
    login = route_client.post(
        "/auth/learning-demo", data={"next": "/my-learning"}, follow_redirects=False
    )
    assert login.status_code == 303
    assignment_start = route_client.post(
        f"{ASSIGNMENT_PATH}/start",
        data={"honor_code": "accepted"},
        follow_redirects=False,
    )
    assert assignment_start.status_code == 303
    rendered.update(
        {
            "header-purchases": ("/", route_client.get("/").text),
            "specialization-free-enrollment": (
                "/specializations/deep-learning",
                route_client.get("/specializations/deep-learning").text,
            ),
            "specialization-paid-checkout": (
                "/specializations/deep-learning",
                route_client.get("/specializations/deep-learning").text,
            ),
            "checkout-submit": (
                "/checkout/deep-learning",
                route_client.get("/checkout/deep-learning").text,
            ),
            "my-learning-course": ("/my-learning", route_client.get("/my-learning").text),
            "assignment-submit": (
                f"{ASSIGNMENT_PATH}/attempt",
                route_client.get(f"{ASSIGNMENT_PATH}/attempt").text,
            ),
            "preferences-save": (
                "/account/preferences",
                route_client.get("/account/preferences").text,
            ),
            "account-settings-save": (
                "/account-settings",
                route_client.get("/account-settings").text,
            ),
            "updates-preferences-save": (
                "/updates",
                route_client.get("/updates").text,
            ),
            "course-objectives-toggle": (
                "/learn/neural-networks-deep-learning/home/module/1",
                route_client.get(
                    "/learn/neural-networks-deep-learning/home/module/1"
                ).text,
            ),
            "course-weekly-target": (
                "/learn/neural-networks-deep-learning/home/module/1",
                route_client.get(
                    "/learn/neural-networks-deep-learning/home/module/1"
                ).text,
            ),
            "lesson-reaction": (
                "/learn/neural-networks-deep-learning/lecture/Cuf2f/welcome",
                route_client.get(
                    "/learn/neural-networks-deep-learning/lecture/Cuf2f/welcome"
                ).text,
            ),
            "lesson-report": (
                "/learn/neural-networks-deep-learning/lecture/Cuf2f/welcome",
                route_client.get(
                    "/learn/neural-networks-deep-learning/lecture/Cuf2f/welcome"
                ).text,
            ),
            "help-feedback": ("/help", route_client.get("/help").text),
        }
    )

    controls = load_control_contract(CONTRACT_PATH)
    assert set(rendered) == {control.id for control in controls}
    for control in controls:
        route, markup = rendered[control.id]
        assert control.route == route
        assert _selector_matches(markup, control.selector), control.id


@pytest.mark.parametrize(
    ("change",),
    [
        (lambda entry: {**entry, "id": "header-login"},),
        (lambda entry: {**entry, "behavior": "remote"},),
        (lambda entry: {**entry, "selector": ""},),
        (lambda entry: {**entry, "target": "https://example.test"},),
        (lambda entry: {**entry, "trace_ids": ["trace-024"]},),
        (lambda entry: {**entry, "evidence_refs": []},),
    ],
)
def test_loader_rejects_invalid_control_contract_entries(tmp_path: Path, change):
    """Catch silently accepted duplicate, unbound, remote, or unproven controls."""

    first = {
        "id": "header-login",
        "route": "/",
        "selector": "[data-control='login']",
        "behavior": "navigate",
        "target": "/login",
        "persistence": "none",
        "trace_ids": ["trace-016"],
        "evidence_refs": ["source-evidence/example.json#login"],
    }
    payload = {"schema_version": "coursera.interaction-controls.v1", "controls": [first, change(first)]}
    path = tmp_path / "controls.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError):
        load_control_contract(path)
