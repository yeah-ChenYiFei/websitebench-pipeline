"""Derivation rules, exercised against a synthetic clone rather than the corpus.

Two of these guard mistakes that would produce a contract which fails against a
*correct* clone — the worst possible failure mode, because it sends the agent to
repair something that is not broken:

* an attribute fragment routed to `visible`, which is matched against text with
  every tag stripped;
* an entity-encoded expectation left encoded, which `visibleText` has already
  decoded by the time the comparison happens.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from websitebench.harbor import derive
from websitebench.harbor.opencli.contract import load_contract_from_site

from .conftest import SAMPLE_CHECKS, SIGNIN_TEMPLATE, SyntheticRepo

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def derived(synthetic_repo: SyntheticRepo) -> SyntheticRepo:
    derive.run_derive(clone_manifest=synthetic_repo.clone_manifest)
    return synthetic_repo


def _steps(repo: SyntheticRepo, profile: str) -> dict[str, dict[str, object]]:
    contract = json.loads(repo.contract.read_text(encoding="utf-8"))
    return {step["id"]: step for step in contract["profiles"][profile]["steps"]}


def _derive_only(repo: SyntheticRepo) -> derive.Derivation:
    """Derivation without the write path, for rules that need no side effects."""

    binding = derive.bind_clone(repo.clone_manifest)
    return derive.derive_contract(
        site_id=binding.site_id,
        manifest_root=binding.manifest_root,
        manifest_data=binding.manifest_data,
    )


def test_derivation_produces_a_loadable_schema_valid_contract(
    derived: SyntheticRepo,
) -> None:
    payload = json.loads(derived.contract.read_text(encoding="utf-8"))
    assert derive.validate_payload(payload, derive.CONTRACT_SCHEMA, "contract") == []
    assert payload["generated_from"] == "materials/example/clone.yaml"

    contract = load_contract_from_site(
        derived.site_root / "site.yaml", allow_legacy_v1=True
    )
    assert set(contract.profiles) == {"catalog", "signin"}


def test_markup_expectations_never_become_visible(derived: SyntheticRepo) -> None:
    catalog = _steps(derived, "catalog")

    grid = catalog["catalog-grid"]["required_state"]
    assert grid["body_contains"] == 'data-product-id="p-1"'
    assert "=" not in str(grid["visible"])

    # A bare hyphenated identifier reads as prose but only ever lives in an
    # attribute, so `visibleText` would never surface it.
    detail = catalog["catalog-detail"]["required_state"]
    assert detail["body_contains"] == "rate-dialog"
    assert "visible" not in detail


def test_entities_are_decoded_for_visible_expectations(derived: SyntheticRepo) -> None:
    grid = _steps(derived, "catalog")["catalog-grid"]["required_state"]
    assert grid["visible"] == "Dogs & Puppies"


def test_every_assertion_key_is_one_the_adapters_can_fail(
    derived: SyntheticRepo,
) -> None:
    from websitebench.harbor.opencli import adapters

    shared = (Path(adapters.__file__).parent / "templates" / "_wb.js").read_text(
        encoding="utf-8"
    )
    contract = json.loads(derived.contract.read_text(encoding="utf-8"))
    for profile in contract["profiles"].values():
        for step in profile["steps"]:
            for key in step["required_state"]:
                assert f"'{key}'" in shared, f"{key} is not an adapter assertion key"


def test_the_site_root_is_unrepresentable_and_is_recorded_not_dropped(
    derived: SyntheticRepo,
) -> None:
    routes = {
        step["route"]
        for profile in json.loads(derived.contract.read_text(encoding="utf-8"))[
            "profiles"
        ].values()
        for step in profile["steps"]
    }
    assert "" not in routes

    unresolved = [
        item
        for item in _derive_only(derived).pending
        if item.kind == "unresolved-route"
    ]
    assert any("catalog.home" in item.detail for item in unresolved)


def test_submit_selector_comes_only_from_a_unique_template_form(
    synthetic_repo: SyntheticRepo,
) -> None:
    unique = _derive_only(synthetic_repo)
    submit = unique.contract["profiles"]["signin"]["steps"][-1]
    assert submit["command"] == "submit"
    assert submit["selector"] == 'form[action="/signin"]'

    # A second template declaring the same action makes the selector ambiguous.
    duplicate = (
        synthetic_repo.clone_root / "clone" / "frontend" / "templates" / "modal.html"
    )
    duplicate.write_text(SIGNIN_TEMPLATE, encoding="utf-8")

    ambiguous = _derive_only(synthetic_repo)
    commands = {
        step["command"] for step in ambiguous.contract["profiles"]["signin"]["steps"]
    }
    assert commands == {"state"}, "an ambiguous form must not yield a submit step"
    assert any(
        item.kind == "selector" and "signin.submit" in item.detail
        for item in ambiguous.pending
    )


def test_a_post_route_that_is_not_a_gettable_page_yields_no_submit_step(
    synthetic_repo: SyntheticRepo,
) -> None:
    """A submit step GETs its route first, so a POST-only endpoint cannot work."""

    checks = [dict(check) for check in SAMPLE_CHECKS]
    for check in checks:
        if check["id"] == "signin.submit":
            check["url"] = "/api/signin"
    synthetic_repo.write_samples({"checks": checks})

    derivation = _derive_only(synthetic_repo)
    commands = {
        step["command"] for step in derivation.contract["profiles"]["signin"]["steps"]
    }
    assert commands == {"state"}
    assert any(
        item.kind == "selector" and "/api/signin" in item.detail
        for item in derivation.pending
    )


def test_a_session_needing_headers_is_refused_not_silently_emitted(
    synthetic_repo: SyntheticRepo,
) -> None:
    """An emitted session that silently 403s is worse than no session at all."""

    synthetic_repo.write_samples(
        {
            "session_setup": {
                "url": "/fixture/session",
                "method": "post",
                "data": {"email": "shopper@example.test"},
                "headers": {"X-WebsiteBench-Admin-Token": "local-fixture"},
            },
            "checks": [{**check, "session": True} for check in SAMPLE_CHECKS],
        }
    )

    with pytest.raises(derive.DerivationError):
        # Every check needs the session, so nothing is derivable — but the
        # refusal must still be visible rather than a silent empty contract.
        _derive_only(synthetic_repo)

    pending: list[derive.Pending] = []
    session = derive._session_block(
        json.loads(synthetic_repo.samples.read_text(encoding="utf-8")), pending
    )
    assert session is None
    assert [item.kind for item in pending] == ["session-headers"]
    assert "requires 1 custom header(s)" in pending[0].detail


def test_a_plain_form_session_is_derived_and_attached_to_its_profile(
    synthetic_repo: SyntheticRepo,
) -> None:
    checks = [dict(check) for check in SAMPLE_CHECKS]
    for check in checks:
        if check["id"].startswith("signin."):
            check["session"] = True
    synthetic_repo.write_samples(
        {
            "session_setup": {
                "url": "/fixture/session",
                "method": "post",
                "data": {"email": "shopper@example.test"},
            },
            "checks": checks,
        }
    )

    profiles = _derive_only(synthetic_repo).contract["profiles"]
    assert profiles["signin"]["session"]["route"] == "fixture/session"
    assert profiles["signin"]["session"]["method"] == "POST"
    assert "session" not in profiles["catalog"]


def test_derivation_is_byte_deterministic_across_hash_seeds(
    synthetic_repo: SyntheticRepo,
) -> None:
    """`render_for_contract` reads `{{SAMPLE_ROUTE}}` from the first step of the
    first profile, so any set-ordering leak into the emitted order would show up
    as spurious adapter drift between runs."""

    outputs = []
    for seed in ("0", "1", "12345"):
        environment = {**os.environ, "PYTHONHASHSEED": seed}
        subprocess.run(
            [
                sys.executable,
                "-m",
                "websitebench.harbor.cli",
                "derive-from-clone",
                "--clone-manifest",
                str(synthetic_repo.clone_manifest),
                "--force",
            ],
            check=True,
            capture_output=True,
            cwd=ROOT,
            env=environment,
        )
        outputs.append(
            (
                synthetic_repo.contract.read_bytes(),
                (
                    synthetic_repo.site_root / "interactions" / "adapters" / "state.js"
                ).read_bytes(),
            )
        )
    assert outputs[0] == outputs[1] == outputs[2]


def test_derivation_needs_no_stored_diagnostic_state(
    synthetic_repo: SyntheticRepo,
) -> None:
    result = derive.run_derive(clone_manifest=synthetic_repo.clone_manifest)

    assert result["status"] == "derived"
    assert synthetic_repo.contract.is_file()
    assert "pending" in result
    assert not (synthetic_repo.site_root / "interactions" / "derivation.json").exists()


def test_an_instance_without_a_profile_blocks_the_opencli_block(
    synthetic_repo: SyntheticRepo,
) -> None:
    """The unique instance must select one generated interaction profile."""

    instance_path = (
        synthetic_repo.root / "harbor" / "instances" / "example-shop" / "instance.yaml"
    )
    instance = yaml.safe_load(instance_path.read_text("utf-8"))
    instance.pop("opencli_profile")
    instance_path.write_text(yaml.safe_dump(instance, sort_keys=False), "utf-8")

    with pytest.raises(derive.DerivationError, match="example-shop"):
        derive.run_derive(clone_manifest=synthetic_repo.clone_manifest)

    # Nothing was written: the site is exactly as it was.
    assert not synthetic_repo.contract.exists()
    site = yaml.safe_load((synthetic_repo.site_root / "site.yaml").read_text("utf-8"))
    assert "opencli" not in site

    derive.run_derive(
        clone_manifest=synthetic_repo.clone_manifest,
        assign_profile={"example-shop": "catalog"},
    )
    instance = yaml.safe_load(instance_path.read_text("utf-8"))
    assert instance["opencli_profile"] == "catalog"


def test_current_derivation_rejects_a_second_instance_for_the_site(
    synthetic_repo: SyntheticRepo,
) -> None:
    synthetic_repo.add_instance("example-shop-covered", profile="catalog")

    with pytest.raises(derive.DerivationError, match="exactly one same-id instance"):
        derive.run_derive(clone_manifest=synthetic_repo.clone_manifest)


def test_current_profile_assignment_cannot_mutate_another_instance(
    synthetic_repo: SyntheticRepo,
) -> None:
    with pytest.raises(derive.DerivationError, match="unique same-id instance"):
        derive.run_derive(
            clone_manifest=synthetic_repo.clone_manifest,
            assign_profile={"another-site": "catalog"},
        )


def test_an_existing_contract_is_never_overwritten_without_force(
    derived: SyntheticRepo,
) -> None:
    before = derived.contract.read_bytes()
    with pytest.raises(derive.DerivationError, match="already exists"):
        derive.run_derive(clone_manifest=derived.clone_manifest)
    assert derived.contract.read_bytes() == before
