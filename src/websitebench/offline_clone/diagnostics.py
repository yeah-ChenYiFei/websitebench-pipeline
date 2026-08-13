"""Two generic diagnostic sections for any offline clone.

``static`` needs no browser and no server: it reads the frozen contracts, the
asset closure and the shipped candidate files. ``live`` boots the clone and
walks its frozen checkpoints in a real browser.

Visual comparison is a reference. Its results are measured and reported under
``observations``: the frozen frames
are thin (64 contracts across 1,505 checkpoints), several thresholds sit at
0.45 where almost any two same-sized pages pass, and a frame can capture the
source site erroring. Route reachability, network closure, asset closure and
declared state assertions are findings for a maintainer to evaluate, not
automatic acceptance decisions.

Every site runs the same two sections. Site-specific knowledge lives in that
site's own data -- ``clone.yaml``, ``scope/`` and ``source-assets/`` -- and
never in this module, so adding a site adds data rather than code. Both sections
collect findings instead of raising on the first one: a clone generator needs
the whole list in one run.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import socket
import sys
import tempfile
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

from .assets import verify_asset_closure
from .manifest import LoadedManifest, load_manifest, utc_now
from .secrets import sensitive_findings
from .verify_driver import load_verify_driver
from websitebench.runtime_isolation import (
    IsolatedProcess,
    IsolationLimits,
    IsolationUnavailable,
    clean_candidate_environment,
    launch_candidate,
    prepare_data_directory,
    require_isolation,
)


DIAGNOSTIC_SECTIONS = ("static", "live")
DIAGNOSTIC_SCHEMA_VERSION = "offline-clone.diagnostic-report.v1"
DIAGNOSTIC_AUTHORITY = "diagnostic-only"
DIAGNOSTIC_QUALIFICATION = "maintainer-judgment-required"
LIVE_WALL_SECONDS = 15 * 60

# A remote runtime reference is an attribute or CSS/JS url() pointing at a host
# that is not loopback. Data URIs and relative paths are the offline norm.
REMOTE_URL = re.compile(
    r"(?i)(?:src|href|action|url)\s*[=(:]\s*[\"']?\s*"
    r"(?:https?:)?//(?!localhost|127\.0\.0\.1)[a-z0-9.-]+\.[a-z]{2,}"
)
TEXT_SUFFIXES = frozenset(
    {".html", ".htm", ".css", ".js", ".mjs", ".jinja", ".j2", ".svg"}
)
# A documented remote reference (a comment, a citation) is not a runtime load.
ALLOW_MARKER = "clawbench-allow-remote-doc"
# A route pattern is only usable as a path when it names exactly one. Scope
# contracts also carry placeholders (`/dp/<ASIN>`) and outright prose
# ("/gp/cart/view.html and cart mutation endpoints", "GET /start-a-petition
# observed HTTP 301; ..."), and turning either into a URL fabricates a request
# nobody declared.
PLACEHOLDER = re.compile(r"[<{]|[,;]| and | observed |\s")
# There is deliberately no static placeholder-link check. `href="#"` is what
# real sites ship for scripted controls -- tripit's carousel arrows and its
# clipboard button both come straight from the source capture -- so flagging it
# would fire on exactly the clones that copied the source most faithfully.
# Whether a control does anything is a runtime question, and it belongs to the
# live section or to nothing.
#
# `sensitive_findings` is written for records, where an email address or a field
# named `password` is PII that should never have been logged. In a shipped login
# page those same names are the page's own vocabulary. Only findings that match
# on a *value* which is secret by nature survive into a file scan.
CREDENTIAL_FINDINGS = frozenset({"private_key", "bearer_token", "jwt", "provider_key"})
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", ""})
INERT_SCHEMES = frozenset({"data", "blob", "about", "javascript"})
DEFAULT_STATES = frozenset({"", "loaded", "default"})


@dataclass
class Finding:
    """One concrete defect, addressed to whoever has to fix it."""

    check: str
    message: str
    subject: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"check": self.check, "subject": self.subject, "message": self.message}


@dataclass
class SectionResult:
    section: str
    site_id: str
    checks: dict[str, int] = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)
    # Measured, reported, and deliberately not part of `status`. See the module
    # docstring on why visual comparison is a reference rather than a section.
    notes: list[Finding] = field(default_factory=list)
    execution_complete: bool = True
    incomplete_reasons: list[str] = field(default_factory=list)

    def incomplete(self, reason: str) -> None:
        self.execution_complete = False
        if reason not in self.incomplete_reasons:
            self.incomplete_reasons.append(reason)

    def as_dict(self) -> dict[str, Any]:
        return {
            "execution": {
                "complete": self.execution_complete,
                "incomplete_reasons": list(self.incomplete_reasons),
            },
            "coverage": self.checks,
            "findings": [finding.as_dict() for finding in self.findings],
            "observations": [note.as_dict() for note in self.notes],
        }


# ---------------------------------------------------------------------------
# Site data
# ---------------------------------------------------------------------------


@dataclass
class Checkpoint:
    id: str
    route_id: str
    state: str
    viewport: str
    path: str | None
    width: int
    height: int
    visual_contract: dict[str, Any] | None
    acceptance_eligible: bool
    required_session: str | None = None

    @property
    def needs_session(self) -> bool:
        return self.required_session is not None

    @property
    def structural_key(self) -> tuple[str, str, str, str]:
        """What actually has to be visited: the same tuple is one page load."""

        return (
            self.path or "",
            self.state,
            self.viewport,
            self.required_session or "anonymous",
        )


@dataclass
class SiteData:
    manifest: LoadedManifest
    root: Path
    site_id: str
    checkpoints: list[Checkpoint]
    prepare: list[dict[str, Any]]
    states: dict[str, list[dict[str, Any]]]
    unresolved_routes: list[tuple[str, str]]
    deferred_routes: dict[str, str]
    expected_status: dict[str, int]
    visual_excluded: dict[str, str]
    session: dict[str, Any]
    out_of_scope: dict[str, str]
    boot: dict[str, Any]

    def recipe_for(self, checkpoint: Checkpoint) -> dict[str, Any] | None:
        """The recipe for this checkpoint's state, most specific key first."""

        for key in (f"{checkpoint.route_id}.{checkpoint.state}", checkpoint.state):
            recipe = self.states.get(key)
            if recipe is not None:
                return recipe
        return None

    def steps_for(self, checkpoint: Checkpoint) -> list[dict[str, Any]] | None:
        recipe = self.recipe_for(checkpoint)
        return None if recipe is None else recipe["steps"]

    def session_for(self, checkpoint: Checkpoint) -> str | None:
        """Which named session this checkpoint is seen through, if any."""

        recipe = self.recipe_for(checkpoint)
        if recipe and recipe.get("session"):
            return str(recipe["session"])
        return checkpoint.required_session

    @property
    def sessions(self) -> dict[str, dict[str, Any]]:
        """Named sessions. A single unnamed block is the `default` one."""

        declared = self.session
        if not declared:
            return {}
        if "accounts" in declared:
            common = {
                key: value for key, value in declared.items() if key != "accounts"
            }
            return {
                str(name): {
                    **common,
                    **account,
                    "headers": {
                        **(common.get("headers") or {}),
                        **(account.get("headers") or {}),
                    },
                    "form": {
                        **(common.get("form") or {}),
                        **(account.get("form") or {}),
                    },
                }
                for name, account in declared["accounts"].items()
            }
        return {"default": declared}


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _clone_path(
    checkpoint: dict[str, Any],
    route_patterns: dict[str, str],
    aliases: dict[str, str],
) -> str | None:
    """Resolve the path the clone must serve for this checkpoint.

    The scope contracts describe the *source* site, so where the clone serves a
    route somewhere else the site declares that alias in ``scope/verify.json``
    and it wins. Otherwise the route table is the clone's own statement of what
    it serves; a templated pattern falls back to the captured URL, which is the
    only place the concrete query lives. A templated route with no captured URL
    is a declaration gap, not something to guess at.
    """

    route_id = str(checkpoint.get("route_id"))
    alias = aliases.get(route_id)
    if isinstance(alias, str) and alias.startswith("/"):
        return alias
    explicit = checkpoint.get("clone_path")
    if isinstance(explicit, str) and explicit.startswith("/"):
        return explicit
    pattern = route_patterns.get(route_id)
    if (
        isinstance(pattern, str)
        and pattern.startswith("/")
        and not PLACEHOLDER.search(pattern)
    ):
        return pattern
    captured = checkpoint.get("final_url") or checkpoint.get("requested_url")
    if isinstance(captured, str) and captured:
        parts = urlsplit(captured)
        # Not every ledger keeps a URL in this field -- edx records prose in
        # some rows -- and prose split by urlsplit still yields a `path`.
        if parts.scheme in {"http", "https"} and parts.path.startswith("/"):
            return parts.path + (f"?{parts.query}" if parts.query else "")
    return None


def load_site(site_dir: Path) -> SiteData:
    manifest = load_manifest(site_dir / "clone.yaml")
    root = manifest.root
    routes = _read_json(manifest.resolve(manifest.data["scope"]["routes"]))
    route_patterns = {
        str(route["id"]): route.get("route_pattern")
        for route in routes.get("routes", [])
        if isinstance(route.get("route_pattern"), str)
    }
    # Everything the generic verifier needs that the frozen source contracts do
    # not express, in one optional per-site file.
    driver_path = root / "scope" / "verify.json"
    driver = (
        load_verify_driver(driver_path, site_id=str(manifest.data["site_id"]))
        if driver_path.is_file()
        else {}
    )
    # A site that says how to establish a session unlocks the routes it also
    # declared out of anonymous reach; without one they stay counted.
    session = driver.get("session") or {}
    route_sessions = {
        str(route_id): "default" for route_id in (session.get("routes") or ())
    }
    for account_name, account in (session.get("accounts") or {}).items():
        for route_id in account.get("routes") or ():
            route_sessions[str(route_id)] = str(account_name)
    aliases = {
        str(key): str(value) for key, value in (driver.get("routes") or {}).items()
    }
    # Routes this section cannot reach anonymously. Naming one is a claim about
    # coverage, not an excuse: it is counted and printed, never silently passed.
    deferred = {
        str(key): str(value) for key, value in (driver.get("deferred") or {}).items()
    }

    states: dict[str, dict[str, Any]] = {}
    for key, value in (driver.get("states") or {}).items():
        if isinstance(value, list):
            states[str(key)] = {"steps": value}
        elif isinstance(value, dict) and isinstance(value.get("steps"), list):
            states[str(key)] = dict(value)

    ledger = _read_json(manifest.checkpoints_path)
    viewports = ledger.get("viewports") or {}

    checkpoints: list[Checkpoint] = []
    unresolved: list[tuple[str, str]] = []
    for row in ledger.get("checkpoints", []):
        viewport_id = str(row.get("viewport", ""))
        viewport = viewports.get(viewport_id) or {}
        route_id = row.get("route_id")
        # Two different reasons a route is not visited anonymously, and only one
        # of them a session fixes: `session.routes` names the ones a signed-in
        # context reaches, while `deferred` keeps the ones no GET ever reaches
        # -- a POST-only logout, a declared static placeholder.
        required_session = (
            route_sessions.get(route_id) if isinstance(route_id, str) else None
        )
        raw_state = str(row.get("state", "loaded"))
        for recipe_key in (f"{route_id}.{raw_state}", raw_state):
            recipe = states.get(recipe_key)
            if recipe and recipe.get("session"):
                required_session = str(recipe["session"])
                break
        if not isinstance(route_id, str) or (
            route_id in deferred and required_session is None
        ):
            # A checkpoint that names no route makes no reachability claim, and
            # a deferred one is declared out of anonymous reach. Neither is
            # visited; a deferred one is counted so the gap shows in the report.
            path = None
        else:
            path = _clone_path(row, route_patterns, aliases)
            if path is None:
                unresolved.append((str(row.get("id")), route_id))
        contract = row.get("visual_contract")
        checkpoints.append(
            Checkpoint(
                id=str(row.get("id")),
                route_id=str(row.get("route_id")),
                state=raw_state,
                viewport=viewport_id,
                path=path,
                width=int(viewport.get("width", 1440)),
                height=int(viewport.get("height", 900)),
                visual_contract=contract if isinstance(contract, dict) else None,
                acceptance_eligible=row.get("acceptance_eligible", True) is not False,
                required_session=required_session,
            )
        )
    return SiteData(
        manifest=manifest,
        root=root,
        site_id=str(manifest.data["site_id"]),
        checkpoints=checkpoints,
        prepare=list(driver.get("prepare") or []),
        states=states,
        unresolved_routes=unresolved,
        deferred_routes=deferred,
        # Some frozen checkpoints record a source that answered 404. Reproducing
        # that answer is the clone being right, so the expected status is data.
        expected_status={
            str(key): int(value) for key, value in (driver.get("status") or {}).items()
        },
        # Checkpoints whose frozen source frame cannot serve as a reference --
        # a capture that caught the source site erroring, say. Naming one is a
        # claim about the evidence and is counted, never silently passed.
        visual_excluded={
            str(key): str(value)
            for key, value in (driver.get("visual_excluded") or {}).items()
        },
        session=session,
        # State classes this section cannot express, each with the reason and where
        # the semantics are covered instead. Counted separately from states
        # nobody has written yet, because "not our job" and "not done" are
        # different claims and only one of them is work.
        out_of_scope={
            str(key): str(value)
            for key, value in (driver.get("states_out_of_scope") or {}).items()
        },
        boot=driver.get("boot") or {},
    )


# ---------------------------------------------------------------------------
# static section
# ---------------------------------------------------------------------------


def run_static(site: SiteData) -> SectionResult:
    result = SectionResult(section="static", site_id=site.site_id)
    candidate = site.manifest.resolve(site.manifest.data["paths"]["candidate_root"])

    closure = verify_asset_closure(site.manifest)
    result.checks["assets_declared"] = closure.declared
    result.checks["assets_verified"] = closure.verified
    if not closure.passed:
        for issue in closure.issues:
            if issue.blocking:
                result.findings.append(
                    Finding("asset-closure", issue.message, issue.asset_id)
                )

    excluded = tuple(
        (candidate / relative).resolve()
        for relative in site.manifest.data["paths"].get("candidate_excludes", [])
    )
    scanned = remote = secret = 0
    for path in sorted(candidate.rglob("*")):
        resolved = path.resolve()
        if any(resolved == root or root in resolved.parents for root in excluded):
            continue
        if not path.is_file() or path.suffix.casefold() not in TEXT_SUFFIXES:
            continue
        relative = path.relative_to(site.root).as_posix()
        if "/static/assets/" in f"/{relative}":
            continue  # captured asset payloads are compared as bytes, not read as code
        scanned += 1
        text = path.read_text(encoding="utf-8", errors="replace")
        for number, line in enumerate(text.splitlines(), start=1):
            if ALLOW_MARKER in line:
                continue
            match = REMOTE_URL.search(line)
            if match:
                remote += 1
                result.findings.append(
                    Finding(
                        "remote-reference",
                        f"runtime load from a remote host: {match.group(0)[:80]}",
                        f"{relative}:{number}",
                    )
                )
        for finding in sensitive_findings(text):
            if finding not in CREDENTIAL_FINDINGS:
                continue
            secret += 1
            result.findings.append(
                Finding("secret", f"shipped file carries {finding}", relative)
            )

    result.checks["files_scanned"] = scanned
    result.checks["remote_references"] = remote
    result.checks["secrets"] = secret

    for checkpoint_id, route_id in site.unresolved_routes:
        result.findings.append(
            Finding(
                "route-unresolved",
                f"route {route_id} is templated and the checkpoint declares no "
                "clone_path or captured URL, so no path can be verified",
                checkpoint_id,
            )
        )
    deferred_checkpoints = [
        c for c in site.checkpoints if c.route_id in site.deferred_routes and not c.path
    ]
    result.checks["deferred_checkpoints"] = len(deferred_checkpoints)
    result.checks["deferred_routes"] = len(site.deferred_routes)
    return result


# ---------------------------------------------------------------------------
# live section
# ---------------------------------------------------------------------------


def _reserve_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class CloneServer:
    """A disposable clone server bound to an isolated data directory."""

    def __init__(
        self, site: SiteData, data_dir: Path, extra_env: dict[str, str] | None = None
    ) -> None:
        self.site = site
        self.data_dir = data_dir
        self.extra_env = extra_env or {}
        self.port = _reserve_loopback_port()
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.process: IsolatedProcess | None = None
        self.health: dict[str, Any] = {}

    def _candidates(self) -> list[tuple[list[str], Path]]:
        """The ways a clone in this repository knows how to start.

        A clone either runs its own server from ``app.py`` or exposes ``app`` as
        an ASGI object for uvicorn -- both shapes ship today, and which one a
        site uses is discoverable by trying it rather than by asking every site
        to declare it. An explicit ``verify.boot.argv`` overrides both.
        """

        clone = self.site.root / "clone"
        declared = self.site.boot.get("argv")
        if isinstance(declared, list) and declared:
            argv = [
                str(item)
                .replace("{python}", sys.executable)
                .replace("{port}", str(self.port))
                for item in declared
            ]
            if self.site.boot.get("cwd") == ".":
                argv = [
                    item.removeprefix("clone/")
                    if not Path(item).is_absolute()
                    else item
                    for item in argv
                ]
            return [(argv, clone)]
        return [
            ([sys.executable, str(clone / "app.py")], clone),
            (
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "app:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(self.port),
                    "--log-level",
                    "warning",
                ],
                clone,
            ),
        ]

    def _declared_read_paths(self) -> tuple[Path, ...]:
        """Extra site-relative trees this candidate reads at runtime.

        Etsy's runtime loads a frozen embedded-browser corpus that lives beside
        ``clone/``; the deployment package already declares the same set. Each
        entry is resolved inside the site root so a driver file cannot widen the
        sandbox to somewhere else on the machine.
        """

        resolved: list[Path] = []
        root = self.site.root.resolve()
        for relative in self.site.boot.get("read_paths") or ():
            candidate = (root / str(relative)).resolve()
            if candidate == root or root not in candidate.parents:
                raise IsolationUnavailable(
                    f"declared read path escapes the site root: {relative}"
                )
            resolved.append(candidate)
        return tuple(resolved)

    def _environment(self) -> dict[str, str]:
        declared: dict[str, str] = {}
        for key, value in (self.site.boot.get("env") or {}).items():
            declared[str(key)] = str(value).replace("{data_dir}", str(self.data_dir))
        declared.update(self.extra_env)
        return clean_candidate_environment(
            self.data_dir,
            port=self.port,
            declared=declared,
        )

    def _start(self, argv: list[str], cwd: Path, *, budget: float) -> str | None:
        """Start one candidate. Returns None on success, else why it failed."""

        candidate = self.site.manifest.resolve(
            self.site.manifest.data["paths"]["candidate_root"]
        )
        if cwd.resolve() != candidate.resolve():
            return f"boot cwd {cwd} is outside the isolated candidate root"
        self.process = launch_candidate(
            argv,
            candidate_root=candidate,
            data_dir=self.data_dir,
            bind_port=self.port,
            environment=self._environment(),
            connect_ports=set(),
            # The candidate itself is mounted read-only by the shared sandbox,
            # while these frozen site contracts live beside (rather than
            # beneath) ``clone/``.  Several existing runtimes read them at
            # startup or request time, so expose only the two declared contract
            # trees they may legitimately consume.
            read_paths=(
                self.site.root / "backend",
                self.site.root / "scope",
                *self._declared_read_paths(),
            ),
            # V8 and Vinext's WebAssembly modules reserve sparse guard regions
            # far larger than their resident memory. Preserve the ordinary
            # 2 GiB ceiling for every other candidate; the fixed Node launcher
            # separately caps its JS heap at 768 MiB and its worker pools.
            limits=(
                IsolationLimits(memory_mb=131072)
                if "websitebench.offline_clone.node_launcher" in argv
                else IsolationLimits()
            ),
        )
        deadline = time.monotonic() + budget
        while time.monotonic() < deadline:
            if self.process.process.poll() is not None:
                error = self.process.stderr_tail()
                self.process.terminate_tree()
                self.process = None
                return "exited: " + error.strip()
            try:
                with urllib.request.urlopen(
                    f"{self.base_url}/healthz", timeout=2
                ) as response:
                    body = response.read().decode("utf-8")
                    status = response.status
                # Clones disagree on the payload: some answer {"ok": true},
                # taskrabbit answers {"status": "ok"}. A 200 is the part they
                # all mean, and it is what the deploy workflow waits on too.
                if status == 200:
                    try:
                        parsed = json.loads(body)
                        self.health = parsed if isinstance(parsed, dict) else {}
                    except ValueError:
                        self.health = {}
                    return None
            except (OSError, ValueError):
                time.sleep(0.25)
        self.__exit__()
        return f"no healthy /healthz within {budget:.0f}s"

    def __enter__(self) -> CloneServer:
        require_isolation()
        prepare_data_directory(self.data_dir)
        failures: list[str] = []
        candidates = self._candidates()
        for index, (argv, cwd) in enumerate(candidates):
            # Some clones seed a database on first boot; taskrabbit needs well
            # over twenty seconds before it answers.
            budget = 120.0 if index == len(candidates) - 1 else 45.0
            failure = self._start(argv, cwd, budget=budget)
            if failure is None:
                return self
            failures.append(f"{' '.join(argv[-2:])} -> {failure}")
        raise RuntimeError("clone server would not start; " + " | ".join(failures))

    def __exit__(self, *exc_info: object) -> None:
        if self.process is None:
            return
        self.process.terminate_tree()
        self.process = None


def _normalized_fullpage_png(raw_png: bytes, width: int, height: int) -> bytes:
    """Bring a raster to exactly (width, height) for comparison.

    Both sides go through this: a frozen source frame is often a full-page
    capture taller than the contract viewport, and a clone render can be wider
    than the frozen width when the two disagree about scrollbar gutter. Extra
    pixels are cropped from the right and bottom. Missing width is refused --
    a narrower render means content is absent, which is the thing being tested.
    """

    from io import BytesIO

    from PIL import Image

    image = Image.open(BytesIO(raw_png))
    image.load()
    image = image.convert("RGB")
    if image.width < width:
        raise ValueError(
            f"raster width {image.width} is narrower than the frozen width {width}"
        )
    if image.height >= height:
        image = image.crop((0, 0, width, height))
    else:
        canvas = Image.new("RGB", (width, height), (255, 255, 255))
        canvas.paste(image.crop((0, 0, width, image.height)), (0, 0))
        image = canvas
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _pixel_similarity(
    source_png: bytes, clone_png: bytes, contract: dict[str, Any]
) -> float:
    from io import BytesIO

    from PIL import Image, ImageChops, ImageStat

    source = Image.open(BytesIO(source_png))
    source.load()
    clone = Image.open(BytesIO(clone_png))
    clone.load()
    source = source.convert("RGB")
    clone = clone.convert("RGB")
    viewport = (contract["viewport"]["width"], contract["viewport"]["height"])
    if source.size != viewport or clone.size != viewport:
        raise ValueError(
            f"screenshot sizes {source.size}/{clone.size} do not match the frozen "
            f"viewport {viewport}"
        )
    region = contract["comparison_region"]
    box = (
        region["x"],
        region["y"],
        region["x"] + region["width"],
        region["y"] + region["height"],
    )
    difference = ImageChops.difference(source.crop(box), clone.crop(box))
    return 1.0 - sum(ImageStat.Stat(difference).mean) / (
        255 * len(difference.getbands())
    )


def _apply_steps(page: Any, steps: list[dict[str, Any]]) -> None:
    """Drive a declared recipe.

    A step marked ``optional`` is skipped when its target is absent -- a cookie
    banner that a given page never shows must not fail the page.
    """

    for step in steps:
        selector = step.get("click") or step.get("fill")
        if selector is not None:
            locator = page.locator(str(selector))
            if locator.count() == 0:
                if step.get("optional"):
                    continue
                raise LookupError(f"no element matches {selector!r}")
            target = locator.first
            try:
                if "click" in step:
                    target.click(timeout=int(step.get("timeout_ms", 5000)))
                else:
                    target.fill(str(step.get("value", "")))
            except Exception:  # noqa: BLE001 - optional means "if you can"
                # A banner that is present but not clickable on this page is the
                # same situation as one that is absent: an optional step says
                # what to do when it can, not that it must be possible.
                if not step.get("optional"):
                    raise
        elif "goto" in step:
            # A state that lives at its own URL -- a wizard step, a query that
            # produces the empty result -- is reached by navigating there, not
            # by clicking from the checkpoint's base path.
            # Resolved against the page's current URL so a recipe names a path,
            # never the ephemeral port this run happens to have bound.
            page.goto(
                urljoin(page.url, str(step["goto"])), wait_until="domcontentloaded"
            )
        elif "expect" in step:
            # A state that navigation alone reaches still gets to assert what
            # makes it that state, rather than only that the page answered 200.
            if page.locator(str(step["expect"])).count() == 0:
                raise LookupError(f"nothing matches {step['expect']!r}")
        elif "press" in step:
            page.keyboard.press(str(step["press"]))
        elif "eval" in step:
            page.evaluate(str(step["eval"]))
        page.wait_for_timeout(int(step.get("wait_ms", 300)))


def _external_host(url: str) -> str | None:
    parts = urlsplit(url)
    if parts.scheme in INERT_SCHEMES or not parts.scheme:
        return None
    return None if parts.hostname in LOOPBACK_HOSTS else parts.hostname


@dataclass
class NetworkWatch:
    """Where a page's remote requests ended up.

    A reference the clone's own CSP refuses never reaches the network, so it is
    counted rather than reported: the policy did its job. A request that leaves
    the page is a finding whether it succeeded or not -- in a sandbox with no
    route out it fails on DNS, and on a machine with one it would not.
    """

    blocked: int = 0
    escaped: list[str] = field(default_factory=list)

    def intercept(self, route: Any) -> None:
        """Abort a remote request before Chromium puts it on the network."""

        if _external_host(route.request.url):
            self.blocked += 1
            if route.request.url not in self.escaped:
                self.escaped.append(route.request.url)
            route.abort("blockedbyclient")
            return
        route.continue_()

    def on_failed(self, request: Any) -> None:
        if not _external_host(request.url):
            return
        if request.url in self.escaped:
            return
        if "csp" in (request.failure or "").casefold():
            self.blocked += 1
        else:
            self.escaped.append(request.url)

    def on_response(self, response: Any) -> None:
        if _external_host(response.url):
            self.escaped.append(response.url)


def open_session(
    context: Any, server: CloneServer, declared: dict[str, Any], token: str
) -> str | None:
    """Authenticate this browser context. Returns None on success, else why not.

    The clone's own test suites reach a signed-in state through a fixture
    endpoint guarded by an admin token the process reads from its environment.
    The section boots that process, so it mints a fresh token per run and hands it
    to both sides: nothing durable is written, and no fixture secret has to be
    copied into `verify.json`.
    """

    path = declared.get("post")
    if not isinstance(path, str):
        return "session block declares no `post` path"
    headers = {
        str(key): str(value).replace("{{token}}", token)
        for key, value in (declared.get("headers") or {}).items()
    }
    form = {str(k): str(v) for k, v in (declared.get("form") or {}).items()}
    try:
        response = context.request.post(
            server.base_url + path, headers=headers, form=form, max_redirects=0
        )
    except Exception as error:  # noqa: BLE001 - reported, not raised
        return f"session request failed: {error}"
    allowed = declared.get("expect_status") or [200, 302, 303]
    if response.status not in allowed:
        return f"session endpoint answered {response.status}, expected one of {allowed}"
    return None


def _trusted_browser_environment() -> dict[str, str]:
    """Environment for the verifier-owned browser, never for candidate code."""

    environment = os.environ.copy()
    dependency_root = Path.home() / "chromium-libs"
    libraries = dependency_root / "usr" / "lib" / "x86_64-linux-gnu"
    fonts = dependency_root / "etc" / "fonts" / "fonts.conf"
    if libraries.is_dir():
        environment["LD_LIBRARY_PATH"] = str(libraries)
    if fonts.is_file():
        environment["FONTCONFIG_FILE"] = str(fonts)
    return environment


def run_live(site: SiteData) -> SectionResult:
    from playwright.sync_api import sync_playwright

    result = SectionResult(section="live", site_id=site.site_id)
    deadline = time.monotonic() + LIVE_WALL_SECONDS
    visitable = [c for c in site.checkpoints if c.path]
    # One page load per distinct (path, state, viewport); a ledger may name the
    # same page many times over, and visiting it once is the same evidence.
    structural: dict[tuple[str, str, str, str], Checkpoint] = {}
    for checkpoint in sorted(visitable, key=lambda c: c.id):
        structural.setdefault(checkpoint.structural_key, checkpoint)
    # A frozen frame captured in a non-default state can only be compared against
    # a clone driven into that state. With no recipe the comparison would score a
    # different page and call it a fidelity gap, so it is counted instead.
    comparable = [
        c
        for c in sorted(visitable, key=lambda c: c.id)
        if c.visual_contract
        and c.acceptance_eligible
        and c.id not in site.visual_excluded
    ]
    visual = [
        c
        for c in comparable
        if c.state in DEFAULT_STATES or site.steps_for(c) is not None
    ]

    result.checks["checkpoints"] = len(site.checkpoints)
    result.checks["page_loads"] = len(structural)
    result.checks["visual_contracts"] = len(visual)
    result.checks["visual_needs_state_recipe"] = len(comparable) - len(visual)
    result.checks["visual_excluded_by_bad_source"] = len(site.visual_excluded)
    result.checks["session_checkpoints"] = sum(
        1 for c in structural.values() if c.needs_session
    )
    result.checks["sessions_requested"] = len(site.sessions)

    # A fixture session is only reachable when the server was started to allow
    # it: the clones section it on an explicit test-boundary flag, and some also
    # require the request's Host to match a declared admin host. Both are boot
    # environment, so the site declares them and the section mints the token.
    token = secrets.token_hex(16)
    extra_env = {
        str(key): str(value).replace("{{token}}", token)
        for key, value in (site.session.get("env") or {}).items()
    }
    token_env = str(site.session.get("token_env") or "")
    if token_env:
        extra_env[token_env] = token
    with tempfile.TemporaryDirectory(prefix=f"{site.site_id}-live-") as scratch:
        with CloneServer(site, Path(scratch), extra_env=extra_env) as server:
            declared_id = server.health.get("site_id")
            if declared_id is not None and declared_id != site.site_id:
                result.findings.append(
                    Finding(
                        "health-identity",
                        f"/healthz reports site_id {declared_id!r}, manifest declares "
                        f"{site.site_id!r}",
                    )
                )
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    args=[
                        "--font-render-hinting=slight",
                        "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE localhost, "
                        "EXCLUDE 127.0.0.1",
                        "--proxy-server=http://127.0.0.1:9",
                        "--proxy-bypass-list=localhost;127.0.0.1;[::1]",
                        "--disable-webrtc",
                    ],
                    env=_trusted_browser_environment(),
                )
                contexts: dict[str, Any] = {}
                try:
                    for name, declared in site.sessions.items():
                        if time.monotonic() >= deadline:
                            result.incomplete(
                                f"live diagnostic exceeded {LIVE_WALL_SECONDS}s wall limit"
                            )
                            break
                        context = browser.new_context()
                        failure = open_session(
                            context, server, {**site.session, **declared}, token
                        )
                        if failure is None:
                            contexts[name] = context
                        else:
                            result.findings.append(
                                Finding("session-setup", failure, f"session:{name}")
                            )
                            result.incomplete(
                                f"named session {name!r} could not be established"
                            )
                    result.checks["sessions_opened"] = len(contexts)
                    result.checks["sessions_failed"] = len(site.sessions) - len(
                        contexts
                    )
                    result.checks["session_checkpoints_unvisited"] = sum(
                        1
                        for checkpoint in structural.values()
                        if site.session_for(checkpoint) is not None
                        and site.session_for(checkpoint) not in contexts
                    )
                    for checkpoint in structural.values():
                        if time.monotonic() >= deadline:
                            result.incomplete(
                                f"live diagnostic exceeded {LIVE_WALL_SECONDS}s wall limit"
                            )
                            break
                        wanted = site.session_for(checkpoint)
                        if wanted is not None and wanted not in contexts:
                            continue
                        try:
                            _visit(
                                browser,
                                server,
                                site,
                                checkpoint,
                                result,
                                session=contexts.get(wanted) if wanted else None,
                            )
                        except Exception as error:  # noqa: BLE001 - retain coverage
                            result.findings.append(
                                Finding("page-visit", str(error), checkpoint.id)
                            )
                    for checkpoint in visual:
                        if not result.execution_complete:
                            break
                        if time.monotonic() >= deadline:
                            result.incomplete(
                                f"live diagnostic exceeded {LIVE_WALL_SECONDS}s wall limit"
                            )
                            break
                        wanted = site.session_for(checkpoint)
                        if wanted is not None and wanted not in contexts:
                            continue
                        _compare(
                            browser,
                            server,
                            site,
                            checkpoint,
                            result,
                            session=contexts.get(wanted) if wanted else None,
                        )
                finally:
                    browser.close()
    return result


def _visit(
    browser: Any,
    server: CloneServer,
    site: SiteData,
    checkpoint: Checkpoint,
    result: SectionResult,
    session: Any = None,
) -> None:
    context = browser.new_context(
        viewport={"width": checkpoint.width, "height": checkpoint.height},
        device_scale_factor=1,
        # A checkpoint behind a session is visited carrying that session's
        # cookies; every other one stays anonymous.
        storage_state=session.storage_state() if session is not None else None,
    )
    network = NetworkWatch()
    try:
        context.set_default_timeout(10_000)
        context.set_default_navigation_timeout(15_000)
        context.route("**/*", network.intercept)
        page = context.new_page()
        page.on("requestfailed", network.on_failed)
        page.on("response", network.on_response)
        response = page.goto(
            server.base_url + (checkpoint.path or "/"), wait_until="networkidle"
        )
        expected = site.expected_status.get(checkpoint.route_id, 200)
        if response is None or response.status != expected:
            status = "no response" if response is None else response.status
            result.findings.append(
                Finding(
                    "route-status",
                    f"{checkpoint.path} answered {status}, expected {expected}",
                    checkpoint.id,
                )
            )
            return
        if not page.title().strip():
            result.findings.append(
                Finding(
                    "page-title", f"{checkpoint.path} renders no title", checkpoint.id
                )
            )
        try:
            _apply_steps(page, site.prepare)
        except Exception as error:  # noqa: BLE001 - reported, not raised
            result.findings.append(Finding("prepare-failed", str(error), checkpoint.id))
        if checkpoint.state not in DEFAULT_STATES:
            steps = site.steps_for(checkpoint)
            if steps is None:
                # Nobody has said how to reach this state, so nobody claimed it
                # was verified. That is a coverage number, not a defect. A
                # recipe that exists and fails is the defect.
                bucket = (
                    "states_out_of_scope"
                    if any(marker in checkpoint.state for marker in site.out_of_scope)
                    else "undeclared_states"
                )
                result.checks[bucket] = result.checks.get(bucket, 0) + 1
            else:
                try:
                    _apply_steps(page, steps)
                except Exception as error:  # noqa: BLE001 - reported, not raised
                    result.findings.append(
                        Finding(
                            "state-unreachable",
                            f"recipe for {checkpoint.state!r} failed: {error}",
                            checkpoint.id,
                        )
                    )
        else:
            width = int(page.evaluate("document.documentElement.scrollWidth"))
            if width > checkpoint.width + 1:
                if checkpoint.acceptance_eligible:
                    result.findings.append(
                        Finding(
                            "horizontal-overflow",
                            f"content is {width}px wide at a {checkpoint.width}px viewport",
                            checkpoint.id,
                        )
                    )
                else:
                    # The ledger marks this route/viewport as having no frozen
                    # source. Whether the real site also overflowed there is
                    # exactly what nobody captured, so it is counted rather
                    # than charged to the clone.
                    result.checks["overflow_without_source_evidence"] = (
                        result.checks.get("overflow_without_source_evidence", 0) + 1
                    )
        if network.escaped:
            result.findings.append(
                Finding(
                    "external-request",
                    f"{len(network.escaped)} remote request(s) were attempted and "
                    f"blocked, first: {network.escaped[0][:110]}",
                    checkpoint.id,
                )
            )
        result.checks["blocked_external_references"] = (
            result.checks.get("blocked_external_references", 0) + network.blocked
        )
    finally:
        context.close()


def _compare(
    browser: Any,
    server: CloneServer,
    site: SiteData,
    checkpoint: Checkpoint,
    result: SectionResult,
    session: Any = None,
) -> None:
    contract = checkpoint.visual_contract or {}
    source_path = site.root / str(contract["source_artifact_path"])
    try:
        source_png = source_path.read_bytes()
    except OSError as error:
        result.notes.append(
            Finding(
                "visual-source",
                f"frozen source raster unreadable: {error}",
                checkpoint.id,
            )
        )
        return
    width = int(contract["viewport"]["width"])
    height = int(contract["viewport"]["height"])
    context = browser.new_context(
        viewport={"width": width, "height": min(height, 2000)},
        device_scale_factor=1,
        storage_state=session.storage_state() if session is not None else None,
    )
    network = NetworkWatch()
    try:
        context.set_default_timeout(10_000)
        context.set_default_navigation_timeout(15_000)
        context.route("**/*", network.intercept)
        page = context.new_page()
        page.goto(server.base_url + (checkpoint.path or "/"), wait_until="networkidle")
        _apply_steps(page, site.prepare)
        if checkpoint.state not in DEFAULT_STATES:
            steps = site.steps_for(checkpoint)
            if steps:
                _apply_steps(page, steps)
        page.wait_for_timeout(400)
        raw = page.screenshot(type="png", full_page=True)
    finally:
        context.close()

    if network.escaped:
        result.findings.append(
            Finding(
                "external-request",
                f"{len(network.escaped)} remote request(s) were attempted and "
                f"blocked during visual capture, first: {network.escaped[0][:110]}",
                checkpoint.id,
            )
        )

    try:
        clone_png = _normalized_fullpage_png(raw, width, height)
        source_png = _normalized_fullpage_png(source_png, width, height)
        score = _pixel_similarity(source_png, clone_png, contract)
    except (ValueError, OSError) as error:
        result.notes.append(Finding("visual-compare", str(error), checkpoint.id))
        return
    threshold = float(contract.get("threshold", 0.0))
    relation = "below" if score < threshold else "at or above"
    result.notes.append(
        Finding(
            "visual-similarity",
            f"similarity {score:.4f} is {relation} the frozen reference "
            f"threshold {threshold}",
            checkpoint.id,
        )
    )


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------


def verify(site_dir: Path, sections: tuple[str, ...] = DIAGNOSTIC_SECTIONS) -> dict[str, Any]:
    """Run requested diagnostic sections and return one stateless report."""

    requested = tuple(dict.fromkeys(sections))
    if not requested:
        raise ValueError("at least one diagnostic section is required")
    unknown = sorted(set(requested) - set(DIAGNOSTIC_SECTIONS))
    if unknown:
        raise ValueError(f"unknown diagnostic section(s): {', '.join(unknown)}")
    try:
        site = load_site(site_dir)
    except Exception as error:  # noqa: BLE001 - invalid input is reportable
        section_reports: dict[str, dict[str, Any]] = {}
        for section in requested:
            result = SectionResult(section=section, site_id=site_dir.name)
            result.incomplete(f"input could not be loaded: {error}")
            section_reports[section] = result.as_dict()
        return {
            "schema_version": DIAGNOSTIC_SCHEMA_VERSION,
            "authority": DIAGNOSTIC_AUTHORITY,
            "qualification": DIAGNOSTIC_QUALIFICATION,
            "site_id": site_dir.name,
            "generated_at": utc_now(),
            "diagnostic_status": "incomplete",
            "requested_sections": list(requested),
            "sections": section_reports,
        }

    results: dict[str, SectionResult] = {}
    for section in DIAGNOSTIC_SECTIONS:
        if section not in requested:
            continue
        try:
            if section == "static":
                results[section] = run_static(site)
                continue
            # Live runs even when static has findings: one diagnostic section
            # must not blind the other.
            results[section] = run_live(site)
        except (IsolationUnavailable, OSError, RuntimeError) as error:
            result = SectionResult(section=section, site_id=site.site_id)
            result.incomplete(str(error))
            results[section] = result
        except Exception as error:  # noqa: BLE001 - preserve a usable report
            result = SectionResult(section=section, site_id=site.site_id)
            result.incomplete(f"diagnostic execution stopped: {error}")
            results[section] = result

    incomplete = any(not result.execution_complete for result in results.values())
    findings = any(result.findings for result in results.values())
    diagnostic_status = (
        "incomplete" if incomplete else "findings" if findings else "clean"
    )
    return {
        "schema_version": DIAGNOSTIC_SCHEMA_VERSION,
        "authority": DIAGNOSTIC_AUTHORITY,
        "qualification": DIAGNOSTIC_QUALIFICATION,
        "site_id": site.site_id,
        "generated_at": utc_now(),
        "diagnostic_status": diagnostic_status,
        "requested_sections": list(requested),
        "sections": {section: result.as_dict() for section, result in results.items()},
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="websitebench-offline-clone verify",
        description="Diagnose one offline clone with generic static and live sections.",
    )
    parser.add_argument("--site", type=Path, required=True)
    parser.add_argument("--section", choices=DIAGNOSTIC_SECTIONS, action="append")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)

    report = verify(args.site, tuple(args.section) if args.section else DIAGNOSTIC_SECTIONS)
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 2 if report["diagnostic_status"] == "incomplete" else 0


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())
