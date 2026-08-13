from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

from websitebench.runtime_isolation import (
    IsolationUnavailable,
    clean_candidate_environment,
    launch_candidate,
    prepare_data_directory,
)


@pytest.mark.skipif(sys.platform != "linux", reason="kernel sandbox is Linux-only")
def test_candidate_environment_does_not_inherit_secrets_or_loader_injection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "host-secret")
    monkeypatch.setenv("PYTHONPATH", "/host/injection")
    monkeypatch.setenv("LD_PRELOAD", "/host/injection.so")
    prepare_data_directory(tmp_path)
    first = clean_candidate_environment(tmp_path, port=12345)
    second = clean_candidate_environment(tmp_path, port=12345)

    assert "AWS_SECRET_ACCESS_KEY" not in first
    assert "PYTHONPATH" not in first
    assert "LD_PRELOAD" not in first
    assert first["WEBSITEBENCH_ISOLATION_ID"] != second["WEBSITEBENCH_ISOLATION_ID"]


@pytest.mark.skipif(sys.platform != "linux", reason="kernel sandbox is Linux-only")
def test_candidate_cannot_write_host_or_escape_network_and_tree_is_cleaned(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = tmp_path / "candidate"
    data = tmp_path / "data"
    candidate.mkdir()
    prepare_data_directory(data)
    host = tmp_path / "host-owned"
    host.write_text("unchanged", encoding="utf-8")
    other_data = tmp_path / "other-task-data"
    prepare_data_directory(other_data)
    other_secret = other_data / "secret"
    other_secret.write_text("other-task", encoding="utf-8")
    injected = tmp_path / "loader-injection"
    injected.mkdir()
    loader_marker = tmp_path / "loader-ran"
    (injected / "sitecustomize.py").write_text(
        f"open({str(loader_marker)!r}, 'w').write('loaded')\n", encoding="utf-8"
    )
    monkeypatch.setenv("PYTHONPATH", str(injected))
    script = candidate / "probe.py"
    script.write_text(
        "import json, os, socket, sqlite3, time\n"
        "result = {}\n"
        f"host = {str(host)!r}\n"
        "try:\n    open(host, 'w').write('changed')\n    result['host_write'] = False\n"
        "except PermissionError:\n    result['host_write'] = True\n"
        f"other_secret = {str(other_secret)!r}\n"
        "try:\n    open(other_secret).read()\n    result['cross_task_read'] = False\n"
        "except PermissionError:\n    result['cross_task_read'] = True\n"
        "try:\n    open(other_secret, 'w').write('changed')\n    result['cross_task_write'] = False\n"
        "except PermissionError:\n    result['cross_task_write'] = True\n"
        "try:\n    socket.create_connection(('1.1.1.1', 443), timeout=.2)\n    result['network'] = False\n"
        "except OSError:\n    result['network'] = True\n"
        "try:\n    os.fork()\n    result['fork'] = False\n"
        "except PermissionError:\n    result['fork'] = True\n"
        "database_path = os.path.join(os.environ['WEBSITEBENCH_DATA_DIR'], 'state.sqlite3')\n"
        "for index in range(80):\n"
        "    with sqlite3.connect(database_path) as database:\n"
        "        database.execute('PRAGMA journal_mode=WAL')\n"
        "        database.execute('CREATE TABLE IF NOT EXISTS state (value INTEGER)')\n"
        "        database.execute('INSERT INTO state VALUES (?)', (index,))\n"
        "result['sqlite_reopen'] = True\n"
        "open(os.path.join(os.environ['WEBSITEBENCH_DATA_DIR'], 'result.json'), 'w').write(json.dumps(result))\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )
    environment = clean_candidate_environment(data, port=31337)
    process = launch_candidate(
        [sys.executable, str(script)],
        candidate_root=candidate,
        data_dir=data,
        bind_port=31337,
        environment=environment,
    )
    result = data / "result.json"
    deadline = time.monotonic() + 10
    while not result.is_file() and time.monotonic() < deadline:
        time.sleep(0.02)
    stderr = process.stderr_tail(4000)
    process.terminate_tree()

    assert host.read_text("utf-8") == "unchanged"
    assert other_secret.read_text("utf-8") == "other-task"
    assert not loader_marker.exists()
    assert result.is_file(), stderr
    assert __import__("json").loads(result.read_text("utf-8")) == {
        "cross_task_read": True,
        "cross_task_write": True,
        "fork": True,
        "host_write": True,
        "network": True,
        "sqlite_reopen": True,
    }
    with pytest.raises(ProcessLookupError):
        os.kill(process.process.pid, 0)


@pytest.mark.skipif(sys.platform != "linux", reason="kernel sandbox is Linux-only")
def test_candidate_read_mount_cannot_escape_through_a_symbolic_link(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "site" / "clone"
    data = tmp_path / "data"
    candidate.mkdir(parents=True)
    prepare_data_directory(data)
    outside = tmp_path / "host-private"
    outside.mkdir()
    escaped = candidate.parent / "scope"
    escaped.symlink_to(outside, target_is_directory=True)

    with pytest.raises(IsolationUnavailable, match="symbolic link"):
        launch_candidate(
            [sys.executable, "-c", "raise SystemExit(0)"],
            candidate_root=candidate,
            data_dir=data,
            bind_port=31339,
            environment=clean_candidate_environment(data, port=31339),
            read_paths=(escaped,),
        )


@pytest.mark.skipif(sys.platform != "linux", reason="kernel sandbox is Linux-only")
def test_isolated_python_can_import_trusted_editable_launcher(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate"
    data = tmp_path / "data"
    candidate.mkdir()
    prepare_data_directory(data)
    marker = data / "imported"
    command = (
        "from pathlib import Path; "
        "import websitebench.offline_clone.node_launcher; "
        "Path(__import__('os').environ['WEBSITEBENCH_DATA_DIR'], 'imported').write_text('ok')"
    )

    process = launch_candidate(
        [sys.executable, "-I", "-c", command],
        candidate_root=candidate,
        data_dir=data,
        bind_port=31340,
        environment=clean_candidate_environment(data, port=31340),
    )
    process.process.wait(timeout=10)
    stderr = process.stderr_tail(4000)
    process.terminate_tree()

    assert marker.read_text(encoding="utf-8") == "ok", stderr
