"""Derive a Harbor OpenCLI interaction contract from a finished offline clone.

The clone build already walks every route and captures what it saw. Two of those
artifacts carry everything a contract needs except selectors:

* ``tools/frontend_samples.json`` — concrete clone URLs, methods, form
  payloads and expectations, all proven to hold against the built clone.
* ``scope/routes.json`` and ``scope/invariants.json`` — priority and the local
  semantics a profile is meant to exercise.

``scope/routes.json`` is deliberately *not* the route source: ``route_pattern``
describes the upstream site and is frequently prose ("GET /start-a-petition
observed HTTP 301; the followed document was ..."). The samples file describes
the clone, which is what a contract drives.

What derivation cannot produce is a selector. No captured artifact holds one —
it is knowledge the agent has while walking the routes and currently discards.
The returned ``pending`` list reports those gaps directly; no binding sidecar is
written.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator, FormatChecker

from ..offline_clone.manifest import ManifestValidationError, load_manifest
from ..offline_clone.toolbox import write_json_atomic
from .manifest import load_schema, load_site
from .opencli import adapters as opencli_adapters
from .opencli.contract import CONTRACT_SCHEMA_VERSION, load_contract_from_site

CONTRACT_SCHEMA = "harbor-opencli-interaction-contract.schema.json"
CONTRACT_NAME = "opencli-interaction-contract.json"
OPENCLI_VERSION = "1.8.6"

DEFAULT_MAX_PROFILES = 2
DEFAULT_MAX_STEPS = 6
MAX_ASSERTIONS_PER_STEP = 2
NETWORK_ALLOWLIST = ("127.0.0.1", "localhost")

# The clone manifest and the Harbor site agree on an id everywhere but here.
# Keep this table empty-by-default and explicit: a silent fuzzy match would
# happily bind a contract to the wrong site.
SITE_ID_ALIASES: dict[str, str] = {}


class DerivationError(ValueError):
    """Raised when a contract cannot be derived from a clone."""


@dataclass
class Pending:
    """One thing derivation could not do mechanically."""

    kind: str
    detail: str

    def payload(self) -> dict[str, str]:
        return {"kind": self.kind, "detail": self.detail[:400]}


@dataclass
class Derivation:
    """A derived contract plus the record of where it came from."""

    site_id: str
    contract: dict[str, Any]
    pending: list[Pending] = field(default_factory=list)
    inputs: list[Path] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Repository / site resolution
# ---------------------------------------------------------------------------


def repository_root(start: Path) -> Path:
    """Walk up to the directory holding both ``materials/`` and ``harbor/``.

    ``generated_from`` is repository-root-relative because the contract schema's
    ``relative_path`` ``$def`` forbids ``..`` — a path relative to
    ``interactions/`` could never reach ``materials/``.
    """

    for candidate in [start.resolve(), *start.resolve().parents]:
        if (candidate / "materials").is_dir() and (candidate / "harbor").is_dir():
            return candidate
    raise DerivationError(
        f"{start}: no repository root above this path holds both materials/ and harbor/"
    )


def relative_to_repository(path: Path, repository: Path) -> str:
    try:
        return path.resolve().relative_to(repository).as_posix()
    except ValueError as exc:
        raise DerivationError(
            f"{path} is outside the repository at {repository}"
        ) from exc


def harbor_site_manifest(repository: Path, clone_site_id: str) -> Path | None:
    """Return the ``site.yaml`` for a clone's Harbor site, if one exists."""

    direct = repository / "harbor" / "sites" / clone_site_id / "site.yaml"
    if direct.is_file():
        return direct
    alias = SITE_ID_ALIASES.get(clone_site_id)
    if alias:
        aliased = repository / "harbor" / "sites" / alias / "site.yaml"
        if aliased.is_file():
            return aliased
    return None


def clone_manifests(repository: Path) -> list[Path]:
    return sorted((repository / "materials").glob("*/clone.yaml"))


# ---------------------------------------------------------------------------
# Expectation classification
# ---------------------------------------------------------------------------

# An expectation only reaches `visible` if it survives visibleText(), which
# strips every tag. Anything living in an attribute — an asset filename, a
# data-* value, a bare markup fragment — must go to `body_contains` or it would
# fail against a perfectly correct clone.
_MARKUP_HINT = re.compile(r'[<>]|="')
_ASSET_LIKE = re.compile(
    r"^[\w./-]+\.(?:jpg|jpeg|png|gif|svg|webp|avif|ico|css|js|mjs|woff2?|mp4|webm)$",
    re.IGNORECASE,
)
# `data-testid="rate-dialog"`-style tokens read as prose but only ever appear in
# an attribute. The asymmetry decides the rule: raw markup is a superset of
# rendered text, so misrouting visible text to `body_contains` merely weakens an
# assertion, while misrouting an attribute value to `visible` breaks a contract
# against a perfectly correct clone.
_IDENTIFIER_LIKE = re.compile(r"^[a-z0-9]+(?:[-_][a-z0-9]+)+$")
_LIST_TOKEN = re.compile(
    r"(?:^|[.\-_])(?:results?|lists?|favou?rites?|search)(?:$|[.\-_])"
)

_ENTITIES = (
    ("&nbsp;", " "),
    ("&amp;", "&"),
    ("&lt;", "<"),
    ("&gt;", ">"),
    ("&quot;", '"'),
    ("&#39;", "'"),
)


def looks_like_markup(value: str) -> bool:
    """True when an expectation can only be found in raw markup."""

    stripped = value.strip()
    if not stripped:
        return False
    return (
        bool(_MARKUP_HINT.search(stripped))
        or bool(_ASSET_LIKE.match(stripped))
        or bool(_IDENTIFIER_LIKE.match(stripped))
    )


def as_visible_text(value: str) -> str:
    """Normalize an expectation the way ``visibleText`` normalizes a page.

    ``visibleText`` decodes entities and collapses whitespace, so an expectation
    written as ``Dogs &amp; Puppies`` never matches unless it is decoded first.
    """

    text = value
    for entity, replacement in _ENTITIES:
        text = text.replace(entity, replacement)
    return re.sub(r"\s+", " ", text).strip()


def _slug_id(check_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]", "-", check_id.replace(".", "-"))[:120]


def _observation_id(site_id: str, check_id: str) -> str:
    raw = f"{site_id}_{check_id}".lower().replace(".", "_")
    cleaned = re.sub(r"[^a-z0-9._/-]", "-", raw)
    cleaned = cleaned.lstrip("._/-") or "observation"
    return cleaned[:120]


# ---------------------------------------------------------------------------
# Clone artifacts
# ---------------------------------------------------------------------------


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DerivationError(f"{path}: cannot read JSON: {exc}") from exc


def samples_path(manifest_root: Path) -> Path | None:
    candidate = manifest_root / "tools" / "frontend_samples.json"
    return candidate if candidate.is_file() else None


def _scope_path(manifest_data: dict[str, Any], root: Path, name: str) -> Path | None:
    scope = manifest_data.get("scope")
    if not isinstance(scope, dict):
        return None
    relative = scope.get(name)
    if not isinstance(relative, str):
        return None
    candidate = root / relative
    return candidate if candidate.is_file() else None


def _form_actions(clone_root: Path) -> dict[str, int]:
    """Count ``<form method="post" action=X>`` occurrences across clone templates.

    A ``submit`` step GETs its route, resolves a form by selector and posts it.
    That only works when the form is reachable, so a selector is only derived
    when exactly one template declares the action.
    """

    counts: dict[str, int] = {}
    if not clone_root.is_dir():
        return counts
    for template in sorted(clone_root.rglob("*.html")):
        try:
            body = template.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for match in re.finditer(r"<form\b([^>]*)>", body, re.IGNORECASE):
            attributes = dict(
                (name.lower(), value)
                for name, value in re.findall(
                    r"([\w:-]+)\s*=\s*\"([^\"]*)\"", match.group(1)
                )
            )
            if attributes.get("method", "get").lower() != "post":
                continue
            action = attributes.get("action")
            if action:
                counts[action] = counts.get(action, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# Derivation
# ---------------------------------------------------------------------------


def _required_state(check: dict[str, Any], pending: list[Pending]) -> dict[str, str]:
    """Map sample expectations onto the keys ``_wb.js`` can actually assert."""

    check_id = str(check.get("id", ""))
    contains = [
        item for item in check.get("expect_contains", []) if isinstance(item, str)
    ]
    absent = [
        item for item in check.get("expect_not_contains", []) if isinstance(item, str)
    ]

    ordered: list[tuple[str, str]] = []
    markup: set[str] = set()
    for value in contains:
        if looks_like_markup(value):
            ordered.append(("body_contains", value))
            markup.add(value)
        elif _LIST_TOKEN.search(check_id):
            ordered.append(("list_contains", as_visible_text(value)))
        else:
            ordered.append(("visible", as_visible_text(value)))
    for value in absent:
        ordered.append(("text_absent", as_visible_text(value)))

    state: dict[str, str] = {}
    dropped: list[str] = []
    for key, value in ordered:
        # `required_state` is a mapping, so a second `visible` would overwrite
        # the first. Both limits are real; neither may drop an expectation
        # silently.
        if key in state or len(state) >= MAX_ASSERTIONS_PER_STEP:
            dropped.append(value)
            continue
        state[key] = value
    # Report only on what survived: flagging an expectation as brittle and then
    # dropping it in the same breath sends the agent after nothing.
    for value in state.values():
        if value in markup:
            pending.append(
                Pending(
                    "markup-assertion",
                    f"check {check_id}: {value!r} is matched against raw markup; "
                    "prefer a rendered-text expectation when one exists",
                )
            )
    if dropped:
        # One aggregated entry per check: a per-value entry buries the pending
        # list under noise from the two or three checks that assert the most.
        preview = ", ".join(repr(value) for value in dropped[:4])
        more = f" (+{len(dropped) - 4} more)" if len(dropped) > 4 else ""
        pending.append(
            Pending(
                "dropped-expectation",
                f"check {check_id}: {len(dropped)} expectation(s) did not fit "
                f"this step — {preview}{more}. Split the step to keep them.",
            )
        )
    return state


def _route_priority(routes: Any, group: str) -> str:
    """Resolve a profile tier from scope route priorities.

    Sample check-id prefixes and route ids agree by prefix, not equality
    (``find`` vs ``find-search``), so match on prefix and fall back to p1.
    """

    entries = routes.get("routes") if isinstance(routes, dict) else None
    if not isinstance(entries, list):
        return "p1"
    matched = [
        entry
        for entry in entries
        if isinstance(entry, dict)
        and isinstance(entry.get("id"), str)
        and (entry["id"] == group or entry["id"].startswith(f"{group}-"))
    ]
    if not matched:
        return "p1"
    return "p0" if all(entry.get("priority") == "p0" for entry in matched) else "p1"


def _clip(text: str, limit: int = 160) -> str:
    """Truncate on a word boundary. A statement cut mid-word reads as corruption."""

    text = text.strip()
    if len(text) <= limit:
        return text
    head = text[: limit - 1]
    space = head.rfind(" ")
    return (head[:space] if space > limit // 2 else head).rstrip(" ,;:") + "…"


def _local_semantics(invariants: Any) -> list[str]:
    entries = invariants.get("invariants") if isinstance(invariants, dict) else None
    statements: list[str] = []
    if isinstance(entries, list):
        for entry in entries:
            if not isinstance(entry, dict) or entry.get("priority") != "p0":
                continue
            statement = entry.get("statement")
            if isinstance(statement, str) and statement.strip():
                statements.append(_clip(statement))
            if len(statements) >= 3:
                break
    if not statements:
        statements.append("Local clone semantics are enforced at the server boundary.")
    return statements


def _journey_paths(journeys: Any, group: str) -> tuple[list[str], list[str]]:
    """Failure and recovery journeys belonging to this profile's family.

    Unfiltered, every profile would claim every journey in the clone — a `find`
    profile listing watchlist failure paths is worse than listing none.
    """

    entries = journeys.get("journeys") if isinstance(journeys, dict) else None
    failure: list[str] = []
    recovery: list[str] = []
    if isinstance(entries, list):
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            label = entry.get("id")
            if not isinstance(label, str):
                continue
            family = str(entry.get("family") or label).split(".", 1)[0]
            if family != group and not family.startswith(f"{group}-"):
                continue
            kind = entry.get("kind")
            if kind == "failure" and len(failure) < 4:
                failure.append(_clip(label))
            elif kind in {"retry", "recovery"} and len(recovery) < 4:
                recovery.append(_clip(label))
    return failure, recovery


def _session_block(
    samples: dict[str, Any], pending: list[Pending]
) -> dict[str, Any] | None:
    setup = samples.get("session_setup")
    if not isinstance(setup, dict):
        return None
    headers = setup.get("headers")
    if isinstance(headers, dict) and headers:
        # `session` in the contract carries route/method/fields only, and the
        # runner posts a plain form. Emitting a session that silently 403s is
        # worse than emitting none, so refuse and say why.
        pending.append(
            Pending(
                "session-headers",
                f"session_setup requires {len(headers)} custom header(s), which "
                "the contract session block "
                "cannot express; only unauthenticated checks were derived",
            )
        )
        return None
    if str(setup.get("method", "post")).lower() != "post":
        pending.append(
            Pending(
                "session-headers",
                f"session_setup method {setup.get('method')!r} is not POST; "
                "only unauthenticated checks were derived",
            )
        )
        return None
    url = str(setup.get("url") or "").lstrip("/")
    data = setup.get("data")
    if not url or not isinstance(data, dict) or not data:
        return None
    return {
        "route": url,
        "method": "POST",
        "fields": {str(key): str(value) for key, value in data.items()},
        "notes": (
            "Derived from tools/frontend_samples.json session_setup. These are "
            "public local fixture values, not credentials."
        ),
    }


def _grouped_checks(checks: list[Any]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for check in checks:
        if not isinstance(check, dict) or not isinstance(check.get("id"), str):
            continue
        groups.setdefault(check["id"].split(".", 1)[0], []).append(check)
    return groups


def derive_contract(
    *,
    site_id: str,
    manifest_root: Path,
    manifest_data: dict[str, Any],
    max_profiles: int = DEFAULT_MAX_PROFILES,
    max_steps: int = DEFAULT_MAX_STEPS,
) -> Derivation:
    """Derive a contract payload from one clone's captured artifacts."""

    samples_file = samples_path(manifest_root)
    if samples_file is None:
        raise DerivationError(
            f"{manifest_root}: no tools/frontend_samples.json; this clone "
            "describes its frontend another way, so a contract cannot be derived "
        )
    samples = _read_json(samples_file)
    if not isinstance(samples, dict) or not isinstance(samples.get("checks"), list):
        raise DerivationError(f"{samples_file}: expected an object with a checks list")

    pending: list[Pending] = []
    inputs = [samples_file]
    session = _session_block(samples, pending)

    routes_file = _scope_path(manifest_data, manifest_root, "routes")
    invariants_file = _scope_path(manifest_data, manifest_root, "invariants")
    journeys_file = _scope_path(manifest_data, manifest_root, "journeys")
    routes = _read_json(routes_file) if routes_file else {}
    invariants = _read_json(invariants_file) if invariants_file else {}
    journeys = _read_json(journeys_file) if journeys_file else {}
    inputs.extend(
        path
        for path in (routes_file, invariants_file, journeys_file)
        if path is not None
    )

    clone_root = manifest_root / str(
        manifest_data.get("paths", {}).get("candidate_root", "clone")
    )
    form_actions = _form_actions(clone_root)
    gettable = {
        str(check.get("url"))
        for check in samples["checks"]
        if isinstance(check, dict) and str(check.get("method", "get")).lower() == "get"
    }

    groups = _grouped_checks(samples["checks"])
    ranked = sorted(
        groups.items(),
        key=lambda item: (
            -sum(
                1
                for check in item[1]
                if str(check.get("method", "get")).lower() == "post"
            ),
            -len(item[1]),
            item[0],
        ),
    )

    profiles: dict[str, dict[str, Any]] = {}
    for group, checks in ranked:
        if len(profiles) >= max_profiles:
            break
        group_pending: list[Pending] = []
        steps: list[dict[str, Any]] = []
        for check in checks:
            if len(steps) >= max_steps:
                break
            step = _derive_step(
                check,
                site_id=site_id,
                session=session,
                form_actions=form_actions,
                gettable=gettable,
                pending=group_pending,
            )
            if step is not None:
                steps.append(step)
        if not steps:
            continue
        failure_paths, recovery_paths = _journey_paths(journeys, group)
        if journeys and not failure_paths and not recovery_paths:
            group_pending.append(
                Pending(
                    "unmapped-journey",
                    f"profile {group!r} matched no journey in scope/journeys.json "
                    "by family or kind; its failure and recovery paths are empty",
                )
            )
        profiles[group] = {
            "label": f"{site_id} {group.replace('-', ' ')} (derived draft)"[:180],
            "tier": _route_priority(routes, group),
            "steps": steps,
            "local_semantics": _local_semantics(invariants),
            "failure_paths": failure_paths,
            "recovery_paths": recovery_paths,
            "network": {
                "allowlist": list(NETWORK_ALLOWLIST),
                "notes": "Only local verifier/candidate hostnames are expected.",
            },
        }
        if session is not None and any(check.get("session") for check in checks):
            profiles[group]["session"] = session
        # Only report pending work for profiles that were actually emitted.
        pending.extend(group_pending)

    if not profiles:
        raise DerivationError(
            f"{samples_file}: no check produced a derivable step. Every check "
            "either asserts nothing or needs a session this contract cannot "
            "establish."
        )

    contract = {
        "schema_version": CONTRACT_SCHEMA_VERSION,
        "opencli_version": OPENCLI_VERSION,
        "site_id": site_id,
        # Filled in by the caller, which knows the repository root.
        "profiles": {key: profiles[key] for key in sorted(profiles)},
    }
    return Derivation(
        site_id=site_id, contract=contract, pending=pending, inputs=inputs
    )


def _derive_step(
    check: dict[str, Any],
    *,
    site_id: str,
    session: dict[str, Any] | None,
    form_actions: dict[str, int],
    gettable: set[str],
    pending: list[Pending],
) -> dict[str, Any] | None:
    check_id = str(check.get("id", ""))
    url = str(check.get("url") or "")
    method = str(check.get("method", "get")).lower()

    if check.get("session") and session is None:
        pending.append(
            Pending(
                "session-headers",
                f"check {check_id} needs an authenticated session; skipped",
            )
        )
        return None

    route = url.lstrip("/")
    if not route:
        # `route` is minLength 1, so the site root is literally unrepresentable.
        pending.append(
            Pending(
                "unresolved-route",
                f"check {check_id} targets the site root, which the contract "
                "route field cannot express; add an explicit index route",
            )
        )
        return None

    step_pending: list[Pending] = []
    required_state = _required_state(check, step_pending)
    if not required_state:
        pending.append(
            Pending(
                "dropped-expectation",
                f"check {check_id} asserts nothing beyond a status code "
                f"({check.get('expect_status')}); a step that cannot fail was "
                "not emitted. Add a required_state from the interaction ledger.",
            )
        )
        return None

    if method == "post":
        # A submit step GETs `route`, finds a form and posts it — so the route
        # must be a page that hosts the form, not the POST endpoint itself.
        if url not in gettable or form_actions.get(url, 0) != 1:
            pending.append(
                Pending(
                    "selector",
                    f"check {check_id} posts to {url}, which is not a uniquely "
                    "form-backed GET route; supply the hosting route and the form "
                    "selector from the interaction ledger",
                )
            )
            return None
        command = "submit"
        selector = f'form[action="{url}"]'
    elif method == "get":
        command = "state"
        selector = None
    else:
        pending.append(
            Pending(
                "unresolved-route",
                f"check {check_id} uses method {method!r}, which has no contract "
                "command; only get and post are derivable",
            )
        )
        return None

    pending.extend(step_pending)
    step: dict[str, Any] = {
        "id": _slug_id(check_id),
        "observation_id": _observation_id(site_id, check_id),
        "command": command,
        "route": route,
        "intent": (f"Exercise clone check {check_id} ({method.upper()} {url}).")[:255],
        "required_state": required_state,
    }
    if selector:
        step["selector"] = selector
    data = check.get("data")
    if command == "submit" and isinstance(data, dict) and data:
        step["fields"] = {str(key): str(value) for key, value in data.items()}
    return step


# ---------------------------------------------------------------------------
# Sidecar
# ---------------------------------------------------------------------------


def validate_payload(value: Any, schema_name: str, label: str) -> list[str]:
    validator = Draft202012Validator(
        load_schema(schema_name), format_checker=FormatChecker()
    )
    problems: list[str] = []
    for error in sorted(validator.iter_errors(value), key=lambda item: list(item.path)):
        suffix = ".".join(str(part) for part in error.absolute_path)
        problems.append(f"{label}{'.' + suffix if suffix else ''}: {error.message}")
    return problems


@dataclass(frozen=True)
class CloneBinding:
    """One clone manifest resolved against its Harbor site."""

    manifest_path: Path
    manifest_root: Path
    manifest_data: dict[str, Any]
    repository: Path
    site_manifest: Path | None
    site_id: str

    @property
    def site_root(self) -> Path | None:
        return self.site_manifest.parent if self.site_manifest else None


def bind_clone(
    clone_manifest: Path, *, harbor_site: Path | None = None
) -> CloneBinding:
    path = clone_manifest.resolve()
    if not path.is_file():
        raise DerivationError(f"{clone_manifest}: no such clone manifest")
    try:
        manifest = load_manifest(path)
    except ManifestValidationError as exc:
        raise DerivationError(f"{path}: invalid clone manifest: {exc}") from exc
    repository = repository_root(manifest.root)
    clone_site_id = str(manifest.data["site_id"])
    if harbor_site is not None:
        site_manifest = (
            harbor_site if harbor_site.is_file() else harbor_site / "site.yaml"
        )
        if not site_manifest.is_file():
            raise DerivationError(f"{harbor_site}: no site.yaml here")
    else:
        site_manifest = harbor_site_manifest(repository, clone_site_id)
    site_id = clone_site_id
    if site_manifest is not None:
        site_id = str(load_site(site_manifest, allow_legacy_v1=True).data["site_id"])
    return CloneBinding(
        manifest_path=path,
        manifest_root=manifest.root,
        manifest_data=manifest.data,
        repository=repository,
        site_manifest=site_manifest,
        site_id=site_id,
    )


def instances_missing_profile(
    repository: Path, site_manifest: Path, profiles: set[str]
) -> list[str]:
    """Instances of this site that no valid ``opencli_profile`` covers.

    ``tests/harbor/test_opencli_contracts.py`` fails the whole corpus when a
    site declares ``opencli`` and any of its instances does not name a profile
    the contract defines. Catching it here turns a confusing corpus-wide
    failure into a local, actionable refusal.

    An instance names its site by path (``site_manifest: sites/<id>/site.yaml``,
    relative to ``harbor/``) and carries no ``site_id`` of its own, so ownership
    is resolved by comparing the manifest paths.
    """

    harbor = repository / "harbor"
    target = site_manifest.resolve()
    offenders: list[str] = []
    for path in sorted((harbor / "instances").glob("*/instance.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            continue
        if not isinstance(data, dict) or not isinstance(data.get("site_manifest"), str):
            continue
        if (harbor / data["site_manifest"]).resolve() != target:
            continue
        if data.get("opencli_profile") not in profiles:
            offenders.append(str(data.get("instance_id") or path.parent.name))
    return offenders


def require_current_site_instance(repository: Path, site_manifest: Path) -> None:
    """Require the current same-id site/instance pair before derivation."""

    site = load_site(site_manifest, allow_legacy_v1=True)
    if site.data.get("schema_version") != "websitebench.harbor.site.v2":
        return
    site_id = str(site.data["site_id"])
    owned: list[Path] = []
    for path in sorted((repository / "harbor" / "instances").glob("*/instance.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("site_manifest"), str):
            continue
        if (
            repository / "harbor" / data["site_manifest"]
        ).resolve() == site_manifest.resolve():
            owned.append(path)
    expected = repository / "harbor" / "instances" / site_id / "instance.yaml"
    if owned != [expected]:
        found = ", ".join(path.parent.name for path in owned) or "none"
        raise DerivationError(
            f"current Harbor site {site_id!r} requires exactly one same-id instance "
            f"at {expected}; found {found}"
        )


def assign_instance_profiles(
    repository: Path, assignments: dict[str, str], profiles: set[str]
) -> list[Path]:
    written: list[Path] = []
    for instance_id, profile_id in sorted(assignments.items()):
        if profile_id not in profiles:
            raise DerivationError(
                f"--assign-profile {instance_id}={profile_id}: the contract "
                f"defines no such profile (have: {', '.join(sorted(profiles))})"
            )
        path = repository / "harbor" / "instances" / instance_id / "instance.yaml"
        if not path.is_file():
            raise DerivationError(f"{path}: no such instance")
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise DerivationError(f"{path}: expected a mapping")
        data["opencli_profile"] = profile_id
        path.write_text(
            yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8"
        )
        written.append(path)
    return written


def ensure_site_opencli_block(site_manifest: Path, contract_relative: str) -> bool:
    """Add the site's ``opencli`` block if it has none. Returns True if written."""

    data = yaml.safe_load(site_manifest.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise DerivationError(f"{site_manifest}: expected a mapping")
    if isinstance(data.get("opencli"), dict):
        return False
    data["opencli"] = {
        "version": OPENCLI_VERSION,
        "contract": contract_relative,
        "network_requirements": {
            "allowlist": list(NETWORK_ALLOWLIST),
            "notes": "Replay runs against a local clone only; no upstream origin.",
        },
    }
    site_manifest.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    return True


# ---------------------------------------------------------------------------
# Operations
# ---------------------------------------------------------------------------


def _write_contract(path: Path, contract: dict[str, Any]) -> None:
    problems = validate_payload(contract, CONTRACT_SCHEMA, "contract")
    if problems:
        raise DerivationError("; ".join(problems))
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(path, contract)


def _regenerate_adapters(site_manifest: Path) -> list[str]:
    site = load_site(site_manifest, allow_legacy_v1=True)
    contract = load_contract_from_site(site_manifest, allow_legacy_v1=True)
    display_name = str(site.data.get("display_name") or contract.site_id)
    rendered = opencli_adapters.render_for_contract(contract, display_name)
    written = opencli_adapters.write(rendered, site.root / "interactions" / "adapters")
    return [str(path) for path in written]


def run_derive(
    *,
    clone_manifest: Path,
    harbor_site: Path | None = None,
    max_profiles: int = DEFAULT_MAX_PROFILES,
    max_steps: int = DEFAULT_MAX_STEPS,
    assign_profile: dict[str, str] | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Generate one site's interaction contract and matching adapters."""

    binding = bind_clone(clone_manifest, harbor_site=harbor_site)
    if binding.site_manifest is None or binding.site_root is None:
        raise DerivationError(
            f"{binding.manifest_path}: clone site_id "
            f"{binding.manifest_data['site_id']!r} maps to no harbor/sites/<id>/. "
            "Create it with `websitebench-harbor init-site` first, or pass "
            "--harbor-site."
        )
    require_current_site_instance(binding.repository, binding.site_manifest)
    site_root = binding.site_root
    interactions = site_root / "interactions"
    contract_path = interactions / CONTRACT_NAME
    generated_from = relative_to_repository(binding.manifest_path, binding.repository)

    if contract_path.is_file() and not force:
        raise DerivationError(
            f"{contract_path}: a contract already exists; pass --force to overwrite it"
        )
    derivation = _derive_bound(binding, max_profiles, max_steps, generated_from)
    profiles = set(derivation.contract["profiles"])
    if assign_profile:
        site = load_site(binding.site_manifest, allow_legacy_v1=True)
        if site.data.get("schema_version") == "websitebench.harbor.site.v2" and set(
            assign_profile
        ) != {binding.site_id}:
            raise DerivationError(
                "current Harbor profile assignment must target the unique same-id "
                f"instance {binding.site_id!r}"
            )
        assign_instance_profiles(binding.repository, assign_profile, profiles)
    offenders = instances_missing_profile(
        binding.repository, binding.site_manifest, profiles
    )
    if offenders:
        raise DerivationError(
            f"instance(s) {', '.join(offenders)} declare no opencli_profile "
            f"among {', '.join(sorted(profiles))}; re-run with "
            "--assign-profile <site-id>=<profile>"
        )
    _write_contract(contract_path, derivation.contract)

    contract_relative = f"interactions/{CONTRACT_NAME}"
    if ensure_site_opencli_block(binding.site_manifest, contract_relative):
        site_opencli_block_written = True
    else:
        site_opencli_block_written = False
    return {
        "status": "derived",
        "site_id": binding.site_id,
        "clone_manifest": generated_from,
        "contract": str(contract_path),
        "profiles": sorted(profiles),
        "pending": [item.payload() for item in derivation.pending],
        "site_opencli_block_written": site_opencli_block_written,
        "adapters": _regenerate_adapters(binding.site_manifest),
    }


def _derive_bound(
    binding: CloneBinding, max_profiles: int, max_steps: int, generated_from: str
) -> Derivation:
    derivation = derive_contract(
        site_id=binding.site_id,
        manifest_root=binding.manifest_root,
        manifest_data=binding.manifest_data,
        max_profiles=max_profiles,
        max_steps=max_steps,
    )
    # Repository-root-relative: the contract schema's relative_path $def forbids
    # `..`, so an interactions/-relative path could never reach materials/.
    derivation.contract["generated_from"] = generated_from
    derivation.inputs.append(binding.manifest_path)
    return derivation
