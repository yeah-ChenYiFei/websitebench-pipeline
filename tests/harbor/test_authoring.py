from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest
import yaml

from websitebench.harbor.cli import main
from websitebench.harbor.manifest import HarborManifestError, load_instance, load_site
from websitebench.harbor.materialize import materialize_instance
from websitebench.harbor.policy import AUTH_CHECKOUT_REQUIRED_NODES
from websitebench.harbor.scaffold import initialize_instance, initialize_site


def _authoring_corpus(tmp_path: Path) -> tuple[Path, Path, Path]:
    corpus = tmp_path / "harbor"
    site_dir = corpus / "sites" / "demo-store"
    instance_dir = corpus / "instances" / "demo-store-rebuild"
    (corpus / "instances").mkdir(parents=True)
    site_manifest = initialize_site(
        site_dir,
        site_id="demo-store",
        display_name="Demo Store",
        legacy_v1=True,
    )
    instance_manifest = initialize_instance(
        instance_dir,
        instance_id="demo-store-rebuild",
        site_manifest="sites/demo-store/site.yaml",
        author_name="Benchmark Team",
        author_email="bench@example.test",
        legacy_v1=True,
    )
    return corpus, site_manifest, instance_manifest


def test_scaffolds_form_a_valid_fullstack_instance(tmp_path: Path) -> None:
    corpus, site_path, instance_path = _authoring_corpus(tmp_path)

    site = load_site(site_path, allow_legacy_v1=True)
    instance = load_instance(instance_path, allow_legacy_v1=True)

    assert site.data["schema_version"] == "websitebench.harbor.site.v1"
    assert instance.data["schema_version"] == "websitebench.harbor.instance.v1"
    assert instance.corpus_root == corpus.resolve()
    assert instance.site.path == site.path
    assert site.data["schema_version"] == "websitebench.harbor.site.v1"
    assert instance.data["schema_version"] == "websitebench.harbor.instance.v1"
    assert site.data["runtime"]["agent_browser"] == "browser-use-cli"
    assert site.data["runtime"]["formal_browser"] == "playwright"
    assert sum(site.data["scoring"]["dimensions"].values()) == 100
    assert len(instance.data["tests"]["api"]) >= 2
    assert len(instance.data["tests"]["ui"]) >= 2
    for dimension, nodes in AUTH_CHECKOUT_REQUIRED_NODES.items():
        assert set(nodes) <= set(instance.data["tests"][dimension])


def test_historical_harbor_schema_names_remain_read_compatible(
    tmp_path: Path,
) -> None:
    _, site_path, instance_path = _authoring_corpus(tmp_path)
    site = yaml.safe_load(site_path.read_text(encoding="utf-8"))
    site["schema_version"] = "clawbench.harbor.site.v1"
    site_path.write_text(yaml.safe_dump(site, sort_keys=False), encoding="utf-8")
    instance = yaml.safe_load(instance_path.read_text(encoding="utf-8"))
    instance["schema_version"] = "clawbench.harbor.instance.v1"
    instance_path.write_text(
        yaml.safe_dump(instance, sort_keys=False), encoding="utf-8"
    )

    assert load_site(site_path, allow_legacy_v1=True).data["site_id"] == "demo-store"
    assert load_instance(instance_path, allow_legacy_v1=True).data["instance_id"] == (
        "demo-store-rebuild"
    )


def test_legacy_reads_are_never_implicit(tmp_path: Path) -> None:
    _, site_path, instance_path = _authoring_corpus(tmp_path)
    with pytest.raises(HarborManifestError, match="allow_legacy_v1=True"):
        load_site(site_path)
    with pytest.raises(HarborManifestError, match="allow_legacy_v1=True"):
        load_instance(instance_path)
    with pytest.raises(HarborManifestError, match="allow_legacy_v1=True"):
        materialize_instance(instance_path, tmp_path / "implicit-legacy")


def test_scaffold_identity_must_match_normalized_directory(tmp_path: Path) -> None:
    destination = tmp_path / "different-name"
    with pytest.raises(ValueError, match="directory name"):
        initialize_site(
            destination,
            site_id="demo-store",
            display_name="Demo Store",
            legacy_v1=True,
        )
    assert not destination.exists()


def test_current_instance_must_share_its_site_id(tmp_path: Path) -> None:
    corpus = tmp_path / "harbor"
    (corpus / "instances").mkdir(parents=True)
    initialize_site(corpus / "sites" / "demo", site_id="demo", display_name="Demo")

    with pytest.raises(ValueError, match="exactly one same-id instance"):
        initialize_instance(
            corpus / "instances" / "demo-rebuild",
            instance_id="demo-rebuild",
            site_manifest="sites/demo/site.yaml",
            author_name="Benchmark Team",
            author_email="bench@example.test",
        )


def test_current_corpus_requires_one_instance_for_every_site(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    corpus = tmp_path / "harbor"
    (corpus / "instances").mkdir(parents=True)
    initialize_site(corpus / "sites" / "demo", site_id="demo", display_name="Demo")

    assert main(["validate-corpus", "--corpus-root", str(corpus)]) == 2
    assert "no instances" in capsys.readouterr().err

    initialize_instance(
        corpus / "instances" / "demo",
        instance_id="demo",
        site_manifest="sites/demo/site.yaml",
        author_name="Benchmark Team",
        author_email="bench@example.test",
    )
    initialize_site(
        corpus / "sites" / "legacy-demo",
        site_id="legacy-demo",
        display_name="Legacy Demo",
        legacy_v1=True,
    )
    initialize_instance(
        corpus / "instances" / "legacy-demo-task",
        instance_id="legacy-demo-task",
        site_manifest="sites/legacy-demo/site.yaml",
        author_name="Benchmark Team",
        author_email="bench@example.test",
        legacy_v1=True,
    )
    assert main(["validate-corpus", "--corpus-root", str(corpus)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["current_site_instance_pairs"] == 1
    assert report["sites"] == report["instances"] == 1
    assert report["legacy_sites"] == report["legacy_instances"] == 1


def test_semantics_reject_visibility_overlap_bad_prefixes_and_weak_complexity(
    tmp_path: Path,
) -> None:
    _, site_path, instance_path = _authoring_corpus(tmp_path)
    site = yaml.safe_load(site_path.read_text(encoding="utf-8"))
    site["paths"]["verifier"] = "public/verifier"
    (site_path.parent / "public" / "verifier").mkdir()
    site_path.write_text(yaml.safe_dump(site, sort_keys=False), encoding="utf-8")
    with pytest.raises(HarborManifestError, match="overlap"):
        load_site(site_path, allow_legacy_v1=True)

    site["paths"]["verifier"] = "verifier"
    site_path.write_text(yaml.safe_dump(site, sort_keys=False), encoding="utf-8")
    instance = yaml.safe_load(instance_path.read_text(encoding="utf-8"))
    instance["tests"]["api"] = ["ui::wrong/prefix"]
    instance_path.write_text(
        yaml.safe_dump(instance, sort_keys=False),
        encoding="utf-8",
    )
    with pytest.raises(HarborManifestError, match="at least 2|must start with"):
        load_instance(instance_path, allow_legacy_v1=True)


def test_semantics_reject_missing_platform_auth_checkout_node(tmp_path: Path) -> None:
    _, _, instance_path = _authoring_corpus(tmp_path)
    instance = yaml.safe_load(instance_path.read_text(encoding="utf-8"))
    missing = AUTH_CHECKOUT_REQUIRED_NODES["api"][0]
    instance["tests"]["api"].remove(missing)
    instance_path.write_text(
        yaml.safe_dump(instance, sort_keys=False),
        encoding="utf-8",
    )

    with pytest.raises(
        HarborManifestError,
        match="missing platform-required auth/checkout node",
    ):
        load_instance(instance_path, allow_legacy_v1=True)


def test_materialize_enforces_visibility_and_is_reproducible(
    tmp_path: Path,
) -> None:
    _, site_path, instance_path = _authoring_corpus(tmp_path)
    (site_path.parent / "public" / "api-contract.json").write_text(
        '{"public": true}\n',
        encoding="utf-8",
    )
    (site_path.parent / "verifier" / "secret-check.py").write_text(
        "REFERENCE_ONLY_EXPECTATION = True\n",
        encoding="utf-8",
    )
    (instance_path.parent / "public" / "starter.py").write_text(
        "STARTER = True\n",
        encoding="utf-8",
    )

    output = materialize_instance(
        instance_path,
        tmp_path / "dist" / "demo-store-rebuild",
        allow_legacy_v1=True,
    )

    assert (output / "environment/seed/starter.py").is_file()
    assert (output / "environment/seed/.websitebench/site/api-contract.json").is_file()
    assert not (output / "environment/seed/.websitebench/site/secret-check.py").exists()
    assert (output / "environment/reference/server.py").is_file()
    assert (output / "tests/reference/server.py").is_file()
    assert (output / "tests/site/secret-check.py").is_file()
    assert (output / "tests/platform-auth-checkout-policy.json").is_file()
    assert (output / "tests/platform_auth_checkout_gate.py").is_file()
    assert "platform_auth_checkout_gate.py" in (output / "tests/test.sh").read_text(
        encoding="utf-8"
    )
    assert (
        output / "environment/seed/.websitebench/auth-checkout-policy.json"
    ).is_file()
    assert (output / "solution/solve.sh").is_file()
    task = tomllib.loads((output / "task.toml").read_text(encoding="utf-8"))
    assert task["schema_version"] == "1.4"
    assert task["artifacts"] == ["/app/repo"]
    assert task["verifier"]["environment_mode"] == "separate"
    assert task["metadata"]["task_type"] == "fullstack-reconstruction"
    assert task["environment"]["memory_mb"] == 8192
    compose = yaml.safe_load(
        (output / "environment/docker-compose.yaml").read_text(encoding="utf-8")
    )
    assert compose["services"]["main"]["depends_on"]["reference"]["condition"] == (
        "service_healthy"
    )
    assert (
        compose["services"]["main"]["environment"]["WEBSITEBENCH_REFERENCE_URL"]
        == "http://reference:8080"
    )
    assert "expose" not in compose["services"]["reference"]

    bundle = json.loads((output / "bundle-manifest.json").read_text(encoding="utf-8"))
    assert bundle["schema_version"] == "websitebench.harbor.bundle.v1"
    entries = {entry["path"]: entry for entry in bundle["files"]}
    assert entries["environment/seed/starter.py"]["visibility"] == "agent-public"
    assert entries["environment/Dockerfile"]["visibility"] == "build-control"
    assert entries["tests/site/secret-check.py"]["visibility"] == "verifier-only"
    assert (
        entries["environment/reference/server.py"]["visibility"]
        == "reference-sidecar-only"
    )
    assert entries["solution/solve.sh"]["visibility"] == "oracle-only"
    assert all(
        entry["bytes"] == (output / entry["path"]).stat().st_size
        for entry in entries.values()
    )
    assert all("sha256" not in entry for entry in entries.values())
    assert "chmod 755 /app/repo/run.sh" in (
        output / "environment/Dockerfile"
    ).read_text(encoding="utf-8")
    assert task["task"]["name"].startswith("websitebench/")
    verifier_dockerfile = (output / "tests/Dockerfile").read_text(encoding="utf-8")
    assert "Acquire::Retries=5" in verifier_dockerfile
    assert "Acquire::http::Timeout=30" in verifier_dockerfile

    with pytest.raises(FileExistsError, match="already exists"):
        materialize_instance(instance_path, output, allow_legacy_v1=True)


def test_cli_init_validate_materialize_and_corpus(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    corpus = tmp_path / "harbor"
    site = corpus / "sites" / "shop"
    instance = corpus / "instances" / "shop-rebuild"
    (corpus / "instances").mkdir(parents=True)

    assert (
        main(
            [
                "init-site",
                "--site-dir",
                str(site),
                "--site-id",
                "shop",
                "--display-name",
                "Shop",
                "--legacy-v1",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert (
        main(
            [
                "init-instance",
                "--instance-dir",
                str(instance),
                "--instance-id",
                "shop-rebuild",
                "--site-manifest",
                "sites/shop/site.yaml",
                "--author-name",
                "Benchmark Team",
                "--author-email",
                "bench@example.test",
                "--legacy-v1",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert main(["validate", "--instance", str(instance), "--legacy-v1"]) == 0
    expected_nodes = 8 + sum(
        len(nodes) for nodes in AUTH_CHECKOUT_REQUIRED_NODES.values()
    )
    assert json.loads(capsys.readouterr().out)["test_nodes"] == expected_nodes
    assert main(["validate-corpus", "--corpus-root", str(corpus), "--legacy-v1"]) == 0
    assert json.loads(capsys.readouterr().out)["instances"] == 1
    output = tmp_path / "bundle"
    assert (
        main(
            [
                "materialize",
                "--instance",
                str(instance),
                "--out",
                str(output),
                "--legacy-v1",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["status"] == "materialized"
