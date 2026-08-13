from __future__ import annotations

import os
from pathlib import Path

import pytest

from websitebench.offline_clone import node_launcher


@pytest.mark.parametrize(
    ("profile", "target", "tail"),
    [
        (
            "vinext",
            "node_modules/vinext/dist/cli.js",
            [
                "--max-old-space-size=768",
                "--v8-pool-size=2",
                "node_modules/vinext/dist/cli.js",
                "start",
                "--hostname",
                "127.0.0.1",
                "--port",
                "43123",
            ],
        ),
        ("next-standalone", ".next/standalone/server.js", [".next/standalone/server.js"]),
    ],
)
def test_launcher_executes_only_a_fixed_built_server(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    profile: str,
    target: str,
    tail: list[str],
) -> None:
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    script = tmp_path / target
    script.parent.mkdir(parents=True)
    script.write_text("// built", encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_execve(
        executable: str, argv: list[str], environment: dict[str, str]
    ) -> None:
        captured.update(executable=executable, argv=argv, environment=environment)
        raise RuntimeError("exec captured")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(node_launcher.shutil, "which", lambda _: "/usr/bin/node")
    monkeypatch.setattr(node_launcher.os, "execve", fake_execve)

    with pytest.raises(RuntimeError, match="exec captured"):
        node_launcher.launch(profile, 43123)

    assert captured["executable"] == "/usr/bin/node"
    expected_tail = [str(script) if item == target else item for item in tail]
    assert captured["argv"] == ["/usr/bin/node", *expected_tail]
    environment = captured["environment"]
    assert isinstance(environment, dict)
    assert environment["HOST"] == "127.0.0.1"
    assert environment["PORT"] == "43123"
    assert environment["RAYON_NUM_THREADS"] == "2"
    assert environment["UV_THREADPOOL_SIZE"] == "4"


def test_launcher_rejects_missing_or_escaping_built_script(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    with pytest.raises(node_launcher.NodeLauncherError, match="unavailable"):
        node_launcher.launch("vinext", 43123)


def test_linkedin_profile_executes_prepared_standalone_without_forking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for relative in (
        "package.json",
        ".next/standalone/server.js",
    ):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("{}", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(node_launcher.shutil, "which", lambda _: "/usr/bin/node")
    monkeypatch.setattr(
        node_launcher.os,
        "execve",
        lambda *_: (_ for _ in ()).throw(RuntimeError("exec captured")),
    )

    with pytest.raises(RuntimeError, match="exec captured"):
        node_launcher.launch("next-standalone-linkedin", 43123)

    outside = tmp_path.parent / "outside-cli.js"
    outside.write_text("// outside", encoding="utf-8")
    target = tmp_path / "node_modules/vinext/dist/cli.js"
    target.parent.mkdir(parents=True)
    try:
        target.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")
    with pytest.raises(node_launcher.NodeLauncherError, match="unsafe"):
        node_launcher.launch("vinext", 43123)


def test_launcher_rejects_unknown_profile_and_port(tmp_path: Path) -> None:
    old = Path.cwd()
    try:
        os.chdir(tmp_path)
        with pytest.raises(node_launcher.NodeLauncherError, match="unsupported"):
            node_launcher.launch("arbitrary-script", 43123)
        with pytest.raises(node_launcher.NodeLauncherError, match="port"):
            node_launcher.launch("vinext", 0)
    finally:
        os.chdir(old)
