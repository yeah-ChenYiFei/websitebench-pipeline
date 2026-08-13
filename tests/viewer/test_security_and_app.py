from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from websitebench.viewer import discovery as discovery_module
from websitebench.viewer.app import create_app
from websitebench.viewer.auth import AuthSettings, LoginLimiter, hash_password
from websitebench.viewer.reviews import DIMENSIONS
from websitebench.viewer.publish import publish_static_site


REPO_ROOT = Path(__file__).resolve().parents[2]


def application(tmp_path: Path, *, profile: str = "internal"):
    return create_app(
        REPO_ROOT,
        profile=profile,
        settings=AuthSettings(
            username="reviewer",
            password_hash=hash_password("strong-password-123"),
            session_secret="test-secret-" * 4,
            cookie_secure=False,
        ),
        review_root=tmp_path / "reviews",
        review_session_root=tmp_path / "review-sessions",
        evidence_root=tmp_path / "visual",
    )


def login(client: TestClient) -> str:
    page = client.get("/login")
    token_match = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
    assert token_match is not None
    token = token_match.group(1)
    response = client.post(
        "/login",
        data={
            "username": "reviewer",
            "password": "strong-password-123",
            "csrf_token": token,
            "next_path": "/",
        },
    )
    assert response.status_code == 200
    home = client.get("/")
    csrf_match = re.search(r'name="csrf-token" content="([^"]+)"', home.text)
    assert csrf_match is not None
    return csrf_match.group(1)


def review_body() -> dict:
    return {
        "expected_revision": 0,
        "review": {
            "reviewer": "reviewer",
            "decision": "approve",
            "visibility": "internal",
            "dimensions": {
                name: {"rating": "pass", "notes": "ok", "evidence_refs": []}
                for name in DIMENSIONS
            },
            "notes": "ok",
            "evidence_refs": [],
        },
    }


def review_finding_body(*, expected_revision: int = 0) -> dict:
    return {
        "expected_revision": expected_revision,
        "finding": {
            "severity": "p1",
            "category": "responsive",
            "target": {
                "checkpoint": "home-desktop",
                "viewport": "desktop",
                "route": "/",
                "role": "anonymous",
                "state": "loaded",
            },
            "observation": "The result card overflows the viewport.",
            "expected": "The card should remain inside the content column.",
            "evidence_refs": ["artifacts/visual/home-desktop.png"],
        },
    }


def test_deployment_auth_settings_load_all_secrets_from_files(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    values = {
        "WEBSITEBENCH_VIEWER_USERNAME": "reviewer",
        "WEBSITEBENCH_VIEWER_PASSWORD_HASH": hash_password("strong-password-123"),
        "WEBSITEBENCH_VIEWER_SESSION_SECRET": "deployment-secret-" * 3,
        "WEBSITEBENCH_VIEWER_TRUSTED_HOSTS": "atlas.example.test,localhost",
    }
    for name, value in values.items():
        path = tmp_path / name.lower()
        path.write_text(value, encoding="utf-8")
        monkeypatch.setenv(f"{name}_FILE", str(path))
        monkeypatch.delenv(name, raising=False)
    settings = AuthSettings.from_env()
    assert settings.username == "reviewer"
    assert settings.trusted_hosts == ("atlas.example.test", "localhost")


def test_deployment_auth_settings_keep_explicit_legacy_env_aliases(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("CLAWBENCH_VIEWER_USERNAME", "legacy-reviewer")
    monkeypatch.setenv(
        "CLAWBENCH_VIEWER_PASSWORD_HASH",
        hash_password("strong-password-123"),
    )
    monkeypatch.setenv(
        "CLAWBENCH_VIEWER_SESSION_SECRET",
        "legacy-deployment-secret-" * 2,
    )
    settings = AuthSettings.from_env()
    assert settings.username == "legacy-reviewer"


def test_login_limiter_blocks_after_configured_failures() -> None:
    limiter = LoginLimiter(attempts=2, window_seconds=300)
    assert limiter.allowed("client")
    limiter.failure("client")
    assert limiter.allowed("client")
    limiter.failure("client")
    assert not limiter.allowed("client")
    limiter.success("client")
    assert limiter.allowed("client")


def test_auth_redirect_security_headers_and_core_pages(tmp_path: Path) -> None:
    with TestClient(application(tmp_path)) as client:
        redirect = client.get("/", follow_redirects=False)
        assert redirect.status_code == 303
        assert redirect.headers["location"].startswith("/login")
        login(client)
        for path in (
            "/",
            "/tasks",
            "/tasks/offlineclone--amazon-shopping-mainline",
            "/models",
            "/results",
            "/compare",
            "/methodology",
        ):
            response = client.get(path)
            assert response.status_code == 200
            assert "default-src 'self'" in response.headers["content-security-policy"]
            assert response.headers["x-frame-options"] == "DENY"
        tasks = client.get("/tasks").text
        assert tasks.count("data-task-row") == len(
            client.app.state.corpus_index.items
        )
        assert "Agent runs" in tasks
        assert "Legacy checks" not in tasks
        amazon = client.get(
            "/tasks/offlineclone--amazon-shopping-mainline"
        ).text
        assert "Route & state explorer" in amazon
        assert "Journey replay" in amazon
        assert "Agent experiment not started" in amazon
        assert "Diagnostics unavailable" in amazon


def test_review_csrf_revision_and_export(tmp_path: Path) -> None:
    with TestClient(application(tmp_path)) as client:
        csrf = login(client)
        key = "offlineclone--amazon-shopping-mainline"
        assert client.put(f"/api/reviews/{key}", json=review_body()).status_code == 403
        saved = client.put(
            f"/api/reviews/{key}",
            json=review_body(),
            headers={"X-CSRF-Token": csrf},
        )
        assert saved.status_code == 200
        assert saved.json()["revision"] == 1
        stale = client.put(
            f"/api/reviews/{key}",
            json=review_body(),
            headers={"X-CSRF-Token": csrf},
        )
        assert stale.status_code == 409
        exported = client.get("/api/reviews/export")
        assert exported.status_code == 200
        assert (
            exported.json()["schema_version"]
            == "websitebench.viewer-review-export.v3"
        )
        assert len(exported.json()["reviews"]) == 1


def test_review_mode_finding_lifecycle_and_export(tmp_path: Path) -> None:
    with TestClient(application(tmp_path)) as client:
        csrf = login(client)
        key = "offlineclone--amazon-shopping-mainline"
        page = client.get(f"/tasks/{key}")
        assert "Review Mode" in page.text
        assert "data-fingerprint" not in page.text

        current = client.get(f"/api/review-mode/{key}")
        assert current.status_code == 200
        assert current.json()["revision"] == 0
        body = review_finding_body()
        assert client.post(f"/api/review-mode/{key}/findings", json=body).status_code == 403

        saved = client.post(
            f"/api/review-mode/{key}/findings",
            json=body,
            headers={"X-CSRF-Token": csrf},
        )
        assert saved.status_code == 200
        session = saved.json()
        assert session["revision"] == 1
        assert session["findings"][0]["status"] == "open"
        finding_id = session["findings"][0]["finding_id"]

        stale = client.post(
            f"/api/review-mode/{key}/findings",
            json=body,
            headers={"X-CSRF-Token": csrf},
        )
        assert stale.status_code == 409

        updated = client.patch(
            f"/api/review-mode/{key}/findings/{finding_id}",
            json={
                "expected_revision": 1,
                "finding": {
                    "status": "resolved",
                    "resolution": {
                        "summary": "Constrained the card to its grid column.",
                        "evidence_refs": ["artifacts/visual/home-desktop-after.png"],
                    },
                },
            },
            headers={"X-CSRF-Token": csrf},
        )
        assert updated.status_code == 200
        assert updated.json()["revision"] == 2
        assert updated.json()["findings"][0]["status"] == "resolved"

        exported = client.get("/api/review-mode/export", params={"item_key": key})
        assert exported.status_code == 200
        assert (
            exported.json()["schema_version"]
            == "websitebench.viewer-review-session-export.v1"
        )
        assert len(exported.json()["sessions"]) == 1


def test_public_profile_disables_writes_and_artifacts(tmp_path: Path) -> None:
    with TestClient(application(tmp_path, profile="public")) as client:
        csrf = login(client)
        key = "offlineclone--amazon-shopping-mainline"
        response = client.put(
            f"/api/reviews/{key}",
            json=review_body(),
            headers={"X-CSRF-Token": csrf},
        )
        assert response.status_code == 403
        assert client.get(f"/api/review-mode/{key}").status_code == 403
        assert client.get(f"/clone/{key}/").status_code == 404
        assert client.get(f"/artifacts/{key}/anything.png").status_code == 404
        assert "Review Mode" not in client.get(f"/tasks/{key}").text


def test_compare_deduplicates_and_ignores_unknown_items(tmp_path: Path) -> None:
    app = application(tmp_path)
    with TestClient(app) as client:
        login(client)
        keys = [item["key"] for item in app.state.corpus_index.items]
        selected = keys[:4]
        assert client.get(
            "/compare", params=[("items", key) for key in selected]
        ).status_code == 200
        too_many = client.get(
            "/compare", params=[("items", key) for key in [*selected, selected[0]]]
        )
        # De-duplication keeps the selection within the comparison cap.
        assert too_many.status_code == 200
        assert client.get(
            "/compare",
            params=[("items", key) for key in [*selected, "missing--one"]],
        ).status_code == 200
        if len(keys) > 4:
            assert client.get(
                "/compare", params=[("items", key) for key in keys[:5]]
            ).status_code == 400


def test_public_static_publish_includes_scalable_catalog_routes(tmp_path: Path) -> None:
    output = tmp_path / "site"
    manifest = publish_static_site(REPO_ROOT, output)
    assert manifest["items"] == 1
    assert (output / "index.html").is_file()
    assert (output / "tasks" / "index.html").is_file()
    assert (
        output
        / "tasks"
        / "offlineclone--amazon-shopping-mainline"
        / "index.html"
    ).is_file()
    assert (output / "amazon" / "index.html").is_file()
    assert (output / "models" / "index.html").is_file()
    assert (output / "results" / "index.html").is_file()
    assert (
        output / "static" / "showcase" / "amazon" / "clone-home.png"
    ).is_file()
    assert (output / "static" / "favicon.svg").is_file()
    html = (output / "index.html").read_text(encoding="utf-8")
    assert "Can an agent rebuild a website" in html
    assert "Agent experiments · not started" in html
    assert 'name="csrf-token" content=""' in html
    assert 'href="/static/styles.css"' in html
    assert 'src="/static/app.js"' in html
    assert 'rel="icon" href="/static/favicon.svg"' in html
    assert 'property="og:image" content="/static/og-v2.png"' in html
    assert 'href="/amazon"' in html
    assert 'href="/tasks/offlineclone--amazon-shopping-mainline"' not in html
    assert "http://testserver" not in html
    assert "Sign out" not in html
    amazon_html = (output / "amazon" / "index.html").read_text(encoding="utf-8")
    assert "Route & state explorer" in amazon_html
    assert "Amazon Shopping" in amazon_html
    assert " style=" not in amazon_html
    models_html = (output / "models" / "index.html").read_text(encoding="utf-8")
    assert " style=" not in models_html


def test_amazon_detail_fails_soft_when_acceptance_evidence_is_unavailable(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    artifact_root = (
        REPO_ROOT / "materials" / "amazon" / "artifacts" / "offline-clone"
    ).resolve()
    summary_path = (REPO_ROOT / "materials" / "amazon" / "viewer-public.json").resolve()
    read_json = discovery_module._read_json

    def without_acceptance_evidence(path: Path) -> tuple[object | None, str | None]:
        resolved = path.resolve()
        if (
            resolved == summary_path
            or resolved == artifact_root
            or artifact_root in resolved.parents
        ):
            return None, "simulated unavailable acceptance evidence"
        return read_json(path)

    monkeypatch.setattr(discovery_module, "_read_json", without_acceptance_evidence)
    with TestClient(application(tmp_path)) as client:
        login(client)
        response = client.get("/tasks/offlineclone--amazon-shopping-mainline")
    assert response.status_code == 200
    assert "Diagnostics unavailable" in response.text
    assert "Diagnostic evidence remains pending" in response.text
    assert "Evidence pending" in response.text
