from __future__ import annotations

import json
from pathlib import Path

import pytest

import websitebench.offline_clone.diagnostics as diagnostics
from websitebench.offline_clone.diagnostics import load_site
from websitebench.offline_clone.verify_driver import (
    VerifyDriverError,
    load_verify_driver,
)

from .helpers import configure_passing_diagnostics, initialized_site
from .test_diagnostics import _checkpoint, _checkpoints, _routes


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def test_named_accounts_and_recipe_sessions_bind_each_checkpoint(
    tmp_path: Path,
) -> None:
    root = initialized_site(tmp_path)
    configure_passing_diagnostics(root)
    _routes(
        root,
        [
            {
                "id": "dashboard",
                "route_pattern": "/dashboard",
                "local_destination": True,
            },
            {"id": "settings", "route_pattern": "/settings", "local_destination": True},
            {"id": "home", "route_pattern": "/", "local_destination": True},
        ],
    )
    _checkpoints(
        root,
        [
            _checkpoint("dashboard"),
            _checkpoint("settings"),
            _checkpoint("home", "personalized"),
        ],
    )
    _write(
        root / "scope" / "verify.json",
        {
            "schema_version": "offline-clone.verify-driver.v1",
            "session": {
                "post": "/fixture/session",
                "accounts": {
                    "buyer": {"form": {"actor": "buyer"}, "routes": ["dashboard"]},
                    "seller": {"form": {"actor": "seller"}, "routes": ["settings"]},
                },
            },
            "states": {
                "home.personalized": {"session": "seller", "steps": []},
            },
        },
    )

    site = load_site(root)
    checkpoint_sessions = {
        row.route_id: site.session_for(row) for row in site.checkpoints[-3:]
    }
    assert checkpoint_sessions == {
        "dashboard": "buyer",
        "settings": "seller",
        "home": "seller",
    }
    assert set(site.sessions) == {"buyer", "seller"}


def test_named_session_setup_failure_is_incomplete_and_counted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = initialized_site(tmp_path)
    configure_passing_diagnostics(root)
    _routes(
        root,
        [
            {
                "id": "dashboard",
                "route_pattern": "/dashboard",
                "local_destination": True,
            },
            {
                "id": "settings",
                "route_pattern": "/settings",
                "local_destination": True,
            },
        ],
    )
    _checkpoints(root, [_checkpoint("dashboard"), _checkpoint("settings")])
    _write(
        root / "scope" / "verify.json",
        {
            "schema_version": "offline-clone.verify-driver.v1",
            "session": {
                "post": "/fixture/session",
                "accounts": {
                    "buyer": {"routes": ["dashboard"]},
                    "seller": {"routes": ["settings"]},
                },
            },
        },
    )

    class FakeServer:
        health: dict[str, object] = {}

        def __init__(self, *_: object, **__: object) -> None:
            pass

        def __enter__(self) -> "FakeServer":
            return self

        def __exit__(self, *_: object) -> None:
            pass

    class FakeBrowser:
        def new_context(self) -> object:
            return object()

        def close(self) -> None:
            pass

    class FakePlaywright:
        class Chromium:
            @staticmethod
            def launch(**_: object) -> FakeBrowser:
                return FakeBrowser()

        chromium = Chromium()

    class FakeManager:
        def __enter__(self) -> FakePlaywright:
            return FakePlaywright()

        def __exit__(self, *_: object) -> None:
            pass

    monkeypatch.setattr(diagnostics, "CloneServer", FakeServer)
    monkeypatch.setattr("playwright.sync_api.sync_playwright", lambda: FakeManager())
    monkeypatch.setattr(
        diagnostics,
        "open_session",
        lambda *_: "fixture endpoint refused the account",
    )

    result = diagnostics.run_live(load_site(root))

    assert result.execution_complete is False
    assert result.checks["sessions_requested"] == 2
    assert result.checks["sessions_opened"] == 0
    assert result.checks["sessions_failed"] == 2
    assert result.checks["session_checkpoints_unvisited"] == 2
    assert [finding.check for finding in result.findings] == [
        "session-setup",
        "session-setup",
    ]


def test_goto_step_resolves_a_clone_relative_route() -> None:
    class FakePage:
        url = "http://127.0.0.1:43123/original"

        def __init__(self) -> None:
            self.visits: list[tuple[str, str]] = []
            self.waits: list[int] = []

        def goto(self, url: str, *, wait_until: str) -> None:
            self.visits.append((url, wait_until))

        def wait_for_timeout(self, milliseconds: int) -> None:
            self.waits.append(milliseconds)

    page = FakePage()

    diagnostics._apply_steps(page, [{"goto": "/wizard/step?mode=edit", "wait_ms": 0}])

    assert page.visits == [
        ("http://127.0.0.1:43123/wizard/step?mode=edit", "domcontentloaded")
    ]
    assert page.waits == [0]


def test_declared_read_paths_are_resolved_below_the_site_root(tmp_path: Path) -> None:
    root = initialized_site(tmp_path)
    configured = root / "source-current" / "frozen"
    configured.mkdir(parents=True)
    _write(
        root / "scope" / "verify.json",
        {
            "schema_version": "offline-clone.verify-driver.v1",
            "boot": {"read_paths": ["source-current/frozen"]},
        },
    )

    server = diagnostics.CloneServer(load_site(root), tmp_path / "data")

    assert server._declared_read_paths() == (configured.resolve(),)


def test_declared_read_path_symlink_cannot_escape_site_root(tmp_path: Path) -> None:
    root = initialized_site(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "source-current").symlink_to(outside, target_is_directory=True)
    _write(
        root / "scope" / "verify.json",
        {
            "schema_version": "offline-clone.verify-driver.v1",
            "boot": {"read_paths": ["source-current"]},
        },
    )

    server = diagnostics.CloneServer(load_site(root), tmp_path / "data")

    with pytest.raises(diagnostics.IsolationUnavailable, match="escapes the site root"):
        server._declared_read_paths()


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (
            '{"schema_version":"offline-clone.verify-driver.v1","routes":{},"routes":{}}',
            "duplicate JSON key",
        ),
        (
            json.dumps(
                {
                    "schema_version": "offline-clone.verify-driver.v1",
                    "routes": {"home": "/../outside"},
                }
            ),
            "local absolute route",
        ),
        (
            json.dumps(
                {
                    "schema_version": "offline-clone.verify-driver.v1",
                    "boot": {
                        "argv": ["sh", "-c", "anything"],
                        "cwd": "clone",
                    },
                }
            ),
            r"trusted \{python\}",
        ),
        (
            json.dumps(
                {
                    "schema_version": "offline-clone.verify-driver.v1",
                    "boot": {"env": {"LD_PRELOAD": "/tmp/inject.so"}},
                }
            ),
            "dangerous variable",
        ),
        (
            json.dumps(
                {
                    "schema_version": "offline-clone.verify-driver.v1",
                    "states": {"home.loaded": {"session": "missing", "steps": []}},
                    "session": {
                        "post": "/fixture/session",
                        "accounts": {"known": {"routes": []}},
                    },
                }
            ),
            "undeclared account",
        ),
        (
            json.dumps(
                {
                    "schema_version": "offline-clone.verify-driver.v1",
                    "states": {"home.loaded": [{"goto": "//outside.example/path"}]},
                }
            ),
            "goto must be a local absolute route",
        ),
        (
            json.dumps(
                {
                    "schema_version": "offline-clone.verify-driver.v1",
                    "prepare": [{"goto": "/../outside"}],
                }
            ),
            "goto must be a local absolute route",
        ),
        (
            json.dumps(
                {
                    "schema_version": "offline-clone.verify-driver.v1",
                    "boot": {"read_paths": ["clone/../../outside"]},
                }
            ),
            "read_paths entry must stay within the site root",
        ),
        (
            json.dumps(
                {
                    "schema_version": "offline-clone.verify-driver.v1",
                    "boot": {"env": {"PATH": "clone/bin"}},
                }
            ),
            "dangerous variable",
        ),
    ],
)
def test_verify_driver_rejects_unsafe_or_ambiguous_input(
    tmp_path: Path, payload: str, message: str
) -> None:
    path = tmp_path / "verify.json"
    path.write_text(payload, encoding="utf-8")
    with pytest.raises(VerifyDriverError, match=message):
        load_verify_driver(path)
