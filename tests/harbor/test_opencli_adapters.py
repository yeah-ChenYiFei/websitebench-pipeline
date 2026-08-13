"""The committed adapters must stay identical to what the generator emits.

`websitebench-harbor opencli-adapters --check` enforces this on demand; this
test enforces it in CI so the committed JavaScript cannot rot away from the
templates it came from.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest
import yaml

from websitebench.harbor.opencli import adapters
from websitebench.harbor.opencli.contract import load_contract_from_site

ROOT = Path(__file__).resolve().parents[2]
HARBOR = ROOT / "harbor"


def _sites_with_adapters() -> list[Path]:
    manifests = []
    for manifest in sorted((HARBOR / "sites").glob("*/site.yaml")):
        data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("opencli"), dict):
            manifests.append(manifest)
    return manifests


SITES = _sites_with_adapters()
SITE_IDS = [manifest.parent.name for manifest in SITES]


@pytest.mark.parametrize("manifest", SITES, ids=SITE_IDS)
def test_committed_adapters_match_the_generator(manifest: Path) -> None:
    contract = load_contract_from_site(manifest, allow_legacy_v1=True)
    data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    rendered = adapters.render_for_contract(contract, str(data["display_name"]))
    destination = manifest.parent / "interactions" / "adapters"
    problems = adapters.check(rendered, destination)
    assert not problems, "\n".join(problems)


@pytest.mark.parametrize("manifest", SITES, ids=SITE_IDS)
def test_adapters_declare_the_headless_contract(manifest: Path) -> None:
    """`browser: false` and `access:` are both load-bearing.

    Getting `browser` backwards silently makes every argument fall back to its
    default, and OpenCLI refuses to load a command with no `access`.
    """

    contract = load_contract_from_site(manifest, allow_legacy_v1=True)
    data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    rendered = adapters.render_for_contract(contract, str(data["display_name"]))
    expected_access = {
        "state.js": "'read'",
        "click.js": "'write'",
        "submit.js": "'write'",
    }
    for name, access in expected_access.items():
        source = rendered[name]
        assert "browser: false," in source, f"{name}: must be headless"
        assert f"access: {access}," in source, f"{name}: wrong access declaration"
        assert f"site: 'wb-{contract.site_id}'," in source, f"{name}: wrong namespace"
        assert "Strategy.LOCAL," in source, f"{name}: must use the LOCAL strategy"


def _assertable_keys(source: str) -> set[str]:
    body = source.split("const ASSERTABLE = new Set([")[1].split("]);")[0]
    return {
        line.strip().rstrip(",").strip("'")
        for line in body.splitlines()
        if line.strip()
    }


def test_body_contains_is_assertable_and_reads_the_raw_document() -> None:
    """Derivation routes attribute and markup expectations to `body_contains`
    because `visible` is compared against text with every tag stripped. If this
    key ever slipped out of `ASSERTABLE`, those expectations would silently
    become descriptive prose and no derived step could fail on them."""

    rendered = adapters.render("demo", "Demo Site")
    assert "body_contains" in _assertable_keys(rendered["_wb.js"])

    # Raw markup, not the tag-stripped text — that is the entire point of the
    # key. `withoutCode` drops script and style bodies, which are not document
    # content and would otherwise match on noise.
    case = rendered["_wb.js"].split("case 'body_contains':")[1].split("case ")[0]
    assert "withoutCode(page.body)" in case
    assert "script|style" in rendered["_wb.js"]


def test_namespace_prefix_avoids_shadowing_official_adapters() -> None:
    """OpenCLI ships official `amazon` and `imdb` site adapters.

    An unprefixed directory under ~/.opencli/clis/ would silently override them.
    """

    assert adapters.adapter_site_name("amazon") == "wb-amazon"
    assert adapters.NAMESPACE_PREFIX == "wb-"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")
@pytest.mark.parametrize(
    ("base", "route", "expected"),
    [
        (
            "http://127.0.0.1:8080",
            "search?q=desk",
            "http://127.0.0.1:8080/search?q=desk",
        ),
        (
            "https://localhost:8443/prefix/",
            "/state",
            "https://localhost:8443/prefix/state",
        ),
    ],
)
def test_adapter_helper_accepts_only_loopback_routes(
    tmp_path: Path, base: str, route: str, expected: str
) -> None:
    """Direct adapter calls cannot bypass the runner's target allowlist."""

    source = adapters.render("demo", "Demo Site")["_wb.js"].replace(
        "import { ArgumentError, CommandExecutionError } from '@jackwener/opencli/errors';",
        "class ArgumentError extends Error {}\nclass CommandExecutionError extends Error {}",
    )
    helper = tmp_path / "_wb.mjs"
    helper.write_text(source, encoding="utf-8")
    script = (
        f"import {{ resolveRoute }} from {json.dumps(helper.as_uri())};"
        f"console.log(resolveRoute({json.dumps(base)}, {json.dumps(route)}));"
    )
    result = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == expected


@pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")
@pytest.mark.parametrize(
    ("base", "route"),
    [
        ("https://example.com", "state"),
        ("http://127.0.0.1.evil.example", "state"),
        ("file:///tmp/clone", "state"),
        ("http://user:secret@127.0.0.1:8080", "state"),
        ("http://127.0.0.1:8080?next=evil", "state"),
        ("http://127.0.0.1:8080", "https://example.com/state"),
        ("http://127.0.0.1:8080", "\\\\example.com/state"),
        ("http://127.0.0.1:8080", " state"),
    ],
)
def test_adapter_helper_rejects_non_loopback_or_escaping_targets(
    tmp_path: Path, base: str, route: str
) -> None:
    source = adapters.render("demo", "Demo Site")["_wb.js"].replace(
        "import { ArgumentError, CommandExecutionError } from '@jackwener/opencli/errors';",
        "class ArgumentError extends Error {}\nclass CommandExecutionError extends Error {}",
    )
    helper = tmp_path / "_wb.mjs"
    helper.write_text(source, encoding="utf-8")
    script = (
        f"import {{ resolveRoute }} from {json.dumps(helper.as_uri())};"
        f"resolveRoute({json.dumps(base)}, {json.dumps(route)});"
    )
    result = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "ArgumentError" in result.stderr


def test_generator_reports_missing_files_as_drift(tmp_path: Path) -> None:
    rendered = adapters.render("demo", "Demo Site")
    problems = adapters.check(rendered, tmp_path)
    assert len(problems) == len(rendered)
    assert all("missing" in problem for problem in problems)

    adapters.write(rendered, tmp_path)
    assert adapters.check(rendered, tmp_path) == []

    (tmp_path / "state.js").write_text("tampered\n", encoding="utf-8")
    problems = adapters.check(rendered, tmp_path)
    assert len(problems) == 1
    assert "differs from the generator output" in problems[0]
