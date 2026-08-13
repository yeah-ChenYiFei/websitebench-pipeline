"""Strict, bounded input contract for ``scope/verify.json``.

The driver is executable configuration: it chooses candidate routes, browser
actions, session fixtures and the candidate boot command.  It therefore gets
stricter parsing than ordinary evidence JSON.  Historical drivers using one
``session`` block and list-valued state recipes remain valid; newly generated
drivers may additionally name accounts and bind a recipe to one account.
"""

from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath
from typing import Any

from jsonschema import Draft202012Validator


SCHEMA_VERSION = "offline-clone.verify-driver.v1"
MAX_DRIVER_BYTES = 1024 * 1024
_SAFE_ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]{0,95}$")
_DANGEROUS_ENV_NAMES = {
    "BASH_ENV",
    "ENV",
    "GCONV_PATH",
    "IFS",
    "LD_AUDIT",
    "LD_LIBRARY_PATH",
    "LD_PRELOAD",
    "NODE_OPTIONS",
    "PATH",
    "PERL5LIB",
    "PERL5OPT",
    "PYTHONHOME",
    "PYTHONINSPECT",
    "PYTHONPATH",
    "PYTHONSTARTUP",
    "WEBSITEBENCH_NODE_EXECUTABLE",
    "RUBYLIB",
    "RUBYOPT",
}


class VerifyDriverError(ValueError):
    """The live diagnostic driver is unsafe or structurally invalid."""


def _schema_path() -> Path:
    source_root = Path(__file__).resolve().parents[3]
    source = (
        source_root
        / "websitebench"
        / "schemas"
        / "offline-clone-verify-driver.schema.json"
    )
    if source.is_file():
        return source
    bundled = (
        Path(__file__).resolve().parents[1]
        / "viewer"
        / "_schemas"
        / "offline-clone-verify-driver.schema.json"
    )
    if bundled.is_file():
        return bundled
    raise VerifyDriverError("offline-clone verify-driver schema is unavailable")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, child in pairs:
        if key in value:
            raise VerifyDriverError(f"duplicate JSON key: {key!r}")
        value[key] = child
    return value


def _local_route(value: str) -> bool:
    if not value.startswith("/") or value.startswith("//"):
        return False
    if "\x00" in value or "\r" in value or "\n" in value or "\\" in value:
        return False
    path = value.split("?", 1)[0].split("#", 1)[0]
    return ".." not in PurePosixPath(path).parts


def _site_relative_path(value: str) -> bool:
    """Return whether a declared runtime path stays below the site root."""

    if not value or value.startswith("/"):
        return False
    if "\x00" in value or "\r" in value or "\n" in value or "\\" in value:
        return False
    parts = PurePosixPath(value).parts
    return bool(parts) and "." not in parts and ".." not in parts


def _recipes(value: dict[str, Any]) -> list[tuple[str, list[dict[str, Any]]]]:
    recipes: list[tuple[str, list[dict[str, Any]]]] = [
        ("prepare", value.get("prepare") or [])
    ]
    for recipe_id, recipe in (value.get("states") or {}).items():
        steps = recipe.get("steps") if isinstance(recipe, dict) else recipe
        recipes.append((f"states.{recipe_id}", steps or []))
    return recipes


def _semantic_problems(value: dict[str, Any], *, site_id: str | None) -> list[str]:
    problems: list[str] = []
    declared_site = value.get("site_id")
    if site_id is not None and declared_site not in {None, site_id}:
        problems.append(
            f"site_id {declared_site!r} does not match clone manifest {site_id!r}"
        )

    for section in ("routes",):
        for key, route in (value.get(section) or {}).items():
            if not _local_route(str(route)):
                problems.append(f"{section}.{key} must be a local absolute route")

    session = value.get("session") or {}
    post = session.get("post")
    if post is not None and not _local_route(str(post)):
        problems.append("session.post must be a local absolute route")

    accounts = session.get("accounts") or {}
    route_owner: dict[str, str] = {}
    for account, declaration in accounts.items():
        for route_id in declaration.get("routes") or []:
            previous = route_owner.setdefault(str(route_id), str(account))
            if previous != account:
                problems.append(
                    f"session route {route_id!r} is assigned to both {previous!r} "
                    f"and {account!r}"
                )

    known_sessions = set(accounts) if accounts else {"default"}
    for recipe_id, recipe in (value.get("states") or {}).items():
        if isinstance(recipe, dict) and recipe.get("session") not in {
            None,
            *known_sessions,
        }:
            problems.append(
                f"states.{recipe_id}.session names undeclared account "
                f"{recipe.get('session')!r}"
            )

    for recipe_id, steps in _recipes(value):
        for index, step in enumerate(steps):
            route = step.get("goto")
            if route is not None and not _local_route(str(route)):
                problems.append(
                    f"{recipe_id}[{index}].goto must be a local absolute route"
                )

    boot = value.get("boot") or {}
    argv = boot.get("argv") or []
    if argv and argv[0] != "{python}":
        problems.append("boot.argv must invoke the trusted {python} interpreter")
    cwd = boot.get("cwd")
    if cwd not in {None, ".", "clone"}:
        problems.append("boot.cwd must be '.' or 'clone'")
    for path in boot.get("read_paths") or []:
        if not _site_relative_path(str(path)):
            problems.append(
                f"boot.read_paths entry must stay within the site root: {path!r}"
            )
    for name in boot.get("env") or {}:
        upper = str(name).upper()
        if (
            not _SAFE_ENV_NAME.fullmatch(str(name))
            or upper in _DANGEROUS_ENV_NAMES
            or upper.startswith("DYLD_")
            or upper.startswith("LD_")
        ):
            problems.append(f"boot.env contains dangerous variable name {name!r}")
    token_env = session.get("token_env")
    if token_env is not None and (
        not _SAFE_ENV_NAME.fullmatch(str(token_env))
        or str(token_env).upper() in _DANGEROUS_ENV_NAMES
    ):
        problems.append("session.token_env is not a safe environment variable name")
    return problems


def load_verify_driver(path: Path, *, site_id: str | None = None) -> dict[str, Any]:
    """Parse and validate a bounded verify driver, rejecting duplicate keys."""

    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise VerifyDriverError(f"cannot read {path}: {exc}") from exc
    if len(raw) > MAX_DRIVER_BYTES:
        raise VerifyDriverError(
            f"{path}: verify driver exceeds {MAX_DRIVER_BYTES} bytes"
        )
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    except VerifyDriverError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VerifyDriverError(f"{path}: invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise VerifyDriverError(f"{path}: verify driver must contain an object")

    schema = json.loads(_schema_path().read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema).iter_errors(value),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    problems = [
        f"{'.'.join(str(part) for part in error.absolute_path) or '<root>'}: "
        f"{error.message}"
        for error in errors
    ]
    problems.extend(_semantic_problems(value, site_id=site_id))
    if problems:
        raise VerifyDriverError(
            f"{path}: invalid {SCHEMA_VERSION}:\n"
            + "\n".join(f"- {problem}" for problem in problems)
        )
    return value
