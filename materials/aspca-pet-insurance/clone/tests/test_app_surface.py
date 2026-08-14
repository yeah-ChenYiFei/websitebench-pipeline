"""App-level surface: pages, headers, static mirror, admin reset, boundary."""

from pathlib import Path

import app as app_module

CLONE_DIR = Path(__file__).resolve().parents[1]

PAGE_PATHS = [
    "/",
    "/pet-insurance-plan/",
    "/cat-insurance/",
    "/dog-insurance/",
    "/why-us/",
    "/research-and-compare/",
    "/about-us/",
    "/about-us/contact-us/",
]

MARKETING_RUNTIME_TAG = '<script src="/static/site/marketing-app.js" defer></script>'


def test_all_frozen_pages_serve(client) -> None:
    for path in PAGE_PATHS:
        response = client.get(path)
        assert response.status_code == 200, path
        assert response.headers["content-type"].startswith("text/html"), path


def test_all_marketing_pages_load_the_local_interaction_runtime(client) -> None:
    for path in PAGE_PATHS:
        response = client.get(path)
        assert MARKETING_RUNTIME_TAG in response.text, path

    runtime = client.get("/static/site/marketing-app.js")
    assert runtime.status_code == 200


def test_marketing_runtime_covers_navigation_and_preferences() -> None:
    script = (CLONE_DIR / "static/site/marketing-app.js").read_text(
        encoding="utf-8"
    )
    assert "#menuToggle" in script
    assert "#mobileNavContainer" in script
    assert ".dropdownBtn" in script
    assert ".osano-cm-dialog__close" in script
    assert ".osano-cm-manage" in script
    assert "aria-expanded" in script


def test_security_headers_on_every_response(client) -> None:
    for path in ("/", "/healthz", "/quote/", "/portal/", "/no-such-page"):
        response = client.get(path)
        csp = response.headers.get("content-security-policy", "")
        assert "default-src 'self'" in csp, path
        assert response.headers.get("x-content-type-options") == "nosniff", path
        assert response.headers.get("x-frame-options") == "DENY", path
        assert response.headers.get("referrer-policy") == "no-referrer", path


def test_healthz_exact_body(client) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"ok": True, "site_id": "aspca-pet-insurance"}


def test_quote_and_portal_shells(client) -> None:
    quote = client.get("/quote/")
    assert quote.status_code == 200
    assert "/static/site/quote-app.js" in quote.text

    no_slash = client.get("/quote", follow_redirects=False)
    assert no_slash.status_code in (200, 307)

    portal = client.get("/portal/")
    assert portal.status_code == 200
    assert "/static/site/portal-app.js" in portal.text


def test_checkout_script_exposes_only_labeled_local_payment_scenarios() -> None:
    script = (CLONE_DIR / "static/site/quote-app.js").read_text(encoding="utf-8")
    assert "Local payment simulation" in script
    assert "No real payment will be made" in script
    assert 'name = "paymentScenario"' in script
    assert 'scenario_id: scenario' in script
    assert "sandbox-approved" in script
    assert "sandbox-declined" in script
    assert "sandbox-retry" in script
    assert "LOCAL_SIMULATION" in script


def test_view_fragments_serve_and_reject_bad_names(client) -> None:
    views_dir = CLONE_DIR / "frontend" / "quote" / "views"
    served = 0
    for view in sorted(views_dir.glob("*.html")):
        response = client.get(f"/quote/views/{view.stem}")
        assert response.status_code == 200, view.stem
        served += 1
    assert served > 0

    assert client.get("/quote/views/../../app").status_code in (400, 404, 422)
    assert client.get("/quote/views/NoSuchView").status_code in (400, 404, 422)


def test_static_mirror_serves_assets(client) -> None:
    static_root = CLONE_DIR / "static"
    sample = next(
        p
        for p in static_root.rglob("*")
        if p.is_file() and p.suffix in {".css", ".js", ".png", ".jpg", ".svg", ".webp"}
    )
    url = "/static/" + sample.relative_to(static_root).as_posix()
    response = client.get(url)
    assert response.status_code == 200, url


def test_admin_reset_requires_token(client) -> None:
    denied = client.post("/__admin/reset")
    assert denied.status_code == 403

    wrong = client.post("/__admin/reset", headers={"X-WebsiteBench-Admin-Token": "nope"})
    assert wrong.status_code == 403

    granted = client.post(
        "/__admin/reset",
        headers={"X-WebsiteBench-Admin-Token": app_module.ADMIN_TOKEN},
    )
    assert granted.status_code == 200
    # Golden pattern (materials/tripit): reset acknowledges with
    # {"reset": true, "site_id": ...}; "ok" is the /healthz body shape.
    assert granted.json() == {"reset": True, "site_id": "aspca-pet-insurance"}


def test_external_boundary_page(client) -> None:
    response = client.get("/external/facebook")
    assert response.status_code == 200
    assert "facebook" in response.text
    assert "third-party" in response.text.lower() or "external" in response.text.lower()


def test_unknown_page_is_html_404_but_api_is_json(client) -> None:
    page = client.get("/definitely-not-a-page")
    assert page.status_code == 404
    assert page.headers["content-type"].startswith("text/html")

    api = client.get("/api/definitely-not-a-route")
    assert api.status_code == 404
    assert api.json() == {"error": "not-found"}
