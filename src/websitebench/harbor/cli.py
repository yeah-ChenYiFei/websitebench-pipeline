"""Command-line interface for normalized Harbor benchmark authoring."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import yaml

from . import derive as contract_derive
from .capture import capture_reference
from .case_protocol import load_case_manifest, score_case_result_files
from .judge_v2 import score_results
from .bundle_v2 import validate_bundle
from .calibration_v2 import calibrate_bundle
from .manifest import (
    HarborManifestError,
    LEGACY_INSTANCE_SCHEMA_VERSIONS,
    LEGACY_SITE_SCHEMA_VERSIONS,
    find_corpus_root,
    load_instance,
    load_site,
    resolve_inside,
)
from .materialize import materialize_instance
from .opencli import adapters as opencli_adapters
from .opencli import runner as opencli_runner
from .opencli.contract import OpenCliContractError, load_contract_from_site
from .scaffold import initialize_instance, initialize_site


def _emit(value: dict[str, Any]) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True))


def _init_site(args: argparse.Namespace) -> int:
    manifest = initialize_site(
        args.site_dir,
        site_id=args.site_id,
        display_name=args.display_name,
        legacy_v1=args.legacy_v1,
    )
    _emit({"status": "initialized", "kind": "site", "manifest": str(manifest)})
    return 0


def _init_instance(args: argparse.Namespace) -> int:
    corpus_root = find_corpus_root(args.instance_dir.parent)
    load_site(
        resolve_inside(corpus_root, args.site_manifest, must_exist=True),
        allow_legacy_v1=args.legacy_v1,
        allow_legacy_deploy_v2=False,
    )
    manifest = initialize_instance(
        args.instance_dir,
        instance_id=args.instance_id,
        site_manifest=args.site_manifest,
        author_name=args.author_name,
        author_email=args.author_email,
        legacy_v1=args.legacy_v1,
    )
    _emit({"status": "initialized", "kind": "instance", "manifest": str(manifest)})
    return 0


def _validate(args: argparse.Namespace) -> int:
    instance = load_instance(
        args.instance,
        corpus_root=args.corpus_root,
        allow_legacy_v1=args.legacy_v1,
        allow_legacy_deploy_v2=args.legacy_deploy_v2,
    )
    payload: dict[str, Any] = {
        "status": "valid",
        "schema_version": instance.data["schema_version"],
        "instance_id": instance.data["instance_id"],
        "site_id": instance.site.data["site_id"],
    }
    if instance.data["schema_version"] == "websitebench.harbor.instance.v2":
        payload["suites"] = {
            kind: instance.data["suites"][kind] for kind in ("task", "visual", "cicd")
        }
        payload["reference_observations"] = instance.data["reference_observations"][
            "status"
        ]
        if "case_manifest" in instance.data:
            _case_manifest, summary = load_case_manifest(
                instance.root / instance.data["case_manifest"],
                allow_draft=True,
                allow_sealed=False,
                expected_site_id=str(instance.site.data["site_id"]),
            )
            payload.update(summary.as_dict())
        else:
            payload["legacy_deploy_v2"] = True
            payload["scorable"] = False
    else:
        payload["test_nodes"] = sum(
            len(nodes) for nodes in instance.data["tests"].values()
        )
    _emit(payload)
    return 0


def _validate_corpus(args: argparse.Namespace) -> int:
    corpus_root = args.corpus_root.resolve()
    all_site_manifests = sorted((corpus_root / "sites").glob("*/site.yaml"))
    all_instance_manifests = sorted((corpus_root / "instances").glob("*/instance.yaml"))

    def _version(path: Path) -> object:
        try:
            value = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
            raise HarborManifestError([f"{path}: cannot read manifest: {exc}"]) from exc
        return value.get("schema_version") if isinstance(value, dict) else None

    legacy_sites = [
        path
        for path in all_site_manifests
        if _version(path) in LEGACY_SITE_SCHEMA_VERSIONS
    ]
    legacy_instances = [
        path
        for path in all_instance_manifests
        if _version(path) in LEGACY_INSTANCE_SCHEMA_VERSIONS
    ]
    site_manifests = (
        all_site_manifests
        if args.legacy_v1
        else [path for path in all_site_manifests if path not in legacy_sites]
    )
    manifests = (
        all_instance_manifests
        if args.legacy_v1
        else [path for path in all_instance_manifests if path not in legacy_instances]
    )
    if not site_manifests:
        raise HarborManifestError(
            [f"{corpus_root}: no sites/*/site.yaml manifests found"]
        )
    if not manifests:
        raise HarborManifestError(
            [f"{corpus_root}: no instances/*/instance.yaml manifests found"]
        )
    sites = [
        load_site(
            path,
            allow_legacy_v1=args.legacy_v1,
            allow_legacy_deploy_v2=args.legacy_deploy_v2,
        )
        for path in site_manifests
    ]
    instances = [
        load_instance(
            path,
            corpus_root=corpus_root,
            allow_legacy_v1=args.legacy_v1,
            allow_legacy_deploy_v2=args.legacy_deploy_v2,
        )
        for path in manifests
    ]
    ids = [instance.data["instance_id"] for instance in instances]
    duplicates = sorted({item for item in ids if ids.count(item) > 1})
    if duplicates:
        raise HarborManifestError(
            [f"duplicate instance_id in corpus: {item}" for item in duplicates]
        )
    site_ids = [site.data["site_id"] for site in sites]
    duplicate_sites = sorted({item for item in site_ids if site_ids.count(item) > 1})
    if duplicate_sites:
        raise HarborManifestError(
            [f"duplicate site_id in corpus: {item}" for item in duplicate_sites]
        )
    declared_site_paths = {site.path for site in sites}
    outside = [
        instance.site.path
        for instance in instances
        if instance.site.path not in declared_site_paths
    ]
    if outside:
        raise HarborManifestError(
            [
                f"instance references a non-corpus site manifest: {path}"
                for path in outside
            ]
        )
    current_sites = {
        str(site.data["site_id"]): site
        for site in sites
        if site.data["schema_version"] == "websitebench.harbor.site.v2"
    }
    current_instances = [
        instance
        for instance in instances
        if instance.data["schema_version"] == "websitebench.harbor.instance.v2"
    ]
    current_instance_sites = [
        str(instance.site.data["site_id"]) for instance in current_instances
    ]
    pairing_problems: list[str] = []
    for site_id in sorted(current_sites):
        count = current_instance_sites.count(site_id)
        if count != 1:
            pairing_problems.append(
                f"current site {site_id!r} must have exactly one same-id instance; "
                f"found {count}"
            )
    for instance in current_instances:
        site_id = str(instance.site.data["site_id"])
        if site_id not in current_sites:
            pairing_problems.append(
                f"current instance {instance.data['instance_id']!r} does not belong "
                "to a current corpus site"
            )
    if pairing_problems:
        raise HarborManifestError(pairing_problems)
    _emit(
        {
            "status": "valid",
            "instances": len(instances),
            "sites": len(sites),
            "current_site_instance_pairs": len(current_sites),
            "legacy_instances": len(legacy_instances),
            "legacy_sites": len(legacy_sites),
        }
    )
    return 0


def _materialize(args: argparse.Namespace) -> int:
    output = materialize_instance(
        args.instance,
        args.out,
        corpus_root=args.corpus_root,
        allow_legacy_v1=args.legacy_v1,
        allow_legacy_deploy_v2=args.legacy_deploy_v2,
    )
    _emit(
        {
            "status": "materialized",
            "output": str(output),
        }
    )
    return 0


def _capture_reference(args: argparse.Namespace) -> int:
    candidate = load_instance(
        args.instance,
        corpus_root=args.corpus_root,
        allow_legacy_deploy_v2=args.legacy_deploy_v2,
    )
    if "case_manifest" in candidate.data:
        _manifest, summary = load_case_manifest(
            candidate.root / candidate.data["case_manifest"],
            allow_draft=True,
            allow_sealed=False,
            expected_site_id=str(candidate.site.data["site_id"]),
        )
        if not summary.scorable:
            raise HarborManifestError(
                ["capture-reference requires a complete 200-case manifest; status is draft"]
            )
    artifact = capture_reference(
        args.instance,
        corpus_root=args.corpus_root,
        reference_url=args.reference_url,
        force=args.force,
        allow_source_mutations=args.allow_source_mutations,
        allow_legacy_deploy_v2=args.legacy_deploy_v2,
    )
    instance = load_instance(
        args.instance,
        corpus_root=args.corpus_root,
        allow_legacy_deploy_v2=args.legacy_deploy_v2,
    )
    _emit(
        {
            "status": "captured",
            "instance_id": instance.data["instance_id"],
            "artifact": str(artifact),
        }
    )
    return 0


def _score_v2(args: argparse.Namespace) -> int:
    legacy_values = (
        args.task_suite,
        args.task_results,
        args.visual_suite,
        args.visual_results,
        args.cicd_suite,
        args.cicd_results,
    )
    if args.legacy_deploy_v2:
        if args.case_manifest is not None or args.case_results is not None:
            raise ValueError("--legacy-deploy-v2 cannot be mixed with active case inputs")
        if any(value is None for value in legacy_values):
            raise ValueError(
                "--legacy-deploy-v2 requires all six --task/--visual/--cicd suite/result inputs"
            )
        return score_results(
            task_suite=args.task_suite,
            task_results=args.task_results,
            visual_suite=args.visual_suite,
            visual_results=args.visual_results,
            cicd_suite=args.cicd_suite,
            cicd_results=args.cicd_results,
            output=args.out,
        )
    if any(value is not None for value in legacy_values):
        raise ValueError("the six-suite score interface requires --legacy-deploy-v2")
    if args.case_manifest is None or args.case_results is None:
        raise ValueError("score-v2 requires --case-manifest and --case-results")
    return score_case_result_files(
        case_manifest=args.case_manifest,
        case_results=args.case_results,
        output=args.out,
    )


def _validate_bundle(args: argparse.Namespace) -> int:
    _emit(
        validate_bundle(
            args.bundle, allow_legacy_deploy_v2=args.legacy_deploy_v2
        )
    )
    return 0


def _calibrate_v2(args: argparse.Namespace) -> int:
    return calibrate_bundle(
        args.bundle, args.out, allow_legacy_deploy_v2=args.legacy_deploy_v2
    )


def _run_opencli(args: argparse.Namespace) -> int:
    site = load_site(
        args.site,
        allow_legacy_v1=args.legacy_v1,
        allow_legacy_deploy_v2=True,
    )
    contract = load_contract_from_site(args.site, allow_legacy_v1=args.legacy_v1)
    profile_id = args.profile
    if profile_id is None:
        available = sorted(contract.profiles)
        if len(available) != 1:
            raise OpenCliContractError(
                "--profile is required when the contract declares more than one "
                f"profile: {available}"
            )
        profile_id = available[0]

    runtime = site.data.get("runtime", {})
    base_url = args.base_url
    if base_url is None:
        port = runtime.get("verifier_candidate_port") or runtime.get("candidate_port")
        example = f"; for example `--base-url http://127.0.0.1:{port}`" if port else ""
        raise OpenCliContractError(
            "--base-url is required; start the candidate clone first and pass "
            f"its loopback URL{example}"
        )

    payload = opencli_runner.run(
        contract,
        profile_id,
        base_url=base_url,
        output=args.out,
        backend_name=args.backend,
        binary=args.opencli_bin,
        timeout=args.timeout_seconds,
        target=args.target,
        reset_path=("" if args.no_reset else str(runtime.get("reset_path") or "")),
        admin_token=args.admin_token,
        force=args.force,
    )
    _emit(
        {
            "status": payload["status"],
            "backend": payload["backend"],
            "profile_id": payload["profile_id"],
            "output": str(args.out.resolve()),
            "summary": payload["summary"],
            "degradation": payload["degradation"],
            "authority": payload["authority"],
        }
    )
    # Always 0 when an artifact was produced: a failing step is a diagnostic
    # observation, not a process failure. Returning non-zero here is how this
    # would quietly become a technical-verification stage.
    return 0


def _opencli_adapters(args: argparse.Namespace) -> int:
    site = load_site(
        args.site,
        allow_legacy_v1=args.legacy_v1,
        allow_legacy_deploy_v2=True,
    )
    contract = load_contract_from_site(args.site, allow_legacy_v1=args.legacy_v1)
    display_name = str(site.data.get("display_name") or contract.site_id)
    rendered = opencli_adapters.render_for_contract(contract, display_name)
    destination = args.out or (site.root / "interactions" / "adapters")

    if args.check:
        problems = opencli_adapters.check(rendered, destination)
        _emit(
            {
                "status": "drift" if problems else "in-sync",
                "destination": str(destination),
                "problems": problems,
            }
        )
        return 2 if problems else 0

    written = opencli_adapters.write(rendered, destination)
    payload: dict[str, Any] = {
        "status": "generated",
        "site": opencli_adapters.adapter_site_name(contract.site_id),
        "destination": str(destination),
        "files": [str(path) for path in written],
    }
    if args.install:
        installed = opencli_adapters.install(destination, contract.site_id)
        payload["installed"] = str(installed)
    _emit(payload)
    return 0


def _assignment(value: str) -> tuple[str, str]:
    instance_id, separator, profile_id = value.partition("=")
    if not separator or not instance_id or not profile_id:
        raise argparse.ArgumentTypeError(
            f"{value!r}: expected <instance_id>=<profile_id>"
        )
    return instance_id, profile_id


def _derive_from_clone(args: argparse.Namespace) -> int:
    payload = contract_derive.run_derive(
        clone_manifest=args.clone_manifest,
        harbor_site=args.harbor_site,
        max_profiles=args.max_profiles,
        max_steps=args.max_steps,
        assign_profile=dict(args.assign_profile or []),
        force=args.force,
    )
    _emit(payload)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="websitebench-harbor")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_site = subparsers.add_parser(
        "init-site", help="create a site authoring skeleton"
    )
    init_site.add_argument("--site-dir", type=Path, required=True)
    init_site.add_argument("--site-id", required=True)
    init_site.add_argument("--display-name", required=True)
    init_site.add_argument(
        "--legacy-v1",
        action="store_true",
        help="explicitly create the historical v1 layout instead of v2",
    )
    init_site.set_defaults(function=_init_site)

    init_instance = subparsers.add_parser(
        "init-instance", help="create the unique same-id instance for one site"
    )
    init_instance.add_argument("--instance-dir", type=Path, required=True)
    init_instance.add_argument("--instance-id", required=True)
    init_instance.add_argument(
        "--site-manifest",
        required=True,
        help="path relative to the Harbor root; its site id must equal --instance-id",
    )
    init_instance.add_argument("--author-name", required=True)
    init_instance.add_argument("--author-email", required=True)
    init_instance.add_argument(
        "--legacy-v1",
        action="store_true",
        help="explicitly create the historical v1 layout instead of v2",
    )
    init_instance.set_defaults(function=_init_instance)

    validate = subparsers.add_parser("validate", help="validate one instance")
    validate.add_argument("--instance", type=Path, required=True)
    validate.add_argument("--corpus-root", type=Path)
    validate.add_argument(
        "--legacy-v1",
        action="store_true",
        help="explicitly allow reading the historical v1 manifest format",
    )
    validate.add_argument(
        "--legacy-deploy-v2",
        action="store_true",
        help="explicitly allow the pre-compile deploy.sh Harbor v2 contract",
    )
    validate.set_defaults(function=_validate)

    validate_corpus = subparsers.add_parser(
        "validate-corpus",
        help="validate the one-site/one-instance corpus under one authoring root",
    )
    validate_corpus.add_argument("--corpus-root", type=Path, required=True)
    validate_corpus.add_argument(
        "--legacy-v1",
        action="store_true",
        help="explicitly allow reading historical v1 manifests",
    )
    validate_corpus.add_argument(
        "--legacy-deploy-v2",
        action="store_true",
        help="explicitly allow pre-compile deploy.sh Harbor v2 manifests",
    )
    validate_corpus.set_defaults(function=_validate_corpus)

    materialize = subparsers.add_parser(
        "materialize", help="generate a self-contained Harbor bundle"
    )
    materialize.add_argument("--instance", type=Path, required=True)
    materialize.add_argument("--out", type=Path, required=True)
    materialize.add_argument("--corpus-root", type=Path)
    materialize.add_argument(
        "--legacy-v1",
        action="store_true",
        help="explicitly materialize an immutable historical v1 input",
    )
    materialize.add_argument(
        "--legacy-deploy-v2",
        action="store_true",
        help="explicitly materialize the pre-compile deploy.sh Harbor v2 contract",
    )
    materialize.set_defaults(function=_materialize)

    capture = subparsers.add_parser(
        "capture-reference",
        help="capture task and visual observations from the reference",
    )
    capture.add_argument("--instance", type=Path, required=True)
    capture.add_argument("--corpus-root", type=Path)
    capture.add_argument(
        "--reference-url",
        help="use an already-running reference; otherwise launch site.paths.reference/run.sh",
    )
    capture.add_argument("--force", action="store_true")
    capture.add_argument(
        "--legacy-deploy-v2",
        action="store_true",
        help="explicitly capture for the pre-compile deploy.sh Harbor v2 contract",
    )
    capture.add_argument(
        "--allow-source-mutations",
        action="store_true",
        help="allow only scenarios that explicitly declare reference_mutation_authorized",
    )
    capture.set_defaults(function=_capture_reference)

    score_v2 = subparsers.add_parser(
        "score-v2", help="compute the deterministic v2 scorecard from exact result sets"
    )
    score_v2.add_argument("--case-manifest", type=Path)
    score_v2.add_argument("--case-results", type=Path)
    for option in (
        "task-suite",
        "task-results",
        "visual-suite",
        "visual-results",
        "cicd-suite",
        "cicd-results",
    ):
        score_v2.add_argument(f"--{option}", type=Path)
    score_v2.add_argument(
        "--legacy-deploy-v2",
        action="store_true",
        help="use the historical six-suite deploy.sh score interface",
    )
    score_v2.add_argument("--out", type=Path, required=True)
    score_v2.set_defaults(function=_score_v2)

    bundle = subparsers.add_parser(
        "validate-bundle",
        help="verify a materialized v2 bundle's structure and hidden-content closure",
    )
    bundle.add_argument("--bundle", type=Path, required=True)
    bundle.add_argument(
        "--legacy-deploy-v2",
        action="store_true",
        help="explicitly validate a pre-compile deploy.sh Harbor v2 bundle",
    )
    bundle.set_defaults(function=_validate_bundle)

    calibration = subparsers.add_parser(
        "calibrate-v2",
        help="run NOP once and a fresh oracle twice against a materialized v2 bundle",
    )
    calibration.add_argument("--bundle", type=Path, required=True)
    calibration.add_argument("--out", type=Path, required=True)
    calibration.add_argument(
        "--legacy-deploy-v2",
        action="store_true",
        help="calibrate a pre-compile deploy.sh Harbor v2 bundle",
    )
    calibration.set_defaults(function=_calibrate_v2)

    run_opencli = subparsers.add_parser(
        "run-opencli",
        help="replay an OpenCLI interaction profile against a running target "
        "(diagnostic only)",
    )
    run_opencli.add_argument("--site", type=Path, required=True)
    run_opencli.add_argument(
        "--profile", help="contract profile id; optional when only one exists"
    )
    run_opencli.add_argument(
        "--base-url",
        help="URL of the already-running candidate clone (or explicit reference target)",
    )
    run_opencli.add_argument("--out", type=Path, required=True)
    run_opencli.add_argument(
        "--backend",
        choices=("adapter", "browser", "auto"),
        default="adapter",
        help="adapter drives generated browser:false adapters over plain HTTP; "
        "browser needs a connected OpenCLI Browser Bridge",
    )
    run_opencli.add_argument("--opencli-bin", default="opencli")
    run_opencli.add_argument("--timeout-seconds", type=int, default=30)
    run_opencli.add_argument(
        "--target",
        choices=("reference", "candidate"),
        default="candidate",
        help="artifact target label (default: candidate)",
    )
    run_opencli.add_argument(
        "--admin-token",
        default=os.environ.get("WEBSITEBENCH_ADMIN_TOKEN", ""),
        help="token sent to the target reset endpoint (default: "
        "WEBSITEBENCH_ADMIN_TOKEN, or empty when unset)",
    )
    run_opencli.add_argument("--no-reset", action="store_true")
    run_opencli.add_argument("--force", action="store_true")
    run_opencli.add_argument(
        "--legacy-v1",
        action="store_true",
        help="explicitly read a historical v1 site manifest",
    )
    run_opencli.set_defaults(function=_run_opencli)

    adapters = subparsers.add_parser(
        "opencli-adapters",
        help="generate the browser:false OpenCLI adapters for one site",
    )
    adapters.add_argument("--site", type=Path, required=True)
    adapters.add_argument(
        "--out", type=Path, help="defaults to <site>/interactions/adapters"
    )
    adapters.add_argument(
        "--check",
        action="store_true",
        help="report drift between the generator and the committed files",
    )
    adapters.add_argument(
        "--install",
        action="store_true",
        help="also copy into ~/.opencli/clis/wb-<site-id>/",
    )
    adapters.add_argument(
        "--legacy-v1",
        action="store_true",
        help="explicitly read a historical v1 site manifest",
    )
    adapters.set_defaults(function=_opencli_adapters)

    derive = subparsers.add_parser(
        "derive-from-clone",
        help="derive one site's OpenCLI interaction contract from captured clone artifacts",
    )
    derive.add_argument("--clone-manifest", type=Path, required=True)
    derive.add_argument(
        "--harbor-site",
        type=Path,
        help="override the harbor/sites/<id>/ the clone site_id maps to",
    )
    derive.add_argument(
        "--max-profiles", type=int, default=contract_derive.DEFAULT_MAX_PROFILES
    )
    derive.add_argument(
        "--max-steps", type=int, default=contract_derive.DEFAULT_MAX_STEPS
    )
    derive.add_argument(
        "--assign-profile",
        type=_assignment,
        action="append",
        metavar="SITE_ID=PROFILE",
        help="set opencli_profile on the current site's unique same-id instance",
    )
    derive.add_argument(
        "--force", action="store_true", help="overwrite an existing contract"
    )
    derive.set_defaults(function=_derive_from_clone)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.function(args))
    except (
        FileExistsError,
        FileNotFoundError,
        HarborManifestError,
        OSError,
        RuntimeError,
        ValueError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
