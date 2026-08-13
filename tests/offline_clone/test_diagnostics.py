"""The two generic sections, and the data that drives them.

The live section needs a booted clone and a browser, so it is exercised against
real sites by `websitebench-offline-clone verify`. What is unit-testable here
is everything that decides *what* the live section will do: which path a
checkpoint resolves to, which states are declared, which routes are out of
anonymous reach -- plus what the static section makes of a candidate's files.
"""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from websitebench.offline_clone.cli import main as offline_clone_main
from websitebench.offline_clone.diagnostics import (
    DIAGNOSTIC_SECTIONS,
    load_site,
    run_static,
    verify,
)
from websitebench.offline_clone.manifest import load_manifest

from .helpers import add_closed_png_asset, configure_passing_diagnostics, initialized_site


def _driver(root: Path, **body: object) -> None:
    payload = {"schema_version": "offline-clone.verify-driver.v1", **body}
    (root / "scope" / "verify.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )


def _checkpoint(route_id: str, state: str = "loaded") -> dict[str, object]:
    return {
        "id": f"{route_id}.{state}.desktop",
        "route_id": route_id,
        "state": state,
        "viewport": "desktop",
        "priority": "p0",
        "evidence_kind": "direct",
    }


def _checkpoints(root: Path, rows: list[dict[str, object]]) -> None:
    """Append rows. The scaffold's own visual checkpoint answers the coverage
    ledger's visual dimension, so replacing it would fail validation for a
    reason that has nothing to do with what is under test."""

    path = root / "scope" / "checkpoints.json"
    ledger = json.loads(path.read_text(encoding="utf-8"))
    ledger["checkpoints"] = [*ledger["checkpoints"], *rows]
    path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")


def _routes(root: Path, rows: list[dict[str, object]]) -> None:
    path = root / "scope" / "routes.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["routes"] = rows
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _page(root: Path, name: str, markup: str) -> None:
    path = root / "clone" / "frontend" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markup, encoding="utf-8")


def test_there_are_exactly_two_sections() -> None:
    assert DIAGNOSTIC_SECTIONS == ("static", "live")


def test_a_diagnostic_section_separates_findings_from_observations() -> None:

    from websitebench.offline_clone.diagnostics import Finding, SectionResult

    result = SectionResult(section="live", site_id="example")
    result.notes.append(Finding("visual-similarity", "0.71 below 0.8", "home.desktop"))

    assert result.execution_complete is True
    assert result.as_dict()["observations"][0]["check"] == "visual-similarity"

    result.findings.append(Finding("route-status", "/x answered 404", "x"))
    assert result.execution_complete is True
    assert result.as_dict()["findings"][0]["check"] == "route-status"


def test_static_section_passes_a_closed_candidate(tmp_path: Path) -> None:
    root = initialized_site(tmp_path)
    configure_passing_diagnostics(root)
    add_closed_png_asset(root)

    result = run_static(load_site(root))

    assert result.execution_complete is True
    assert result.findings == []
    assert result.checks["remote_references"] == 0


def test_static_section_reports_a_runtime_load_from_a_remote_host(tmp_path: Path) -> None:
    root = initialized_site(tmp_path)
    configure_passing_diagnostics(root)
    add_closed_png_asset(root)
    _page(root, "leak.html", '<script src="https://cdn.example.com/a.js"></script>\n')

    result = run_static(load_site(root))

    assert result.execution_complete is True
    assert [finding.check for finding in result.findings] == ["remote-reference"]
    assert "cdn.example.com" in result.findings[0].message


def test_static_section_skips_manifest_declared_candidate_excludes(tmp_path: Path) -> None:
    root = initialized_site(tmp_path)
    configure_passing_diagnostics(root)
    add_closed_png_asset(root)
    manifest_path = root / "clone.yaml"
    import yaml

    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["paths"]["candidate_excludes"] = ["node_modules", ".next"]
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    for relative in ("node_modules/a.js", ".next/b.js"):
        path = root / "clone" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('fetch("https://excluded.example.test")', encoding="utf-8")

    result = run_static(load_site(root))

    assert result.findings == []
    assert result.checks["remote_references"] == 0


def test_a_documented_remote_reference_is_not_a_runtime_load(tmp_path: Path) -> None:
    root = initialized_site(tmp_path)
    configure_passing_diagnostics(root)
    add_closed_png_asset(root)
    _page(
        root,
        "note.html",
        '<!-- clawbench-allow-remote-doc src="https://x.test/s" -->\n',
    )

    assert run_static(load_site(root)).findings == []


def test_a_placeholder_link_is_not_a_static_finding(tmp_path: Path) -> None:
    """Real sites ship `href="#"` for scripted controls; a faithful clone copies it."""

    root = initialized_site(tmp_path)
    configure_passing_diagnostics(root)
    add_closed_png_asset(root)
    _page(root, "carousel.html", '<a href="#">Next</a>\n')

    assert run_static(load_site(root)).findings == []


def test_a_declared_alias_beats_the_source_route_pattern(tmp_path: Path) -> None:
    root = initialized_site(tmp_path)
    configure_passing_diagnostics(root)
    _routes(root, [{"id": "home", "route_pattern": "/web", "local_destination": True}])
    _checkpoints(root, [_checkpoint("home")])
    _driver(root, routes={"home": "/"})

    site = load_site(root)

    assert site.checkpoints[-1].path == "/"
    assert site.unresolved_routes == []


def test_a_templated_route_with_no_concrete_path_is_reported(tmp_path: Path) -> None:
    root = initialized_site(tmp_path)
    configure_passing_diagnostics(root)
    add_closed_png_asset(root)
    _routes(
        root,
        [
            {
                "id": "search",
                "route_pattern": "/find?q=<query>",
                "local_destination": True,
            }
        ],
    )
    _checkpoints(root, [_checkpoint("search")])

    result = run_static(load_site(root))

    assert [finding.check for finding in result.findings] == ["route-unresolved"]


def test_a_deferred_route_is_counted_rather_than_visited(tmp_path: Path) -> None:
    root = initialized_site(tmp_path)
    configure_passing_diagnostics(root)
    add_closed_png_asset(root)
    _routes(
        root,
        [{"id": "dashboard", "route_pattern": "/dashboard", "local_destination": True}],
    )
    _checkpoints(root, [_checkpoint("dashboard")])
    _driver(root, deferred={"dashboard": "answers 401 anonymously"})

    site = load_site(root)
    result = run_static(site)

    assert site.checkpoints[-1].path is None
    assert result.findings == []
    assert result.checks["deferred_checkpoints"] == 1


def test_a_state_recipe_is_looked_up_route_first(tmp_path: Path) -> None:
    root = initialized_site(tmp_path)
    configure_passing_diagnostics(root)
    _routes(root, [{"id": "home", "route_pattern": "/", "local_destination": True}])
    _checkpoints(root, [_checkpoint("home", "menu-open")])
    _driver(
        root,
        states={
            "menu-open": [{"click": ".generic"}],
            "home.menu-open": [{"click": ".specific"}],
        },
    )

    site = load_site(root)

    assert site.steps_for(site.checkpoints[-1]) == [{"click": ".specific"}]


def test_live_still_runs_when_static_fails(tmp_path: Path) -> None:
    """Both sections always report: one failing must not blind the other."""

    root = initialized_site(tmp_path)
    configure_passing_diagnostics(root)
    add_closed_png_asset(root)
    _page(root, "leak.html", '<img src="https://cdn.example.com/a.png">\n')

    report = verify(root, ("static",))

    assert report["schema_version"] == "offline-clone.diagnostic-report.v1"
    assert report["diagnostic_status"] == "findings"
    assert report["authority"] == "diagnostic-only"
    assert report["qualification"] == "maintainer-judgment-required"
    assert list(report["sections"]) == ["static"]

    schema_path = (
        Path(__file__).resolve().parents[2]
        / "websitebench/schemas/offline-clone-diagnostic-report.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(report)
    bundled_schema = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "src/websitebench/viewer/_schemas/offline-clone-diagnostic-report.schema.json"
        ).read_text(encoding="utf-8")
    )
    assert bundled_schema == schema
    assert list(Draft202012Validator(schema).iter_errors({**report, "sections": {}}))


def test_cli_findings_are_advisory_but_incomplete_execution_exits_two(
    tmp_path: Path,
) -> None:
    root = initialized_site(tmp_path)
    configure_passing_diagnostics(root)
    add_closed_png_asset(root)
    _page(root, "leak.html", '<img src="https://cdn.example.com/a.png">\n')
    findings_report = tmp_path / "findings.json"

    assert (
        offline_clone_main(
            [
                "verify",
                "--site",
                str(root),
                "--section",
                "static",
                "--out",
                str(findings_report),
            ]
        )
        == 0
    )
    assert (
        json.loads(findings_report.read_text(encoding="utf-8"))["diagnostic_status"]
        == "findings"
    )

    (root / "scope/verify.json").write_text("{}\n", encoding="utf-8")
    incomplete_report = tmp_path / "incomplete.json"
    assert (
        offline_clone_main(
            [
                "verify",
                "--site",
                str(root),
                "--section",
                "static",
                "--out",
                str(incomplete_report),
            ]
        )
        == 2
    )
    assert (
        json.loads(incomplete_report.read_text(encoding="utf-8"))["diagnostic_status"]
        == "incomplete"
    )


def test_verify_stores_no_result(tmp_path: Path) -> None:
    """A result is printed, not remembered, so no stale pass can survive."""

    root = initialized_site(tmp_path)
    configure_passing_diagnostics(root)
    add_closed_png_asset(root)

    verify(root, ("static",))

    assert not (root / ".clone-harness").exists()


def test_the_manifest_has_no_retired_gate_declaration(tmp_path: Path) -> None:
    root = initialized_site(tmp_path)
    configure_passing_diagnostics(root)

    assert "gates" not in load_manifest(root).data
