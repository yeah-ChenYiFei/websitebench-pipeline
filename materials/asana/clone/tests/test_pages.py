import re

PUBLIC_PAGES = ["/", "/pricing", "/product", "/resources",
                "/templates", "/-/login", "/create-account",
                "/-/forgot_password"]


def test_public_pages_render(client) -> None:
    for path in PUBLIC_PAGES:
        r = client.get(path)
        assert r.status_code == 200, path
        assert "<title>" in r.text, path


def test_solutions_is_a_complete_reachable_public_page(client) -> None:
    response = client.get("/solutions")
    assert response.status_code == 200
    assert "Move every team’s work forward" in response.text
    for section in ("marketing", "operations", "product", "enterprise"):
        assert f'id="{section}"' in response.text


def test_public_navigation_has_real_mega_menus(client) -> None:
    text = client.get("/").text
    assert text.count('class="mnav-menu"') == 3
    assert text.count('class="mnav-mega"') == 3
    for label in ("Products", "Solutions", "Learning & support"):
        assert label in text


def test_template_card_destinations_are_reachable(client) -> None:
    for category in (
        "marketing", "operations-pmo", "design", "it",
        "product-engineering", "hr", "sales-cx",
    ):
        response = client.get(f"/templates/{category}")
        assert response.status_code == 200, category
        assert "AI workflow template gallery" in response.text


def test_observed_public_control_destinations_are_reachable(client) -> None:
    for path in (
        "/demo/main",
        "/resources/category/work-management",
        "/resources/category/project-planning",
        "/resources/category/workflow-automation",
        "/resources/category/ai-at-work",
        "/resources/category/strategic-planning",
        "/terms/terms-of-service",
        "/terms/privacy-statement",
    ):
        assert client.get(path).status_code == 200, path


def test_mobile_menu_reports_open_and_closed_state(client) -> None:
    text = client.get("/templates").text
    assert 'aria-expanded="false"' in text
    assert "setAttribute('aria-expanded',String(open))" in text


def test_login_page_copy(client) -> None:
    text = client.get("/-/login").text
    assert "Welcome to Asana" in text
    assert "To get started, please sign in" in text
    assert "Email address" in text
    assert "Continue" in text


def test_home_work_email_is_submitted_to_signup(client) -> None:
    text = client.get("/").text
    assert '<form class="source-signup" action="/create-account" method="get">' in text
    assert 'name="email"' in text


def test_signup_prefills_and_escapes_home_work_email(client) -> None:
    text = client.get(
        "/create-account", params={"email": '\" autofocus onfocus=\"alert(1)'}
    ).text
    assert (
        'id="email" name="email" type="email" autocomplete="email" '
        'value="&quot; autofocus onfocus=&quot;alert(1)" required'
    ) in text
    assert 'value="\" autofocus onfocus="alert(1)"' not in text


def test_forgot_page_copy(client) -> None:
    text = client.get("/-/forgot_password").text
    assert "Forgot password?" in text
    assert "Enter your email address for instructions" in text
    assert "Send instructions" in text


def test_pricing_tiers(client) -> None:
    text = client.get("/pricing").text
    for tier in ("Personal", "Starter", "Advanced", "Enterprise"):
        assert tier in text


def test_pricing_uses_local_synthetic_help_surface(client) -> None:
    text = client.get("/pricing").text
    assert 'class="synthetic-help"' in text
    assert 'class="synthetic-help" aria-label="Synthetic local help" hidden' in text
    assert 'id="synthetic-help-panel"' in text
    assert 'id="footer-support"' in text
    assert 'aria-label="Close help"' in text
    assert "Synthetic help" in text
    assert "Nothing is sent" in text
    assert "Qualified" not in text
    assert "iframe" not in text.lower()


def test_no_remote_references(client) -> None:
    """No runtime request may leave the local origin."""

    pattern = re.compile(r'(?:src|href)="(https?:)?//(?!127\.0\.0\.1|localhost)')
    for path in [*PUBLIC_PAGES, "/solutions"]:
        assert not pattern.search(client.get(path).text), path
    for asset in ("/static/site.css", "/static/app.css", "/static/app.js",
                  "/static/auth.js"):
        body = client.get(asset).text
        assert "https://" not in body.replace("https://asana.offline", ""), asset


def test_static_assets_served(client) -> None:
    for asset in ("/static/site.css", "/static/app.css", "/static/app.js",
                  "/static/auth.js", "/static/favicon.svg",
                  "/static/source/oat-background.png"):
        assert client.get(asset).status_code == 200, asset


def test_app_requires_auth(client) -> None:
    r = client.get("/app/home", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"].startswith("/-/login")


def test_js_has_no_absolute_remote_fetch(client) -> None:
    """Negative check: client code never targets an absolute remote URL."""

    for asset in ("/static/app.js", "/static/auth.js"):
        body = client.get(asset).text
        assert 'fetch("http' not in body and "fetch('http" not in body, asset
        assert "new WebSocket" not in body, asset


def test_app_icon_paths_have_valid_compact_negative_numbers(client) -> None:
    """A separated minus sign makes Chromium reject the entire SVG path."""

    script = client.get("/static/app.js").text
    assert "-.999-.9532" in script
    assert "-1.002-.9757" in script
    assert "- ." not in script


def test_sanitized_authenticated_navigation_has_local_routes(client) -> None:
    script = client.get("/static/app.js").text
    for path in ("/app/home", "/app/tasks", "/app/tasks/upcoming",
                 "/app/tasks/overdue", "/app/inbox", "/app/projects",
                 "/app/portfolios", "/app/goals", "/app/search",
                 "/app/invite", "/app/agents", "/app/strategy",
                 "/app/knowledge", "/app/people", "/app/more"):
        assert path in script
    for label in ("Home", "My tasks", "Upcoming", "Overdue", "Inbox",
                  "Projects", "Portfolios", "Goals", "Search", "Create",
                  "Invite"):
        assert label in script


def test_authenticated_navigation_avoids_placeholder_interactions(client) -> None:
    script = client.get("/static/app.js").text
    assert 'data-home-demo' not in script
    assert "Project options opened" not in script
    assert "Local widget item selected" not in script
