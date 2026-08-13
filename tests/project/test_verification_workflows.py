from __future__ import annotations

from pathlib import Path

import pytest

from websitebench.harbor.derive import clone_manifests


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = REPOSITORY_ROOT / ".github" / "workflows"


def present_sites() -> list[str]:
    """The site directories this checkout actually carries.

    Discovery replaces the site tuple that used to live here. A checkout with
    one site is as valid as a checkout with twelve, and retiring a site is
    deleting its material rather than editing a list two directories away.
    """
    return [manifest.parent.name for manifest in clone_manifests(REPOSITORY_ROOT)]


def workflow(name: str) -> str:
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def test_deployment_runs_shared_diagnostics() -> None:
    # Every site deploys through one reusable workflow, so verification is
    # asserted once there rather than per legacy per-site deployer. There is no
    # tier to select any more: `verify` runs the static and live sections.
    template = workflow("public-demo-site.yml")
    assert "offline_clone.cli verify" in template
    assert "materials/${{ inputs.site }}" in template
    assert "--tier" not in template


def test_the_shared_clone_diagnostics_run_only_the_site_it_is_handed() -> None:
    template = workflow("clone-diagnostics.yml")
    assert "workflow_call:" in template
    assert "offline_clone.cli verify" in template
    assert "github.event.pull_request.base.sha || github.sha" not in template
    assert "Install the current checkout" in template
    assert "materials/${SITE_ID}" in template
    assert "Upload diagnostic report" in template
    assert "diagnostic-only" in template
    assert "diagnostic_exit=$?" in template
    assert "if: always()" in template
    assert "exit 0" in template
    assert "Verify sandbox infrastructure" in template
    assert "--tier" not in template
    # The template must stay a template: no trigger of its own and no way to
    # enumerate sites from inside it.
    assert "workflow_dispatch:" not in template
    assert "matrix:" not in template


@pytest.mark.parametrize("site", present_sites())
def test_each_present_site_owns_its_diagnostics_dispatcher(site: str) -> None:
    entry_point = WORKFLOWS / f"tests-{site}.yml"
    assert entry_point.is_file(), f"missing diagnostics workflow for {site}"

    dispatcher = entry_point.read_text(encoding="utf-8")
    assert "uses: ./.github/workflows/clone-diagnostics.yml" in dispatcher
    assert f"site: {site}\n" in dispatcher
    # The dispatcher must react to its own material.
    assert f"- materials/{site}/**" in dispatcher
    assert "matrix:" not in dispatcher


@pytest.mark.parametrize(
    "entry_point",
    sorted(WORKFLOWS.glob("deploy-*-public.yml")),
    ids=lambda path: path.name,
)
def test_each_explicit_deploy_dispatcher_targets_an_existing_site(
    entry_point: Path,
) -> None:
    site = entry_point.name.removeprefix("deploy-").removesuffix("-public.yml")
    dispatcher = entry_point.read_text(encoding="utf-8")
    assert "public-demo-site.yml" in dispatcher
    assert f"site: {site}\n" in dispatcher
    assert "matrix:" not in dispatcher


def test_the_shared_test_workflow_carries_no_site_list() -> None:
    # A site list here would go stale and silently omit diagnostics.
    shared = workflow("tests.yml")
    assert "pull_request:" in shared
    assert "github.event.pull_request.base.sha || github.sha" not in shared
    assert "path: trusted-verifier" not in shared
    assert "working-directory: trusted-verifier" not in shared
    assert "persist-credentials: false" in shared
    assert "pull_request_target:" not in shared
    assert "secrets:" not in shared
    assert "matrix:" not in shared
    assert "materials/" not in shared
    assert "--tier" not in shared
