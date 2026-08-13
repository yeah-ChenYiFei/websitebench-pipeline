"""Create normalized Harbor authoring skeletons without overwriting user data."""

from __future__ import annotations

import json
import re
from pathlib import Path
from pathlib import PurePosixPath

import yaml

from .policy import AUTH_CHECKOUT_REQUIRED_NODES


_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _validate_identity(destination: Path, identifier: str, kind: str) -> None:
    if not _SLUG.fullmatch(identifier):
        raise ValueError(f"{kind}_id must be a lowercase hyphenated slug")
    if destination.name != identifier:
        raise ValueError(
            f"{kind}_id must match destination directory name {destination.name!r}"
        )


def _prepare_empty(destination: Path) -> Path:
    destination = destination.resolve()
    if destination.exists() and any(destination.iterdir()):
        raise FileExistsError(f"destination is non-empty: {destination}")
    destination.mkdir(parents=True, exist_ok=True)
    return destination


def _write_yaml(path: Path, value: dict[str, object]) -> None:
    path.write_text(
        yaml.safe_dump(value, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
        newline="\n",
    )


def initialize_site(
    destination: Path,
    *,
    site_id: str,
    display_name: str,
    legacy_v1: bool = False,
) -> Path:
    _validate_identity(destination, site_id, "site")
    if not display_name.strip():
        raise ValueError("display_name must not be empty")
    root = _prepare_empty(destination)
    for directory in ("public", "reference", "verifier", "fixtures/hidden", "oracle"):
        (root / directory).mkdir(parents=True, exist_ok=True)
    (root / "public" / "README.md").write_text(
        "# Public site contract\n\n"
        "Only Agent-visible API/interface contracts and starter assets belong here. "
        "Never place reference implementation files in this directory.\n",
        encoding="utf-8",
        newline="\n",
    )
    (root / "reference" / "server.py").write_text(
        '"""Replace this minimal server with the frozen offline reference."""\n\n'
        "from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer\n"
        "import os\n\n"
        "class Handler(BaseHTTPRequestHandler):\n"
        "    def do_GET(self):\n"
        "        if self.path == '/healthz':\n"
        "            body = b'ok\\n'\n"
        "            self.send_response(200)\n"
        "            self.send_header('Content-Type', 'text/plain')\n"
        "        else:\n"
        "            body = b'Replace the scaffold reference implementation.\\n'\n"
        "            self.send_response(200)\n"
        "            self.send_header('Content-Type', 'text/plain')\n"
        "        self.send_header('Content-Length', str(len(body)))\n"
        "        self.end_headers()\n"
        "        self.wfile.write(body)\n\n"
        "    def log_message(self, format, *args):\n"
        "        return\n\n"
        "ThreadingHTTPServer(('0.0.0.0', int(os.environ.get('PORT', '8080'))), "
        "Handler).serve_forever()\n",
        encoding="utf-8",
        newline="\n",
    )
    (root / "reference" / "Dockerfile").write_text(
        "FROM python:3.12-slim\n"
        "WORKDIR /srv/reference\n"
        "COPY . .\n"
        "ENV PORT=8080\n"
        "HEALTHCHECK --interval=2s --timeout=3s --retries=30 "
        'CMD python -c "import urllib.request; '
        "urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=2)\"\n"
        'CMD ["python", "server.py"]\n',
        encoding="utf-8",
        newline="\n",
    )
    reference_run = root / "reference" / "run.sh"
    reference_run.write_text(
        "#!/usr/bin/env bash\nset -Eeuo pipefail\nexec python server.py\n",
        encoding="utf-8",
        newline="\n",
    )
    reference_run.chmod(0o755)
    verifier_message = (
        '    "Implement API, Playwright, visual, journey, and robustness checks; "\n'
        '    "write /run/verifier-final/ctrf.json and dimensions.json."\n'
        if legacy_v1
        else '    "Add only deterministic site-specific checks; Harbor v2 owns "\n'
        '    "task, RGB SSIM, CI/CD result validation, and scoring."\n'
    )
    (root / "verifier" / "run.py").write_text(
        '"""Site-specific trusted evaluator entry point."""\n\n'
        "raise SystemExit(\n" + verifier_message + ")\n",
        encoding="utf-8",
        newline="\n",
    )
    (root / "fixtures" / "hidden" / "README.md").write_text(
        "# Hidden fixtures\n\nEvaluator-only reset states and test data.\n",
        encoding="utf-8",
        newline="\n",
    )
    (root / "oracle" / "README.md").write_text(
        "# Oracle-only site support\n\n"
        "Private calibration helpers. These files are copied only into solution/.\n",
        encoding="utf-8",
        newline="\n",
    )
    if legacy_v1:
        scoring: dict[str, object] = {
            "max_points": 100,
            "dimensions": {
                "contract": 10,
                "api": 20,
                "ui": 20,
                "visual": 15,
                "journey": 20,
                "robustness": 15,
                "efficiency": 0,
            },
        }
        runtime: dict[str, object] = {
            "reference_access": "browser-only",
            "agent_browser": "browser-use-cli",
            "formal_browser": "playwright",
            "reference_url_env": "WEBSITEBENCH_REFERENCE_URL",
            "candidate_url_env": "WEBSITEBENCH_CANDIDATE_URL",
            "reference_admin_url_env": "WEBSITEBENCH_REFERENCE_ADMIN_URL",
            "candidate_admin_url_env": "WEBSITEBENCH_CANDIDATE_ADMIN_URL",
            "reference_port": 8080,
            "candidate_port": 3000,
            "verifier_reference_port": 18080,
            "verifier_candidate_port": 18901,
            "ready_path": "/healthz",
            "reset_path": "/__admin/reset",
            "judge_network": "offline",
        }
    else:
        scoring = {
            "reward_source": "task_completion",
            "task_score": "equal_weight_exact_terminal_state",
            "visual_score": "checkpoint_area_weighted_rgb_ssim_report_only",
            "cicd_score": "equal_weight_trusted_checks_report_only",
        }
        runtime = {
            "reference_access": "browser-only",
            "agent_browser": "browser-use-cli",
            "formal_browser": "playwright",
            "reference_url_env": "WEBSITEBENCH_REFERENCE_URL",
            "reference_allowed_origins_env": "WEBSITEBENCH_REFERENCE_ALLOWED_ORIGINS",
            "reference_storage_state_env": "WEBSITEBENCH_REFERENCE_STORAGE_STATE",
            "reference_reset_url_env": "WEBSITEBENCH_REFERENCE_RESET_URL",
            "reference_reset_credential_env": "WEBSITEBENCH_REFERENCE_RESET_CREDENTIAL",
            "candidate_url_env": "WEBSITEBENCH_CANDIDATE_URL",
            "reference_port": 8080,
            "candidate_port": 3000,
            "ready_path": "/healthz",
            "judge_network": "loopback-only",
            "candidate_entrypoint": "deploy.sh",
            "candidate_data_dir_env": "WEBSITEBENCH_DATA_DIR",
            "formal_workers": 4,
            "browser": {
                "engine": "chromium",
                "playwright_version": "1.61.0",
                "font_profile": "websitebench-linux-fonts-v1",
                "locale": "en-US",
                "timezone": "UTC",
                "color_scheme": "light",
                "frozen_time": "2026-01-01T00:00:00Z",
                "disable_animations": True,
            },
        }
    site_payload: dict[str, object] = {
        "schema_version": (
            "websitebench.harbor.site.v1"
            if legacy_v1
            else "websitebench.harbor.site.v2"
        ),
        "site_id": site_id,
        "display_name": display_name,
        "benchmark_kind": "fullstack-offline-reconstruction",
        "runtime": runtime,
    }
    if not legacy_v1:
        site_payload["mailbox"] = {
            "mode": "local-sidecar",
            "namespace_env": "WEBSITEBENCH_MAILBOX_NAMESPACE",
            "credential_env": "WEBSITEBENCH_MAILBOX_CREDENTIAL",
            "external_allowlist": [],
        }
    site_payload.update(
        {
            "paths": {
                "public": "public",
                "reference": "reference",
                "verifier": "verifier",
                "hidden_fixtures": "fixtures/hidden",
                "oracle": "oracle",
            },
            "scoring": scoring,
        }
    )
    _write_yaml(root / "site.yaml", site_payload)
    return root / "site.yaml"


def initialize_instance(
    destination: Path,
    *,
    instance_id: str,
    site_manifest: str,
    author_name: str,
    author_email: str,
    legacy_v1: bool = False,
) -> Path:
    _validate_identity(destination, instance_id, "instance")
    site_parts = PurePosixPath(site_manifest.replace("\\", "/")).parts
    if len(site_parts) != 3 or site_parts[0] != "sites" or site_parts[2] != "site.yaml":
        raise ValueError(
            "site_manifest must be sites/<site-id>/site.yaml relative to the "
            "authoring root"
        )
    if not legacy_v1 and instance_id != site_parts[1]:
        raise ValueError(
            "current Harbor sites have exactly one same-id instance: "
            f"instance_id must be {site_parts[1]!r}"
        )
    if not author_name.strip():
        raise ValueError("author_name must not be empty")
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", author_email):
        raise ValueError("author_email must be a valid email address")
    root = _prepare_empty(destination)
    for directory in ("public", "verifier", "fixtures/hidden", "solution"):
        (root / directory).mkdir(parents=True, exist_ok=True)
    (root / "instruction.md").write_text(
        "# Reconstruct the offline website\n\n"
        "Use Browser Use CLI to inspect the browser-only reference website. Rebuild "
        "the complete scoped frontend and backend in `/app/repo`. The formal verifier uses "
        + (
            "Playwright and direct HTTP checks against a fresh candidate instance.\n"
            if legacy_v1
            else "A deterministic verifier evaluates hidden exact-state tasks, RGB "
            "SSIM checkpoints, and trusted CI/CD checks. Only task completion "
            "contributes to reward.\n"
        ),
        encoding="utf-8",
        newline="\n",
    )
    (root / "public" / "README.md").write_text(
        "# Site-instance public files\n\n"
        "Place the candidate scaffold and Agent-visible site contracts here. Keep "
        + ("`run.sh`" if legacy_v1 else "root `deploy.sh`")
        + ": the verifier sets `PORT` and `WEBSITEBENCH_DATA_DIR`, then runs "
        "it from `/app/repo`.\n",
        encoding="utf-8",
        newline="\n",
    )
    candidate_run = root / "public" / ("run.sh" if legacy_v1 else "deploy.sh")
    candidate_run.write_text(
        "#!/usr/bin/env bash\n"
        "set -Eeuo pipefail\n"
        "echo 'implement the candidate server; listen on $PORT' >&2\n"
        "exit 2\n",
        encoding="utf-8",
        newline="\n",
    )
    candidate_run.chmod(0o755)
    (root / "verifier" / "README.md").write_text(
        "# Site-instance verifier overlay\n\n"
        "Put evaluator-only checks for the complete scoped site here.\n",
        encoding="utf-8",
        newline="\n",
    )
    (root / "fixtures" / "hidden" / "README.md").write_text(
        "# Site-instance hidden fixtures\n\nEvaluator-only site scenarios and expected states.\n",
        encoding="utf-8",
        newline="\n",
    )
    solve = root / "solution" / "solve.sh"
    solve.write_text(
        "#!/usr/bin/env bash\n"
        "set -Eeuo pipefail\n"
        "echo 'oracle solution is not implemented' >&2\n"
        "exit 2\n",
        encoding="utf-8",
        newline="\n",
    )
    solve.chmod(0o755)
    if not legacy_v1:
        hidden = root / "fixtures" / "hidden"
        suites: dict[str, dict[str, object]] = {
            "task-suite.json": {
                "schema_version": "websitebench.harbor.task-suite.v1",
                "suite_id": f"{instance_id}-tasks",
                "site_id": site_parts[1],
                "dsl_version": "websitebench.harbor.playwright-dsl.v1",
                "tasks": [
                    {
                        "id": "healthz",
                        "timeout_sec": 30,
                        "actions": [],
                        "observations": [
                            {
                                "id": "status",
                                "kind": "api_status",
                                "path": "/healthz",
                                "comparator": {"type": "exact"},
                            }
                        ],
                    }
                ],
            },
            "visual-suite.json": {
                "schema_version": "websitebench.harbor.visual-suite.v1",
                "suite_id": f"{instance_id}-visual",
                "site_id": site_parts[1],
                "checkpoints": [
                    {
                        "id": "home",
                        "route": "/",
                        "timeout_sec": 60,
                        "viewport": {"width": 1280, "height": 720},
                        "actions": [],
                        "regions": [
                            {
                                "id": "page",
                                "rect": {"x": 0, "y": 0, "width": 1280, "height": 720},
                                "masks": [],
                            }
                        ],
                        "reference_image": "visual/home.png",
                    }
                ],
            },
            "cicd-suite.json": {
                "schema_version": "websitebench.harbor.cicd-suite.v1",
                "suite_id": f"{instance_id}-cicd",
                "site_id": site_parts[1],
                "checks": [
                    {"id": identifier, "kind": "platform", "timeout_sec": 60}
                    for identifier in (
                        "platform::artifact/complete",
                        "platform::artifact/deploy-path-safe",
                        "platform::deploy/offline-clean",
                        "platform::deploy/healthz",
                        "platform::deploy/foreground-lifecycle",
                        "platform::deploy/graceful-sigterm",
                        "platform::deploy/restart-persistence",
                        "platform::deploy/concurrent-isolation",
                        "platform::artifact/code-tree-unchanged",
                        "platform::network/external-closed",
                        "platform::security/secret-reference-verifier-scan",
                        "platform::browser/chromium-smoke",
                        "platform::accessibility/basic",
                        "platform::performance/startup-budget",
                        "platform::performance/resource-budget",
                    )
                ],
            },
        }
        for filename, payload in suites.items():
            (hidden / filename).write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
                newline="\n",
            )

    instance_payload: dict[str, object] = {
        "schema_version": (
            "websitebench.harbor.instance.v1"
            if legacy_v1
            else "websitebench.harbor.instance.v2"
        ),
        "instance_id": instance_id,
        "site_manifest": site_manifest,
        "task": {
            "category": "web-development",
            "type": "fullstack-reconstruction",
            "language": "web",
        },
        "metadata": {
            "author_name": author_name,
            "author_email": author_email,
            "difficulty": "hard",
            "tags": ["browser-checks", "frontend-backend"],
        },
        "budgets": {
            "agent_timeout_sec": 3600 if legacy_v1 else 28800,
            "verifier_timeout_sec": 1200 if legacy_v1 else 3600,
            "build_timeout_sec": 1200,
            "cpus": 4,
            "memory_mb": 8192,
            "storage_mb": 20480,
        },
        "paths": {
            "instruction": "instruction.md",
            "public": "public",
            "verifier": "verifier",
            "hidden_fixtures": "fixtures/hidden",
            "oracle_solution": "solution/solve.sh",
        },
    }
    if legacy_v1:
        instance_payload.update(
            {
                "tests": {
                    "contract": [
                        "contract::runtime/starts-and-resets",
                        *AUTH_CHECKOUT_REQUIRED_NODES["contract"],
                    ],
                    "api": [
                        "api::core/read-path",
                        "api::core/write-path",
                        *AUTH_CHECKOUT_REQUIRED_NODES["api"],
                    ],
                    "ui": [
                        "ui::primary/initial-state",
                        "ui::primary/interaction",
                        *AUTH_CHECKOUT_REQUIRED_NODES["ui"],
                    ],
                    "visual": ["visual::primary/reference-checkpoint"],
                    "journey": [
                        "journey::primary/end-to-end",
                        *AUTH_CHECKOUT_REQUIRED_NODES["journey"],
                    ],
                    "robustness": [
                        "robustness::refresh-and-retry",
                        *AUTH_CHECKOUT_REQUIRED_NODES["robustness"],
                    ],
                    "efficiency": [],
                },
                "calibration": {"nop_max_score": 10, "oracle_min_score": 95},
            }
        )
    else:
        instance_payload.update(
            {
                "suites": {
                    "task": "fixtures/hidden/task-suite.json",
                    "visual": "fixtures/hidden/visual-suite.json",
                    "cicd": "fixtures/hidden/cicd-suite.json",
                },
                "reference_observations": {
                    "status": "pending",
                    "artifact": "fixtures/hidden/reference-observations.json",
                },
                "calibration": {
                    "nop_max_task_score": 5,
                    "oracle_task_score": 100,
                    "oracle_min_visual_score": 95,
                    "oracle_cicd_score": 100,
                    "repeat_deterministic": True,
                },
            }
        )
    _write_yaml(
        root / "instance.yaml",
        instance_payload,
    )
    return root / "instance.yaml"
