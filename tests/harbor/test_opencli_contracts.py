"""Structural guarantees for every OpenCLI interaction contract in the corpus.

These tests never start a server and never invoke the ``opencli`` binary. They
protect the authoring invariants that are easy to break silently: the
site/instance coupling trap, the executable verb set, and the schema shape that
was already wrong once.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from websitebench.harbor.manifest import load_site
from websitebench.harbor.opencli.backends import SUPPORTED_COMMANDS
from websitebench.harbor.opencli.contract import (
    OpenCliContractError,
    load_contract_from_site,
)

ROOT = Path(__file__).resolve().parents[2]
HARBOR = ROOT / "harbor"
SCHEMA = (
    ROOT
    / "websitebench"
    / "schemas"
    / "harbor-opencli-interaction-contract.schema.json"
)


def _sites_with_opencli() -> list[Path]:
    manifests = []
    for manifest in sorted((HARBOR / "sites").glob("*/site.yaml")):
        data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("opencli"), dict):
            manifests.append(manifest)
    return manifests


SITES = _sites_with_opencli()
SITE_IDS = [manifest.parent.name for manifest in SITES]


def test_the_corpus_declares_opencli_contracts() -> None:
    # Guards against the whole suite silently passing on an empty parametrize.
    assert SITE_IDS, "no site declares an opencli block"


@pytest.mark.parametrize("manifest", SITES, ids=SITE_IDS)
def test_contract_loads_and_matches_its_site(manifest: Path) -> None:
    site = load_site(manifest, allow_legacy_v1=True)
    contract = load_contract_from_site(manifest, allow_legacy_v1=True)
    assert contract.site_id == site.data["site_id"]
    assert contract.opencli_version == site.data["opencli"]["version"]
    assert contract.profiles


@pytest.mark.parametrize("manifest", SITES, ids=SITE_IDS)
def test_every_step_is_executable(manifest: Path) -> None:
    contract = load_contract_from_site(manifest, allow_legacy_v1=True)
    for profile_id, profile in contract.profiles.items():
        assert profile.tier in {"p0", "p1"}
        assert profile.network_allowlist, f"{profile_id}: empty network allowlist"
        seen_steps: set[str] = set()
        for step in profile.steps:
            where = f"{manifest.parent.name}/{profile_id}/{step.id}"
            assert step.command in SUPPORTED_COMMANDS, f"{where}: unknown verb"
            assert step.tier in {"p0", "p1"}, f"{where}: unresolved tier"
            assert not step.route.startswith("/"), f"{where}: route must be relative"
            assert ".." not in step.route, f"{where}: route must not traverse"
            assert step.id not in seen_steps, f"{where}: duplicate step id"
            seen_steps.add(step.id)
            # Field overrides only make sense for a form submission.
            if step.fields:
                assert step.command == "submit", f"{where}: fields on a non-submit step"


@pytest.mark.parametrize("manifest", SITES, ids=SITE_IDS)
def test_every_profile_is_loopback_only(manifest: Path) -> None:
    contract = load_contract_from_site(manifest, allow_legacy_v1=True)
    for profile_id, profile in contract.profiles.items():
        assert set(profile.network_allowlist) == {"127.0.0.1", "localhost"}, (
            f"{manifest.parent.name}/{profile_id}: local clone replay must never "
            "authorize an upstream host"
        )


@pytest.mark.parametrize("manifest", SITES, ids=SITE_IDS)
def test_session_preconditions_are_well_formed(manifest: Path) -> None:
    contract = load_contract_from_site(manifest, allow_legacy_v1=True)
    for profile_id, profile in contract.profiles.items():
        if profile.session is None:
            continue
        where = f"{manifest.parent.name}/{profile_id}"
        assert profile.session.method == "POST", f"{where}: session must POST"
        assert not profile.session.route.startswith("/"), f"{where}: relative route"
        assert profile.session.fields, f"{where}: session needs fields"


@pytest.mark.parametrize("manifest", SITES, ids=SITE_IDS)
def test_rendered_text_expectations_carry_no_markup(manifest: Path) -> None:
    """`visible` and `list_contains` are matched against `visibleText(body)`,
    which strips every tag and decodes entities before comparing.

    So an attribute fragment or an encoded entity placed here fails against a
    *perfectly correct* clone — the worst failure this system can produce,
    because it sends the agent to repair something that is not broken. Markup
    belongs in `body_contains`, which matches the raw document.
    """

    rendered_keys = ("visible", "list_contains", "link_text", "text_absent")
    for profile_id, profile in load_contract_from_site(
        manifest, allow_legacy_v1=True
    ).profiles.items():
        for step in profile.steps:
            for key in rendered_keys:
                value = step.required_state.get(key)
                if not isinstance(value, str):
                    continue
                where = f"{manifest.parent.name}/{profile_id}/{step.id}.{key}"
                assert "<" not in value and ">" not in value, (
                    f"{where}: tags are stripped before this is compared; use "
                    "body_contains"
                )
                assert '="' not in value, (
                    f"{where}: attributes are stripped before this is compared; "
                    "use body_contains"
                )
                assert "&amp;" not in value and "&quot;" not in value, (
                    f"{where}: entities are decoded before this is compared; "
                    "write the decoded character"
                )


def test_legacy_instances_of_an_opencli_site_select_a_real_profile() -> None:
    """Historical v1 instances retain their explicitly selected profile.

    Current v2 authoring has one same-id instance per site. Historical v1 task
    records remain immutable compatibility inputs and can still carry one
    profile per old task.
    """

    profiles_by_site = {
        manifest.parent.name: set(
            load_contract_from_site(manifest, allow_legacy_v1=True).profiles
        )
        for manifest in SITES
    }
    checked = 0
    for instance_manifest in sorted((HARBOR / "instances").glob("*/instance.yaml")):
        data = yaml.safe_load(instance_manifest.read_text(encoding="utf-8"))
        site_id = str(data["site_manifest"]).split("/")[1]
        if site_id not in profiles_by_site:
            continue
        checked += 1
        instance_id = instance_manifest.parent.name
        selected = data.get("opencli_profile")
        assert isinstance(selected, str), (
            f"{instance_id}: site {site_id!r} declares opencli, so the instance "
            "must declare opencli_profile"
        )
        assert selected in profiles_by_site[site_id], (
            f"{instance_id}: opencli_profile {selected!r} is not a profile of "
            f"site {site_id!r}"
        )
    assert checked, "no instance belongs to an opencli-enabled site"


def test_current_sites_have_exactly_one_same_id_instance() -> None:
    current_sites = {
        manifest.parent.name
        for manifest in (HARBOR / "sites").glob("*/site.yaml")
        if yaml.safe_load(manifest.read_text(encoding="utf-8")).get("schema_version")
        == "websitebench.harbor.site.v2"
    }
    current_instances = {
        manifest.parent.name
        for manifest in (HARBOR / "instances").glob("*/instance.yaml")
        if yaml.safe_load(manifest.read_text(encoding="utf-8")).get("schema_version")
        == "websitebench.harbor.instance.v2"
    }

    assert current_sites
    assert current_instances == current_sites
    for site_id in sorted(current_sites):
        instance = yaml.safe_load(
            (HARBOR / "instances" / site_id / "instance.yaml").read_text(
                encoding="utf-8"
            )
        )
        assert instance["instance_id"] == site_id
        assert instance["site_manifest"] == f"sites/{site_id}/site.yaml"


def test_step_tier_is_optional_and_inherits_the_profile() -> None:
    """Regression pin: `tier` was required per step while no contract set it."""

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    step = schema["$defs"]["step"]
    assert set(step["required"]) == {"id", "observation_id", "command", "route"}
    assert "tier" in step["properties"]
    assert "tier" in schema["$defs"]["profile"]["required"]

    contract = load_contract_from_site(
        HARBOR / "sites" / "petfinder" / "site.yaml", allow_legacy_v1=True
    )
    profile = contract.profiles["adopter-profile-retry-owner-receipt"]
    assert profile.tier == "p1"
    assert all(step.tier == "p1" for step in profile.steps)


def test_unknown_profile_is_rejected() -> None:
    contract = load_contract_from_site(
        HARBOR / "sites" / "petfinder" / "site.yaml", allow_legacy_v1=True
    )
    with pytest.raises(OpenCliContractError, match="not declared"):
        contract.profile("no-such-profile")
