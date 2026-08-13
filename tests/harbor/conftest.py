"""A synthetic repository that `derive-from-clone` accepts.

Both commands resolve a repository root by walking up for a directory holding
both ``materials/`` and ``harbor/``, so a unit test needs that shape rather than
a bare ``tmp_path``. Everything here is deliberately small: the point is to
exercise the derivation rules, not to mirror the corpus.

The field values below are public local fixtures. Nothing in this file is, or
resembles, a credential.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

from websitebench.harbor.scaffold import initialize_site as initialize_harbor_site
from websitebench.offline_clone.manifest import initialize_site as initialize_clone_site

SITE_ID = "example-shop"

# `catalog.grid` deliberately avoids a `list`/`results`/`search` token: those
# route an expectation to `list_contains` instead of `visible`.
SAMPLE_CHECKS: list[dict[str, object]] = [
    {
        "id": "catalog.home",
        "url": "/",
        "method": "get",
        "expect_status": 200,
        "expect_contains": ["Example Shop"],
    },
    {
        "id": "catalog.grid",
        "url": "/catalog",
        "method": "get",
        "expect_status": 200,
        # One entity-encoded prose string and one attribute fragment: the two
        # cases that must not land in the same required_state key.
        "expect_contains": ["Dogs &amp; Puppies", 'data-product-id="p-1"'],
    },
    {
        "id": "catalog.detail",
        "url": "/catalog/p-1",
        "method": "get",
        "expect_status": 200,
        # A bare identifier token only ever appears inside an attribute.
        "expect_contains": ["rate-dialog"],
        "expect_not_contains": ["Out of stock"],
    },
    {
        "id": "signin.form",
        "url": "/signin",
        "method": "get",
        "expect_status": 200,
        "expect_contains": ["Sign in to Example Shop"],
    },
    {
        "id": "signin.submit",
        "url": "/signin",
        "method": "post",
        "expect_status": 200,
        "data": {"email": "shopper@example.test", "code": "000000"},
        "expect_contains": ["Welcome back"],
    },
]

SIGNIN_TEMPLATE = """<!doctype html>
<html><body>
<form method="post" action="/signin">
  <input name="email">
  <input name="code">
  <button type="submit">Sign in</button>
</form>
</body></html>
"""


@dataclass(frozen=True)
class SyntheticRepo:
    """One clone plus its Harbor site, inside a throwaway repository root."""

    root: Path
    clone_manifest: Path
    clone_root: Path
    site_root: Path

    @property
    def samples(self) -> Path:
        return self.clone_root / "tools" / "frontend_samples.json"

    @property
    def contract(self) -> Path:
        return self.site_root / "interactions" / "opencli-interaction-contract.json"

    def write_samples(self, payload: dict[str, object]) -> None:
        self.samples.parent.mkdir(parents=True, exist_ok=True)
        self.samples.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    def add_instance(self, instance_id: str, *, profile: str | None = None) -> Path:
        """Write the two keys `instances_missing_profile` actually reads.

        An instance names its site by path and carries no `site_id`, which is
        the whole reason that helper resolves ownership through `site_manifest`.
        """

        path = self.root / "harbor" / "instances" / instance_id / "instance.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        data: dict[str, object] = {
            "schema_version": "websitebench.harbor.instance.v2",
            "instance_id": instance_id,
            "site_manifest": f"sites/{SITE_ID}/site.yaml",
        }
        if profile is not None:
            data["opencli_profile"] = profile
        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        return path


@pytest.fixture
def synthetic_repo(tmp_path: Path) -> SyntheticRepo:
    root = tmp_path / "repo"
    (root / "harbor" / "instances").mkdir(parents=True)
    (root / "harbor" / "sites").mkdir(parents=True)

    clone_root = root / "materials" / "example"
    initialize_clone_site(
        clone_root,
        site_id=SITE_ID,
        display_name="Example Shop",
        source_url="https://example.test/",
    )
    clone_manifest = clone_root / "clone.yaml"
    site_root = root / "harbor" / "sites" / SITE_ID
    initialize_harbor_site(site_root, site_id=SITE_ID, display_name="Example Shop")

    template = clone_root / "clone" / "frontend" / "templates" / "signin.html"
    template.parent.mkdir(parents=True, exist_ok=True)
    template.write_text(SIGNIN_TEMPLATE, encoding="utf-8")

    repo = SyntheticRepo(
        root=root,
        clone_manifest=clone_manifest,
        clone_root=clone_root,
        site_root=site_root,
    )
    repo.write_samples({"checks": SAMPLE_CHECKS})
    repo.add_instance(SITE_ID, profile="catalog")
    return repo
