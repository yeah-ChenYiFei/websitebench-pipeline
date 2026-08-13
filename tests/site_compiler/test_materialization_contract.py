from __future__ import annotations

import importlib
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

import websitebench.site_compiler as site_compiler
from websitebench.offline_clone.backend_model import validate_backend_model
from websitebench.offline_clone.manifest import load_manifest
from websitebench.site_compiler.compile import CompilationResult, CompilerWorkspace
from websitebench.site_compiler.diagnostics import SiteCompilerError

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "generic-v2"
INVENTORY = FIXTURE_ROOT / "platform-inventory.json"
PROFILES = FIXTURE_ROOT / "profiles"
PACKS = REPO_ROOT / "websitebench" / "capability-packs"
PROOF_OBLIGATIONS = {
    "valid",
    "invalid",
    "duplicate",
    "stale",
    "foreign-owner",
    "unauthorized-role",
    "restart",
    "migration",
    "concurrency",
}


def _workspace() -> CompilerWorkspace:
    return CompilerWorkspace.load(inventory_path=INVENTORY, packs_root=PACKS)


def _unblocked_target(tmp_path: Path) -> tuple[CompilationResult, dict[str, Any]]:
    profile = json.loads(
        (PROFILES / "alpha-market/site.json").read_text(encoding="utf-8")
    )
    profile_path = tmp_path / "profile" / "alpha-market" / "site.json"
    profile_path.parent.mkdir(parents=True)
    profile_path.write_text(
        json.dumps(profile, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return (
        _workspace().compile(profile_path=profile_path, target="scope"),
        profile,
    )


def _materialize(
    result: CompilationResult,
    site_dir: Path,
) -> Any:
    function = getattr(site_compiler, "materialize_compilation", None)
    assert callable(function), (
        "site compiler must export materialize_compilation("
        "result, site_dir, *, stage='scope')"
    )
    return function(
        result,
        site_dir,
        stage="scope",
    )


def _json_documents(root: Path) -> Iterator[tuple[Path, Any]]:
    for path in sorted(root.rglob("*.json"), key=lambda item: item.as_posix()):
        yield path, json.loads(path.read_text(encoding="utf-8"))
    for path in sorted(root.rglob("*.jsonl"), key=lambda item: item.as_posix()):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                yield path, json.loads(line)


def _walk_json(value: Any) -> Iterator[tuple[str, Any]]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield key, child
            yield from _walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json(child)


def _tree_contents(root: Path) -> list[tuple[str, bytes | None]]:
    contents: list[tuple[str, bytes | None]] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(root).as_posix()
        if path.is_dir():
            contents.append((relative + "/", None))
        else:
            contents.append((relative, path.read_bytes()))
    return contents


def _assert_no_direct_claims(*roots: Path) -> None:
    for root in roots:
        for path, document in _json_documents(root):
            for key, value in _walk_json(document):
                if key in {"evidence_tier", "source_tier"}:
                    assert value != "direct", (
                        f"scope materialization invented a direct source claim in {path}"
                    )


def test_scope_materialization_creates_a_compatible_planned_skeleton(
    tmp_path: Path,
) -> None:
    result, source_profile = _unblocked_target(tmp_path)
    site_dir = tmp_path / "alpha-market"
    _materialize(result, site_dir)

    manifest = load_manifest(site_dir)
    assert manifest.data["site_id"] == "alpha-market"
    assert manifest.data["paths"]["backend_model"] == "backend/model.json"
    assert {
        "clone/frontend",
        "clone/backend",
        "clone/static",
        "scope",
        "source-assets",
    } <= {
        path.relative_to(site_dir).as_posix()
        for path in site_dir.rglob("*")
        if path.is_dir()
    }

    backend = json.loads(
        (site_dir / "backend/model.json").read_text(encoding="utf-8")
    )
    assert backend == result.plan["site_ir"]["backend_model_seed"]
    assert validate_backend_model(
        backend,
        expected_site_id="alpha-market",
        require_verified=False,
    ) == []
    assert backend["capabilities"]
    for capability in backend["capabilities"]:
        assert capability["implementation_status"] == "planned"
        assert capability["proofs"]["evidence"] == {}
        assert set(capability["proofs"]["planned"]) == PROOF_OBLIGATIONS

    compiler_root = site_dir / "artifacts/site-compiler"
    assert json.loads(
        (compiler_root / "alpha-market.compiled.json").read_text(encoding="utf-8")
    ) == result.plan
    assert not (compiler_root / "alpha-market.lock.json").exists()
    assert json.loads(
        (compiler_root / "alpha-market.explain.json").read_text(encoding="utf-8")
    ) == result.explanation

    copied_inputs = [
        document
        for path, document in _json_documents(compiler_root / "inputs")
        if path.is_file()
    ]
    assert source_profile in copied_inputs

    assert (site_dir / "scope/claims.jsonl").read_bytes() == b""
    _assert_no_direct_claims(site_dir)

    # Scope materialization creates only the contract skeleton. No executable
    # backend or database may appear before the bounded implementation phase.
    assert not any((site_dir / "clone/backend").rglob("*"))
    assert not (site_dir / "clone/clawbench").exists()
    assert not list(site_dir.rglob("*.sqlite*"))


def test_blocked_profile_fails_before_creating_any_destination(
    tmp_path: Path,
) -> None:
    result = _workspace().compile(
        profile_path=PROFILES / "beta-learning" / "site.json",
        target="scope",
    )
    assert result.plan["site_ir"]["blockers"]
    site_dir = tmp_path / "beta-learning"

    with pytest.raises(SiteCompilerError, match="block"):
        _materialize(result, site_dir)

    assert not site_dir.exists()


@pytest.mark.parametrize("prepopulate", [False, True])
def test_materialization_refuses_every_preexisting_site_directory(
    tmp_path: Path,
    prepopulate: bool,
) -> None:
    result, _ = _unblocked_target(tmp_path)
    site_dir = tmp_path / "alpha-market"
    site_dir.mkdir()
    if prepopulate:
        (site_dir / "owned-by-user.txt").write_text("preserve me", encoding="utf-8")
    before = _tree_contents(site_dir)

    with pytest.raises(FileExistsError, match="exist|overwrite"):
        _materialize(result, site_dir)

    assert _tree_contents(site_dir) == before


def test_scope_materialization_is_byte_deterministic(tmp_path: Path) -> None:
    result, _ = _unblocked_target(tmp_path)
    first_site = tmp_path / "first/site"
    second_site = tmp_path / "second/site"

    _materialize(result, first_site)
    _materialize(result, second_site)

    assert _tree_contents(first_site) == _tree_contents(second_site)


def test_materialization_check_detects_compiler_owned_drift(
    tmp_path: Path,
) -> None:
    result, _ = _unblocked_target(tmp_path)
    site_dir = tmp_path / "alpha-market"
    _materialize(result, site_dir)

    check = getattr(site_compiler, "check_materialization", None)
    assert callable(check)
    current = check(result, site_dir)
    assert current["status"] == "current"

    backend_model = site_dir / "backend/model.json"
    backend_model.write_text("{}\n", encoding="utf-8")
    with pytest.raises(SiteCompilerError, match="drifted"):
        check(result, site_dir)


def test_materialization_never_removes_a_concurrent_writers_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, _ = _unblocked_target(tmp_path)
    site_dir = tmp_path / "alpha-market"
    module = importlib.import_module("websitebench.site_compiler.materialize")
    original_replace = module.os.replace

    def race(source: Path, destination: Path) -> None:
        if Path(destination) == site_dir:
            site_dir.mkdir()
            (site_dir / "foreign.txt").write_text(
                "concurrent writer",
                encoding="utf-8",
            )
            raise FileExistsError("simulated concurrent materializer")
        original_replace(source, destination)

    monkeypatch.setattr(module.os, "replace", race)
    with pytest.raises(FileExistsError, match="concurrent"):
        _materialize(result, site_dir)

    assert (site_dir / "foreign.txt").read_text(encoding="utf-8") == (
        "concurrent writer"
    )
