"""Load, initialize, and validate an offline-clone harness manifest."""

from __future__ import annotations

import io
import json
import os
import re
import stat
import warnings
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any
from urllib.parse import parse_qsl, unquote, urlsplit

import yaml
from jsonschema import Draft202012Validator, FormatChecker
from yaml.constructor import ConstructorError
from yaml.resolver import BaseResolver

from .backend_model import (
    BackendModelError,
    load_backend_model,
    validate_backend_scope_references,
)

MANIFEST_NAME = "clone.yaml"
MANIFEST_SCHEMA = "offline-clone-manifest-v2.schema.json"
LEGACY_MANIFEST_SCHEMA = "offline-clone-manifest.schema.json"
CURRENT_MANIFEST_SCHEMA_VERSION = "offline-clone.manifest.v2"
LEGACY_MANIFEST_SCHEMA_VERSION = "offline-clone.manifest.v1"
ASSET_SCHEMA = "offline-clone-asset-manifest.schema.json"
COVERAGE_SCHEMA = "offline-clone-coverage.schema.json"
PURPOSE_SCHEMA = "offline-clone-purpose.schema.json"
INVARIANTS_SCHEMA = "offline-clone-invariants.schema.json"
CHECKPOINTS_SCHEMA = "offline-clone-checkpoints.schema.json"
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
# Bounds on a frozen source screenshot the scope contracts point at. These
# outlived the acceptance-evidence vocabulary they were named for: a checkpoint
# still names a raster, and it still must not be unbounded.
MAX_FROZEN_SOURCE_RASTER_BYTES = 64 * 1024 * 1024
MAX_VISUAL_EVIDENCE_PIXELS = 16_777_216

_SENSITIVE_QUERY_KEYS = frozenset(
    {
        "accesskey",
        "accesstoken",
        "apikey",
        "auth",
        "authorization",
        "bearer",
        "code",
        "cookie",
        "credential",
        "clientsecret",
        "csrftoken",
        "idtoken",
        "jwt",
        "key",
        "keypairid",
        "passwd",
        "password",
        "privatekey",
        "pwd",
        "sas",
        "secret",
        "secretkey",
        "session",
        "sessionid",
        "sig",
        "signature",
        "token",
    }
)
_SENSITIVE_QUERY_SUFFIXES = (
    "accesstoken",
    "apikey",
    "authorization",
    "credential",
    "idtoken",
    "password",
    "privatekey",
    "secret",
    "secretkey",
    "securitytoken",
    "sessionid",
    "signature",
    "token",
)
_URL_CREDENTIAL_FINDINGS = frozenset(
    {
        "access_token",
        "api_key",
        "authorization",
        "bearer_token",
        "client_secret",
        "cookie",
        "credential_flag",
        "jwt",
        "low_entropy_secret_hash",
        "password",
        "passwd",
        "private_key",
        "provider_key",
        "pwd",
        "refresh_token",
        "secret",
        "session_id",
        "session_token",
        "smtp_password",
    }
)
_MALFORMED_PERCENT_ESCAPE = re.compile(r"%(?![0-9A-Fa-f]{2})")


class _UniqueKeySafeLoader(yaml.SafeLoader):
    """Safe YAML loader that refuses ambiguous duplicate mapping keys."""


def _construct_unique_yaml_mapping(
    loader: _UniqueKeySafeLoader, node: yaml.MappingNode, deep: bool = False
) -> dict[Any, Any]:
    loader.flatten_mapping(node)
    result: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in result
        except TypeError as exc:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "found an unhashable key",
                key_node.start_mark,
            ) from exc
        if duplicate:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueKeySafeLoader.add_constructor(
    BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_yaml_mapping
)


@dataclass(frozen=True)
class ValidationProblem:
    location: str
    message: str

    def __str__(self) -> str:
        return f"{self.location}: {self.message}"


class ManifestValidationError(ValueError):
    def __init__(self, problems: list[ValidationProblem]) -> None:
        self.problems = tuple(problems)
        detail = "\n".join(f"- {problem}" for problem in problems)
        super().__init__(f"offline clone manifest validation failed:\n{detail}")


@dataclass(frozen=True)
class LoadedManifest:
    path: Path
    root: Path
    data: dict[str, Any]
    is_legacy: bool = False

    def resolve(self, relative: str, *, must_exist: bool = False) -> Path:
        return resolve_inside(self.root, relative, must_exist=must_exist)

    @property
    def asset_manifest_path(self) -> Path:
        return self.resolve(self.data["paths"]["asset_manifest"], must_exist=True)

    @property
    def backend_model_path(self) -> Path:
        return self.resolve(self.data["paths"]["backend_model"], must_exist=True)

    @property
    def coverage_path(self) -> Path:
        return self.resolve(self.data["scope"]["coverage"], must_exist=True)

    @property
    def purpose_path(self) -> Path:
        return self.resolve(self.data["scope"]["purpose"], must_exist=True)

    @property
    def invariants_path(self) -> Path:
        return self.resolve(self.data["scope"]["invariants"], must_exist=True)

    @property
    def checkpoints_path(self) -> Path:
        return self.resolve(self.data["scope"]["checkpoints"], must_exist=True)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def validate_source_url(value: str) -> None:
    """Reject ambiguous source URLs and URLs that may persist credentials."""

    if value != value.strip():
        raise ValueError("source URL must not have leading or trailing whitespace")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError("source URL must not contain an ASCII control character")
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        username = parsed.username
        password = parsed.password
        _ = parsed.port
    except ValueError as exc:
        raise ValueError(f"source URL is invalid: {exc}") from exc
    if parsed.scheme not in {"http", "https"} or not hostname:
        raise ValueError("source URL must be an absolute HTTP(S) URL")
    if username is not None or password is not None:
        raise ValueError("source URL must not contain userinfo")
    if "#" in value:
        raise ValueError("source URL must not contain a fragment")
    def decoded_layers(raw: str) -> list[str]:
        layers: list[str] = []
        current = raw
        for _ in range(5):
            if _MALFORMED_PERCENT_ESCAPE.search(current):
                raise ValueError("source URL contains a malformed percent escape")
            try:
                decoded = unquote(current, errors="strict")
            except UnicodeDecodeError as exc:
                raise ValueError("source URL contains invalid percent-encoded UTF-8") from exc
            if any(ord(character) < 32 or ord(character) == 127 for character in decoded):
                raise ValueError("source URL contains a decoded control character")
            layers.append(decoded)
            if decoded == current:
                return layers
            current = decoded
        try:
            extra_decoded = unquote(current, errors="strict")
        except UnicodeDecodeError as exc:
            raise ValueError("source URL contains invalid percent-encoded UTF-8") from exc
        if extra_decoded != current:
            raise ValueError("source URL exceeds the supported percent-encoding depth")
        return layers

    decoded_values: list[str] = decoded_layers(parsed.path)
    for key, query_value in parse_qsl(
        parsed.query.replace(";", "&"), keep_blank_values=True
    ):
        for decoded_key in decoded_layers(key):
            normalized = re.sub(r"[^a-z0-9]", "", decoded_key.casefold())
            if normalized in _SENSITIVE_QUERY_KEYS or normalized.endswith(
                _SENSITIVE_QUERY_SUFFIXES
            ):
                raise ValueError(
                    f"source URL query key may contain credentials: {decoded_key!r}"
                )
        decoded_values.extend(decoded_layers(query_value))
    # Keys catch ordinary query credentials. Values and path components still
    # need scanning because redirect parameters and percent-encoding can hide
    # bearer/JWT/provider keys or assignments such as ``access_token=...``.
    # Filter to credential findings so benign prose containing "code" does not
    # become an over-broad URL rejection rule.
    from .secrets import sensitive_findings

    for decoded in decoded_values:
        findings = sorted(
            set(sensitive_findings(decoded)) & _URL_CREDENTIAL_FINDINGS
        )
        if findings:
            raise ValueError(
                "source URL path or query value may contain credentials: "
                + ", ".join(findings)
            )


def resolve_manifest_path(value: Path | str) -> Path:
    path = Path(value).resolve()
    return path / MANIFEST_NAME if path.is_dir() else path


def _schema_path(filename: str) -> Path:
    source_root = Path(__file__).resolve().parents[3]
    source_schema = source_root / "websitebench" / "schemas" / filename
    if source_schema.is_file():
        return source_schema
    bundled = Path(__file__).resolve().parents[1] / "viewer" / "_schemas" / filename
    if bundled.is_file():
        return bundled
    raise FileNotFoundError(f"offline clone schema is unavailable: {filename}")


def load_schema(filename: str) -> dict[str, Any]:
    value = json.loads(_schema_path(filename).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(value)
    return value


def _schema_problems(value: Any, filename: str, location: str) -> list[ValidationProblem]:
    validator = Draft202012Validator(
        load_schema(filename), format_checker=FormatChecker()
    )
    problems: list[ValidationProblem] = []
    for error in sorted(validator.iter_errors(value), key=lambda item: list(item.path)):
        suffix = ".".join(str(part) for part in error.absolute_path)
        problems.append(
            ValidationProblem(f"{location}.{suffix}" if suffix else location, error.message)
        )
    return problems


def resolve_inside(root: Path, relative: str, *, must_exist: bool = False) -> Path:
    raw = Path(relative)
    windows = PureWindowsPath(relative)
    posix = PurePosixPath(relative)
    if raw.is_absolute() or windows.is_absolute() or windows.drive or posix.is_absolute():
        raise ValueError("absolute paths are forbidden")
    if ".." in windows.parts or ".." in posix.parts:
        raise ValueError(f"parent traversal is forbidden: {relative}")
    resolved_root = root.resolve()
    resolved = (resolved_root / raw).resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise ValueError(f"path escapes the site directory: {relative}")
    if must_exist and not resolved.exists():
        raise ValueError(f"path does not exist: {relative}")
    return resolved


def _is_link_or_reparse(path: Path) -> bool:
    """Inspect one lexical path component without following redirects."""

    try:
        metadata = path.lstat()
    except (FileNotFoundError, NotADirectoryError):
        return False
    if stat.S_ISLNK(metadata.st_mode):
        return True
    attributes = getattr(metadata, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    if attributes & reparse_flag:
        return True
    return bool(hasattr(path, "is_junction") and path.is_junction())


def resolve_safe_regular_file(root: Path, relative: str) -> Path:
    """Resolve a contained regular file without accepting redirected components."""

    resolved = resolve_inside(root, relative, must_exist=True)
    lexical = root.resolve()
    for component in Path(relative).parts:
        lexical = lexical / component
        if _is_link_or_reparse(lexical):
            raise ValueError(
                "path crosses a symbolic link, junction, or reparse point: "
                f"{relative}"
            )
    try:
        metadata = resolved.lstat()
    except OSError as exc:
        raise ValueError(f"cannot inspect file: {relative}: {exc}") from exc
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError(f"path is not a regular file: {relative}")
    return resolved


def _read_mapping(path: Path, *, yaml_allowed: bool = False) -> dict[str, Any]:
    try:
        payload = path.read_bytes()
        value = (
            _strict_yaml_mapping(payload)
            if yaml_allowed
            else _strict_json_mapping(payload)
        )
    except (OSError, UnicodeDecodeError, ValueError, yaml.YAMLError) as exc:
        raise ValueError(str(exc)) from exc
    if not isinstance(value, dict):
        raise ValueError("document must contain an object")
    return value


def _strict_yaml_mapping(payload: bytes) -> dict[str, Any]:
    try:
        value = yaml.load(payload.decode("utf-8"), Loader=_UniqueKeySafeLoader)
    except (UnicodeDecodeError, yaml.YAMLError, ValueError) as exc:
        raise ValueError(str(exc)) from exc
    if not isinstance(value, dict):
        raise ValueError("document must contain an object")
    return value


def _strict_json_mapping(payload: bytes) -> dict[str, Any]:
    """Parse a JSON object while rejecting duplicate keys at every depth."""

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON object key: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(payload, object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(str(exc)) from exc
    if not isinstance(value, dict):
        raise ValueError("document must contain an object")
    return value


def _read_safe_regular_bytes(
    root: Path, relative: str, *, maximum_bytes: int
) -> tuple[Path, bytes]:
    """Read one bounded regular artifact through a no-follow descriptor."""

    path = resolve_safe_regular_file(root, relative)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ValueError(f"cannot open regular file: {relative}: {exc}") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError(f"path is not a regular file: {relative}")
        if getattr(metadata, "st_nlink", 1) != 1:
            raise ValueError(f"file must have exactly one hard link: {relative}")
        if metadata.st_size > maximum_bytes:
            raise ValueError(
                f"acceptance evidence exceeds {maximum_bytes} bytes"
            )
        chunks: list[bytes] = []
        remaining = maximum_bytes + 1
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        if len(payload) > maximum_bytes:
            raise ValueError(
                f"acceptance evidence exceeds {maximum_bytes} bytes"
            )
    finally:
        os.close(descriptor)
    return path, payload


def _validated_image_size(payload: bytes) -> tuple[int, int]:
    """Verify a raster without allowing compressed images to expand unboundedly."""

    try:
        from PIL import Image

        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(payload)) as image:
                width, height = image.size
                if (
                    width < 1
                    or height < 1
                    or width * height > MAX_VISUAL_EVIDENCE_PIXELS
                ):
                    raise ValueError(
                        "image dimensions exceed the visual evidence pixel budget"
                    )
                image.verify()
    except (OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError(f"invalid or unsafe image: {exc}") from exc
    return width, height



def load_asset_manifest(path: Path) -> dict[str, Any]:
    value = _read_mapping(path)
    problems = _schema_problems(value, ASSET_SCHEMA, "asset_manifest")
    ids: set[str] = set()
    source_paths: set[str] = set()
    runtime_paths: set[str] = set()
    for index, asset in enumerate(value.get("assets", [])):
        if not isinstance(asset, dict):
            continue
        for field, seen in (
            ("id", ids),
            ("source_path", source_paths),
            ("runtime_path", runtime_paths),
        ):
            item = asset.get(field)
            if isinstance(item, str) and item in seen:
                problems.append(
                    ValidationProblem(
                        f"asset_manifest.assets.{index}.{field}",
                        f"duplicate value: {item}",
                    )
                )
            elif isinstance(item, str):
                seen.add(item)
        source_url = asset.get("source_url")
        if isinstance(source_url, str):
            try:
                validate_source_url(source_url)
            except ValueError as exc:
                problems.append(
                    ValidationProblem(
                        f"asset_manifest.assets.{index}.source_url", str(exc)
                    )
                )
    if problems:
        raise ManifestValidationError(problems)
    return value


def load_coverage_ledger(path: Path) -> dict[str, Any]:
    """Load coverage dimensions and enforce the relations JSON Schema cannot."""

    value = _read_mapping(path)
    problems = _schema_problems(value, COVERAGE_SCHEMA, "coverage")
    status = value.get("status")
    dimensions = value.get("dimensions")
    if status == "frozen" and isinstance(dimensions, list) and not dimensions:
        problems.append(
            ValidationProblem(
                "coverage.dimensions",
                "a frozen coverage ledger must contain at least one dimension",
            )
        )
    if (
        status == "frozen"
        and isinstance(dimensions, list)
        and dimensions
        and not any(
            isinstance(dimension, dict) and bool(dimension.get("required_items"))
            for dimension in dimensions
        )
    ):
        problems.append(
            ValidationProblem(
                "coverage.dimensions",
                "a frozen coverage ledger must include at least one non-empty denominator",
            )
        )
    dimension_ids: set[str] = set()
    for index, dimension in enumerate(dimensions if isinstance(dimensions, list) else []):
        if not isinstance(dimension, dict):
            continue
        dimension_id = dimension.get("id")
        if isinstance(dimension_id, str) and dimension_id in dimension_ids:
            problems.append(
                ValidationProblem(
                    f"coverage.dimensions.{index}.id",
                    f"duplicate dimension id: {dimension_id}",
                )
            )
        elif isinstance(dimension_id, str):
            dimension_ids.add(dimension_id)

        item_sets: dict[str, set[str]] = {}
        for field in ("required_items", "satisfied_items"):
            items = dimension.get(field)
            if not isinstance(items, list):
                continue
            seen: set[str] = set()
            canonical_items: list[str] = []
            for item_index, item in enumerate(items):
                item_id = (
                    item
                    if isinstance(item, str)
                    else item.get("id")
                    if isinstance(item, dict)
                    else None
                )
                if isinstance(item_id, str) and item_id in seen:
                    problems.append(
                        ValidationProblem(
                            f"coverage.dimensions.{index}.{field}.{item_index}",
                            f"duplicate item id: {item_id}",
                        )
                    )
                elif isinstance(item_id, str):
                    seen.add(item_id)
                    canonical_items.append(item_id)
            if len(canonical_items) == len(items):
                dimension[field] = canonical_items
            item_sets[field] = seen

        required = item_sets.get("required_items")
        satisfied = item_sets.get("satisfied_items")
        if status == "frozen" and satisfied:
            problems.append(
                ValidationProblem(
                    f"coverage.dimensions.{index}.satisfied_items",
                    "a frozen source ledger must leave satisfaction empty; verification evidence owns numerators",
                )
            )
        if required == set() and not dimension.get("rationale"):
            problems.append(
                ValidationProblem(
                    f"coverage.dimensions.{index}.rationale",
                    "an empty denominator requires an explicit N/A rationale",
                )
            )
        if required is not None and satisfied is not None:
            for item in sorted(satisfied - required):
                problems.append(
                    ValidationProblem(
                        f"coverage.dimensions.{index}.satisfied_items",
                        f"satisfied item is not required: {item}",
                    )
                )
    if problems:
        raise ManifestValidationError(problems)
    return value


def load_purpose_contract(path: Path) -> dict[str, Any]:
    value = _read_mapping(path)
    problems = _schema_problems(value, PURPOSE_SCHEMA, "purpose")
    if value.get("status") == "frozen" and str(value.get("statement", "")).strip().casefold().startswith("todo"):
        problems.append(
            ValidationProblem(
                "purpose.statement", "a frozen purpose must replace the TODO placeholder"
            )
        )
    if problems:
        raise ManifestValidationError(problems)
    return value


def load_invariants_contract(path: Path) -> dict[str, Any]:
    value = _read_mapping(path)
    problems = _schema_problems(value, INVARIANTS_SCHEMA, "invariants")
    seen: set[str] = set()
    for index, invariant in enumerate(value.get("invariants", [])):
        if not isinstance(invariant, dict) or not isinstance(invariant.get("id"), str):
            continue
        invariant_id = invariant["id"]
        if invariant_id in seen:
            problems.append(
                ValidationProblem(
                    f"invariants.invariants.{index}.id",
                    f"duplicate invariant id: {invariant_id}",
                )
            )
        seen.add(invariant_id)
    if problems:
        raise ManifestValidationError(problems)
    return value


def load_journeys_contract(path: Path) -> dict[str, Any]:
    value = _read_mapping(path)
    problems: list[ValidationProblem] = []
    if value.get("schema_version") != "offline-clone.journeys.v1":
        problems.append(
            ValidationProblem("journeys.schema_version", "invalid schema_version")
        )
    journeys = value.get("journeys")
    if not isinstance(journeys, list):
        problems.append(ValidationProblem("journeys.journeys", "must be an array"))
        journeys = []
    seen: set[str] = set()
    for index, journey in enumerate(journeys):
        location = f"journeys.journeys.{index}"
        if not isinstance(journey, dict):
            problems.append(ValidationProblem(location, "must be an object"))
            continue
        journey_id = journey.get("id")
        if not isinstance(journey_id, str) or not re.fullmatch(
            r"[a-z0-9]+(?:[._:-][a-z0-9]+)*", journey_id
        ):
            problems.append(ValidationProblem(f"{location}.id", "invalid journey id"))
        elif journey_id in seen:
            problems.append(
                ValidationProblem(f"{location}.id", f"duplicate journey id: {journey_id}")
            )
        else:
            seen.add(journey_id)
        if journey.get("priority") not in {"p0", "p1", "p2"}:
            problems.append(
                ValidationProblem(f"{location}.priority", "must be p0, p1, or p2")
            )
        if journey.get("status") not in {"draft", "frozen"}:
            problems.append(
                ValidationProblem(f"{location}.status", "must be draft or frozen")
            )
        if not isinstance(journey.get("steps"), list) or not journey.get("steps"):
            problems.append(
                ValidationProblem(f"{location}.steps", "must contain at least one step")
            )
    if problems:
        raise ManifestValidationError(problems)
    return value


def load_checkpoints_contract(path: Path) -> dict[str, Any]:
    """Load the visual oracle whose thresholds and source rasters are frozen."""

    value = _read_mapping(path)
    problems = _schema_problems(value, CHECKPOINTS_SCHEMA, "checkpoints")
    seen: set[str] = set()
    for index, checkpoint in enumerate(value.get("checkpoints", [])):
        if not isinstance(checkpoint, dict):
            continue
        checkpoint_id = checkpoint.get("id")
        if isinstance(checkpoint_id, str) and checkpoint_id in seen:
            problems.append(
                ValidationProblem(
                    f"checkpoints.checkpoints.{index}.id",
                    f"duplicate checkpoint id: {checkpoint_id}",
                )
            )
        elif isinstance(checkpoint_id, str):
            seen.add(checkpoint_id)
        contract = checkpoint.get("visual_contract")
        if contract is None:
            continue
        if not isinstance(contract, dict):
            continue
        viewport = contract.get("viewport")
        region = contract.get("comparison_region")
        if not isinstance(viewport, dict) or not isinstance(region, dict):
            continue
        values = tuple(
            viewport.get(field) for field in ("width", "height")
        ) + tuple(region.get(field) for field in ("x", "y", "width", "height"))
        if not all(type(item) is int for item in values):
            continue  # JSON Schema reports the individual type errors.
        viewport_width, viewport_height, x, y, width, height = values
        if x + width > viewport_width or y + height > viewport_height:
            problems.append(
                ValidationProblem(
                    f"checkpoints.checkpoints.{index}.visual_contract.comparison_region",
                    "comparison region must be contained by the frozen viewport",
                )
            )
        if viewport_width * viewport_height > MAX_VISUAL_EVIDENCE_PIXELS:
            problems.append(
                ValidationProblem(
                    f"checkpoints.checkpoints.{index}.visual_contract.viewport",
                    "viewport exceeds the visual evidence pixel budget",
                )
            )
        source_crop = contract.get("source_crop")
        if source_crop is not None:
            if not isinstance(source_crop, dict):
                continue
            crop_values = tuple(
                source_crop.get(field) for field in ("x", "y", "width", "height")
            )
            if not all(type(item) is int for item in crop_values):
                continue  # JSON Schema reports the individual type errors.
            _, _, crop_width, crop_height = crop_values
            if (crop_width, crop_height) != (viewport_width, viewport_height):
                problems.append(
                    ValidationProblem(
                        f"checkpoints.checkpoints.{index}.visual_contract.source_crop",
                        "source crop dimensions must equal the frozen viewport",
                    )
                )
    if problems:
        raise ManifestValidationError(problems)
    return value







def require_frozen_coverage(manifest: LoadedManifest) -> dict[str, Any]:
    """Return the ledger or fail closed while any source contract is a draft."""

    ledger = load_coverage_ledger(manifest.coverage_path)
    purpose = load_purpose_contract(manifest.purpose_path)
    invariants = load_invariants_contract(manifest.invariants_path)
    checkpoints = load_checkpoints_contract(manifest.checkpoints_path)
    problems: list[ValidationProblem] = []
    if ledger["status"] != "frozen":
        problems.append(
            ValidationProblem(
                "coverage.status",
                "source acceptance requires status 'frozen'",
            )
        )
    if purpose["status"] != "frozen":
        problems.append(
            ValidationProblem(
                "purpose.status", "source acceptance requires status 'frozen'"
            )
        )
    if invariants["status"] != "frozen":
        problems.append(
            ValidationProblem(
                "invariants.status", "source acceptance requires status 'frozen'"
            )
        )
    if checkpoints["status"] != "frozen":
        problems.append(
            ValidationProblem(
                "checkpoints.status", "source acceptance requires status 'frozen'"
            )
        )
    if problems:
        raise ManifestValidationError(
            problems
        )
    return ledger


def load_manifest(
    value: Path | str,
    *,
    check_references: bool = True,
) -> LoadedManifest:
    """Load and validate one clone manifest.

    There is no tier any more: structural integrity, source-origin safety,
    backend-model structure and the frozen scope contracts are always checked.
    Runtime behavior belongs to the two diagnostic sections.
    """

    path = resolve_manifest_path(value)
    try:
        payload = path.read_bytes()
        if len(payload) > MAX_MANIFEST_BYTES:
            raise ValueError(f"manifest exceeds {MAX_MANIFEST_BYTES} bytes")
        data = _strict_yaml_mapping(payload)
    except (OSError, ValueError) as exc:
        raise ManifestValidationError([ValidationProblem(str(path), str(exc))]) from exc
    schema_version = data.get("schema_version")
    is_legacy = schema_version == LEGACY_MANIFEST_SCHEMA_VERSION
    schema = LEGACY_MANIFEST_SCHEMA if is_legacy else MANIFEST_SCHEMA
    problems = _schema_problems(data, schema, "manifest")
    if schema_version not in {
        CURRENT_MANIFEST_SCHEMA_VERSION,
        LEGACY_MANIFEST_SCHEMA_VERSION,
    }:
        problems.append(
            ValidationProblem(
                "manifest.schema_version",
                "expected offline-clone.manifest.v2",
            )
        )
    root = path.parent.resolve()

    source = data.get("source") if isinstance(data.get("source"), dict) else {}
    origins = source.get("origins") if isinstance(source.get("origins"), list) else []
    for index, origin in enumerate(origins):
        if not isinstance(origin, str):
            continue
        try:
            validate_source_url(origin)
        except ValueError as exc:
            problems.append(
                ValidationProblem(f"manifest.source.origins.{index}", str(exc))
            )

    paths = data.get("paths") if isinstance(data.get("paths"), dict) else {}
    scope = data.get("scope") if isinstance(data.get("scope"), dict) else {}
    references: list[tuple[str, str, str]] = []
    for name in (
        "purpose",
        "invariants",
        "routes",
        "journeys",
        "checkpoints",
        "claims",
        "coverage",
    ):
        if isinstance(scope.get(name), str):
            references.append((f"scope.{name}", scope[name], "file"))
    for name in ("candidate_root", "asset_manifest", "backend_model"):
        if isinstance(paths.get(name), str):
            references.append(
                (
                    f"paths.{name}",
                    paths[name],
                    "directory" if name == "candidate_root" else "file",
                )
            )

    for name in ("artifact_root",):
        if isinstance(paths.get(name), str):
            references.append((f"paths.{name}", paths[name], "future"))

    candidate_root: Path | None = None
    if isinstance(paths.get("candidate_root"), str):
        try:
            candidate_root = resolve_inside(root, paths["candidate_root"])
        except ValueError:
            pass
    candidate_exclude_paths: list[Path] = []
    candidate_excludes = paths.get("candidate_excludes")
    if candidate_root is not None and isinstance(candidate_excludes, list):
        for index, relative in enumerate(candidate_excludes):
            if not isinstance(relative, str):
                continue
            location = f"manifest.paths.candidate_excludes.{index}"
            lexical_exclusion = candidate_root
            redirected = False
            for component in Path(relative).parts:
                lexical_exclusion = lexical_exclusion / component
                if _is_link_or_reparse(lexical_exclusion):
                    problems.append(
                        ValidationProblem(
                            location,
                            "candidate exclusion crosses a symbolic link, junction, or reparse point",
                        )
                    )
                    redirected = True
                    break
            if redirected:
                continue
            try:
                excluded = resolve_inside(candidate_root, relative)
            except ValueError as exc:
                problems.append(ValidationProblem(location, str(exc)))
                continue
            if excluded == candidate_root:
                problems.append(
                    ValidationProblem(location, "candidate_root itself cannot be excluded")
                )
                continue
            if excluded.exists() and (
                not excluded.is_dir() or _is_link_or_reparse(excluded)
            ):
                problems.append(
                    ValidationProblem(
                        location,
                        "an existing candidate exclusion must be a real directory",
                    )
                )
                continue
            if any(
                excluded == existing
                or excluded in existing.parents
                or existing in excluded.parents
                for existing in candidate_exclude_paths
            ):
                problems.append(
                    ValidationProblem(
                        location,
                        "candidate exclusions must be distinct and non-overlapping",
                    )
                )
                continue
            candidate_exclude_paths.append(excluded)
    for location, relative, expected in references:
        try:
            resolved = resolve_inside(root, relative)
        except ValueError as exc:
            problems.append(ValidationProblem(f"manifest.{location}", str(exc)))
            continue
        if not check_references or expected == "future":
            continue
        if expected == "file" and not resolved.is_file():
            problems.append(ValidationProblem(f"manifest.{location}", "file is missing"))
        elif expected == "directory" and not resolved.is_dir():
            problems.append(ValidationProblem(f"manifest.{location}", "directory is missing"))
        elif expected in {"any", "baseline-optional"} and not resolved.exists():
            problems.append(ValidationProblem(f"manifest.{location}", "input is missing"))

    asset_path = paths.get("asset_manifest")
    if check_references and isinstance(asset_path, str):
        try:
            resolved_asset_path = resolve_inside(root, asset_path)
            if resolved_asset_path.is_file():
                load_asset_manifest(resolved_asset_path)
        except (ValueError, ManifestValidationError) as exc:
            if isinstance(exc, ManifestValidationError):
                problems.extend(exc.problems)
            else:
                problems.append(ValidationProblem("manifest.paths.asset_manifest", str(exc)))

    backend_model_path = paths.get("backend_model")
    if check_references and isinstance(backend_model_path, str):
        try:
            resolved_backend_model_path = resolve_inside(root, backend_model_path)
            if resolved_backend_model_path.is_file():
                load_backend_model(
                    resolved_backend_model_path,
                    expected_site_id=data.get("site_id")
                    if isinstance(data.get("site_id"), str)
                    else None,
                )
        except (ValueError, BackendModelError) as exc:
            if isinstance(exc, BackendModelError):
                problems.extend(
                    ValidationProblem("manifest.paths.backend_model", problem)
                    for problem in exc.problems
                )
            else:
                problems.append(
                    ValidationProblem("manifest.paths.backend_model", str(exc))
                )

    coverage_path = scope.get("coverage")
    if check_references and isinstance(coverage_path, str):
        try:
            resolved_coverage_path = resolve_inside(root, coverage_path)
            if resolved_coverage_path.is_file():
                load_coverage_ledger(resolved_coverage_path)
        except (ValueError, ManifestValidationError) as exc:
            if isinstance(exc, ManifestValidationError):
                problems.extend(exc.problems)
            else:
                problems.append(ValidationProblem("manifest.scope.coverage", str(exc)))

    for name, loader in (
        ("purpose", load_purpose_contract),
        ("invariants", load_invariants_contract),
        ("journeys", load_journeys_contract),
        ("checkpoints", load_checkpoints_contract),
    ):
        relative = scope.get(name)
        if not check_references or not isinstance(relative, str):
            continue
        try:
            resolved_contract = resolve_inside(root, relative)
            if resolved_contract.is_file():
                loader(resolved_contract)
        except (ValueError, ManifestValidationError) as exc:
            if isinstance(exc, ManifestValidationError):
                problems.extend(exc.problems)
            else:
                problems.append(
                    ValidationProblem(f"manifest.scope.{name}", str(exc))
                )

    if check_references and all(
        isinstance(scope.get(name), str)
        for name in ("purpose", "invariants", "journeys", "checkpoints", "coverage")
    ):
        try:
            purpose_contract = load_purpose_contract(
                resolve_inside(root, scope["purpose"], must_exist=True)
            )
            invariant_contract = load_invariants_contract(
                resolve_inside(root, scope["invariants"], must_exist=True)
            )
            journey_contract = load_journeys_contract(
                resolve_inside(root, scope["journeys"], must_exist=True)
            )
            checkpoint_contract = load_checkpoints_contract(
                resolve_inside(root, scope["checkpoints"], must_exist=True)
            )
            coverage_contract = load_coverage_ledger(
                resolve_inside(root, scope["coverage"], must_exist=True)
            )
        except (ValueError, ManifestValidationError):
            pass  # Individual contract validation above already reports details.
        else:
            # These cross-contract bindings say a frozen claim in one contract
            # is answered by a frozen claim in another. A site whose ledgers are
            # still draft has not made those claims yet, so checking them would
            # refuse to load a manifest for a site that is honestly mid-freeze
            # -- and a site that cannot load cannot be gated at all. This ran
            # strict-tier-only before; `frozen` is what strict actually meant.
            frozen = all(
                contract.get("status") == "frozen"
                for contract in (
                    journey_contract,
                    checkpoint_contract,
                    coverage_contract,
                )
            )
            if frozen:
                journeys_by_id = {
                    journey["id"]: journey for journey in journey_contract["journeys"]
                }
                try:
                    backend_model_contract = load_backend_model(
                        resolve_inside(root, paths["backend_model"], must_exist=True),
                        expected_site_id=(
                            data.get("site_id")
                            if isinstance(data.get("site_id"), str)
                            else None
                        ),
                    )
                except (ValueError, BackendModelError):
                    # The dedicated backend-model validation above already reports
                    # structural problems.  Cross-reference only a valid model.
                    backend_model_contract = None
                if not frozen:
                    backend_model_contract = None
                if backend_model_contract is not None:
                    invariant_ids = {
                        invariant["id"]
                        for invariant in invariant_contract["invariants"]
                        if isinstance(invariant, dict)
                        and isinstance(invariant.get("id"), str)
                    }
                    for problem in validate_backend_scope_references(
                        backend_model_contract,
                        journey_ids=set(journeys_by_id),
                        invariant_ids=invariant_ids,
                        # Draft models are authoring scaffolds; manifest loading must
                        # still support incremental scope authoring.
                        require_bindings=(
                            backend_model_contract.get("status") == "verified"
                        ),
                    ):
                        problems.append(
                            ValidationProblem("manifest.paths.backend_model", problem)
                        )
                    if backend_model_contract.get("status") == "verified":
                        for capability in backend_model_contract.get(
                            "capabilities", []
                        ):
                            if not isinstance(capability, dict):
                                continue
                            for journey_id in capability.get("journey_ids", []):
                                journey = journeys_by_id.get(journey_id)
                                if (
                                    isinstance(journey, dict)
                                    and journey.get("status") != "frozen"
                                ):
                                    problems.append(
                                        ValidationProblem(
                                            "manifest.paths.backend_model",
                                            "verified capability "
                                            f"{capability.get('id')!r} binds "
                                            f"non-frozen journey {journey_id!r}",
                                        )
                                    )
                        if invariant_contract.get("status") != "frozen":
                            problems.append(
                                ValidationProblem(
                                    "manifest.paths.backend_model",
                                    "verified backend model requires a frozen "
                                    "invariants contract",
                                )
                            )
                mainline_ids = set(purpose_contract["mainline_journey_ids"])
                for journey_id in sorted(mainline_ids if frozen else ()):
                    journey = journeys_by_id.get(journey_id)
                    if journey is None:
                        problems.append(
                            ValidationProblem(
                                "purpose.mainline_journey_ids",
                                f"unknown journey id: {journey_id}",
                            )
                        )
                    elif (
                        journey.get("priority") not in {"p0", "p1"}
                        or journey.get("status") != "frozen"
                    ):
                        problems.append(
                            ValidationProblem(
                                "purpose.mainline_journey_ids",
                                "mainline journey must be frozen p0/p1: "
                                f"{journey_id}",
                            )
                        )
                dimensions_by_id = {
                    dimension["id"]: dimension
                    for dimension in coverage_contract["dimensions"]
                }
                checkpoint_ids = {
                    checkpoint["id"]
                    for checkpoint in checkpoint_contract["checkpoints"]
                    if isinstance(checkpoint.get("visual_contract"), dict)
                }
                visual_required_items = {
                    item
                    for dimension in coverage_contract["dimensions"]
                    if "visual" in dimension["required_evidence_kinds"]
                    for item in dimension["required_items"]
                }
                missing_visual_contracts = sorted(visual_required_items - checkpoint_ids)
                if missing_visual_contracts:
                    problems.append(
                        ValidationProblem(
                            "checkpoints.checkpoints",
                            "visual coverage items require frozen checkpoint contracts: "
                            + ", ".join(missing_visual_contracts[:20]),
                        )
                    )
                for index, checkpoint in enumerate(checkpoint_contract["checkpoints"]):
                    contract = checkpoint.get("visual_contract")
                    if not isinstance(contract, dict):
                        continue
                    source_relative = contract["source_artifact_path"]
                    location = (
                        f"checkpoints.checkpoints.{index}.visual_contract.source_artifact_path"
                    )
                    try:
                        source_path, source_payload = _read_safe_regular_bytes(
                            root,
                            source_relative,
                            maximum_bytes=MAX_FROZEN_SOURCE_RASTER_BYTES,
                        )
                        source_size = _validated_image_size(source_payload)
                    except ValueError as exc:
                        problems.append(ValidationProblem(location, str(exc)))
                        continue
                    if candidate_root is not None and (
                        source_path == candidate_root or candidate_root in source_path.parents
                    ):
                        problems.append(
                            ValidationProblem(
                                location,
                                "frozen source screenshot must not come from paths.candidate_root",
                            )
                        )
                    expected_size = (
                        contract["viewport"]["width"],
                        contract["viewport"]["height"],
                    )
                    source_crop = contract.get("source_crop")
                    if isinstance(source_crop, dict):
                        crop = (
                            source_crop["x"],
                            source_crop["y"],
                            source_crop["width"],
                            source_crop["height"],
                        )
                        if (
                            crop[0] + crop[2] > source_size[0]
                            or crop[1] + crop[3] > source_size[1]
                            or (crop[2], crop[3]) != expected_size
                        ):
                            problems.append(
                                ValidationProblem(
                                    location,
                                    "frozen source_crop is outside the screenshot or does not match visual_contract.viewport",
                                )
                            )
                    elif source_size != expected_size:
                        problems.append(
                            ValidationProblem(
                                location,
                                "frozen source screenshot dimensions do not match visual_contract.viewport",
                            )
                        )
                for invariant in invariant_contract["invariants"]:
                    journey_ids = set(invariant["journey_ids"])
                    for journey_id in sorted(journey_ids):
                        if journey_id not in journeys_by_id:
                            problems.append(
                                ValidationProblem(
                                    f"invariants.{invariant['id']}.journey_ids",
                                    f"unknown journey id: {journey_id}",
                                )
                            )
                    if invariant["priority"] == "p0" and not (journey_ids & mainline_ids):
                        problems.append(
                            ValidationProblem(
                                f"invariants.{invariant['id']}.journey_ids",
                                "p0 invariant must bind at least one frozen mainline journey",
                            )
                        )
                    for dimension_id in invariant.get(
                        "coverage_dimension_ids", []
                    ):
                        dimension = dimensions_by_id.get(dimension_id)
                        if dimension is None:
                            problems.append(
                                ValidationProblem(
                                    f"invariants.{invariant['id']}.coverage_dimension_ids",
                                    f"unknown coverage dimension: {dimension_id}",
                                )
                            )
                        elif invariant["priority"] == "p0" and not dimension["required_items"]:
                            problems.append(
                                ValidationProblem(
                                    f"invariants.{invariant['id']}.coverage_dimension_ids",
                                    f"p0 invariant cannot bind an N/A dimension: {dimension_id}",
                                )
                            )

    if problems:
        raise ManifestValidationError(problems)
    return LoadedManifest(
        path,
        root,
        data,
        is_legacy=is_legacy,
    )



def initial_backend_model(site_id: str) -> dict[str, Any]:
    """Return the fail-closed common backend model for a newly initialized site."""

    def capability(
        capability_id: str,
        label: str,
        *,
        category: str,
        entities: list[dict[str, str]],
        kind: str,
        states: list[str],
        transitions: list[dict[str, str]],
        authorities: list[str],
        external_effect: str = "none",
    ) -> dict[str, Any]:
        return {
            "id": capability_id,
            "label": label,
            "priority": "p0",
            "category": category,
            "implementation_status": "planned",
            "entities": entities,
            "state_machine": {
                "kind": kind,
                "states": states,
                "transitions": transitions,
            },
            "server_authorities": authorities,
            "external_effect": external_effect,
            "journey_ids": [],
            "invariant_ids": [],
            "proofs": {
                "evidence": {},
                "planned": [
                    "valid",
                    "invalid",
                    "duplicate",
                    "stale",
                    "foreign-owner",
                    "unauthorized-role",
                    "restart",
                    "migration",
                    "concurrency",
                ],
                "not_applicable": [],
            },
        }

    return {
        "schema_version": "offline-clone.backend-model.v1",
        "site_id": site_id,
        "status": "draft",
        "profile": "offline-benchmark",
        "database": {
            "engine": "sqlite",
            "location_policy": "runtime-data-outside-candidate",
            "concurrency_model": "wal-transactional-single-writer",
            "migration_strategy": "versioned-forward-migrations",
            "deterministic_reset": True,
            "restart_persistence": True,
            "site_isolation": "one-database-per-site",
            "proofs": [
                {"obligation": obligation, "status": "planned", "evidence": []}
                for obligation in (
                    "data-location",
                    "schema-migration",
                    "deterministic-reset",
                    "restart-persistence",
                    "backup-restore",
                    "concurrency",
                )
            ],
        },
        "auth_semantics": {
            "account_database_scope": "site-isolated",
            "credential_storage": "salted-scrypt-hash",
            "session_storage": "opaque-cookie-digest-at-rest",
            "registration_account_creation": "after-email-verification",
            "verification_challenge_storage": "salted-hash",
            "password_reset_enumeration": "indistinguishable-public-response",
            "mail_default": "LOCAL_ONLY",
            "mail_statuses": [
                "LOCAL_ONLY",
                "SMTP_PENDING",
                "SMTP_SENT",
                "SMTP_FAILED",
            ],
            "smtp_activation": "explicit-complete-config-only",
            "smtp_delivery_ceiling": 3,
            "rejected_secret_journaling": "forbidden",
            "legacy_write_policy": "read-compatible-write-rejected",
        },
        "common_capabilities": {
            "account_registration": "account-registration",
            "account_sign_in": "account-sign-in",
            "session_lifecycle": "session-lifecycle",
            "password_recovery": "password-recovery",
            "email_delivery": "email-delivery",
        },
        "capabilities": [
            capability(
                "account-registration",
                "Verified local account registration",
                category="authentication",
                entities=[
                    {
                        "name": "pending-registration",
                        "identity": "opaque pending id bound to one browser session",
                        "owner_scope": "session",
                        "persistence": "durable",
                    },
                    {
                        "name": "local-account",
                        "identity": "site-local account id and unique normalized email",
                        "owner_scope": "account",
                        "persistence": "durable",
                    },
                ],
                kind="challenge-lifecycle",
                states=[
                    "collecting",
                    "pending-verification",
                    "verified",
                    "account-created",
                    "expired",
                    "locked",
                ],
                transitions=[
                    {
                        "from": "collecting",
                        "to": "pending-verification",
                        "trigger": "validated registration request",
                    },
                    {
                        "from": "pending-verification",
                        "to": "verified",
                        "trigger": "correct unexpired code within attempt budget",
                    },
                    {
                        "from": "verified",
                        "to": "account-created",
                        "trigger": "transactional account creation and session rotation",
                    },
                    {
                        "from": "pending-verification",
                        "to": "expired",
                        "trigger": "challenge expiry",
                    },
                    {
                        "from": "pending-verification",
                        "to": "locked",
                        "trigger": "verification attempt budget exhausted",
                    },
                ],
                authorities=[
                    "The server normalizes identity and hashes password and code.",
                    "An account is created only after successful verification.",
                    "Duplicate normalized email creation is rejected transactionally.",
                ],
            ),
            capability(
                "account-sign-in",
                "Password-based local account sign-in",
                category="authentication",
                entities=[
                    {
                        "name": "local-account",
                        "identity": "site-local account id and normalized email",
                        "owner_scope": "account",
                        "persistence": "durable",
                    }
                ],
                kind="entity-lifecycle",
                states=["signed-out", "identified", "authenticated", "rejected"],
                transitions=[
                    {
                        "from": "signed-out",
                        "to": "identified",
                        "trigger": "normalized email submitted",
                    },
                    {
                        "from": "identified",
                        "to": "authenticated",
                        "trigger": "constant-time password verification succeeds",
                    },
                    {
                        "from": "identified",
                        "to": "rejected",
                        "trigger": "credentials are invalid",
                    },
                ],
                authorities=[
                    "The server verifies salted password hashes.",
                    "The server rotates the authenticated session.",
                    "Client-selected fixture identity is not authentication.",
                ],
            ),
            capability(
                "session-lifecycle",
                "Anonymous and authenticated browser sessions",
                category="authentication",
                entities=[
                    {
                        "name": "browser-session",
                        "identity": "opaque cookie token with digest persisted at rest",
                        "owner_scope": "session",
                        "persistence": "durable",
                    }
                ],
                kind="session-lifecycle",
                states=["anonymous", "authenticated", "revoked", "expired"],
                transitions=[
                    {
                        "from": "anonymous",
                        "to": "authenticated",
                        "trigger": "successful sign-in or registration rotates session",
                    },
                    {
                        "from": "authenticated",
                        "to": "revoked",
                        "trigger": "sign-out or security reset",
                    },
                    {
                        "from": "anonymous",
                        "to": "expired",
                        "trigger": "session expiry",
                    },
                    {
                        "from": "authenticated",
                        "to": "expired",
                        "trigger": "session expiry",
                    },
                ],
                authorities=[
                    "Raw session tokens are never stored in the database.",
                    "Ownership is resolved from the server-side session record.",
                    "Sign-out revokes server-side authority before deleting the cookie.",
                ],
            ),
            capability(
                "password-recovery",
                "Enumeration-resistant local password recovery",
                category="authentication",
                entities=[
                    {
                        "name": "password-reset-challenge",
                        "identity": "opaque reset id bound to one browser session",
                        "owner_scope": "session",
                        "persistence": "durable",
                    },
                    {
                        "name": "local-account",
                        "identity": "nullable concealed account binding",
                        "owner_scope": "account",
                        "persistence": "durable",
                    },
                ],
                kind="challenge-lifecycle",
                states=["requested", "verified", "consumed", "expired", "locked"],
                transitions=[
                    {
                        "from": "requested",
                        "to": "verified",
                        "trigger": "correct unexpired code within attempt budget",
                    },
                    {
                        "from": "verified",
                        "to": "consumed",
                        "trigger": "password is replaced and sessions are revoked",
                    },
                    {
                        "from": "requested",
                        "to": "expired",
                        "trigger": "challenge expiry",
                    },
                    {
                        "from": "requested",
                        "to": "locked",
                        "trigger": "verification attempt budget exhausted",
                    },
                ],
                authorities=[
                    "Known and unknown emails receive indistinguishable public responses.",
                    "Only the server binds a reset flow to an account.",
                    "Password replacement revokes prior authenticated sessions.",
                ],
                external_effect="local-only",
            ),
            capability(
                "email-delivery",
                "Truthful local verification and recovery mail outbox",
                category="communication",
                entities=[
                    {
                        "name": "mail-outbox-entry",
                        "identity": "site-local outbox id and purpose-bound flow id",
                        "owner_scope": "system",
                        "persistence": "durable",
                    }
                ],
                kind="delivery-lifecycle",
                states=[
                    "local-only",
                    "smtp-pending",
                    "smtp-sent",
                    "smtp-failed",
                ],
                transitions=[
                    {
                        "from": "local-only",
                        "to": "smtp-pending",
                        "trigger": "operator enables complete explicit SMTP configuration",
                    },
                    {
                        "from": "smtp-pending",
                        "to": "smtp-sent",
                        "trigger": "SMTP transport confirms delivery handoff",
                    },
                    {
                        "from": "smtp-pending",
                        "to": "smtp-failed",
                        "trigger": "delivery attempt fails or ceiling is reached",
                    },
                    {
                        "from": "smtp-failed",
                        "to": "smtp-pending",
                        "trigger": "bounded idempotent retry below the delivery ceiling",
                    },
                ],
                authorities=[
                    "Offline mode records LOCAL_ONLY and never claims external delivery.",
                    "SMTP is disabled unless every required setting is present.",
                    "Claim, retry, and startup replay share one delivery ceiling.",
                ],
                external_effect="local-only",
            ),
        ],
    }


def initialize_site(
    site_dir: Path | str,
    *,
    site_id: str,
    display_name: str,
    source_url: str | Sequence[str],
    created_at: str | None = None,
) -> LoadedManifest:
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", site_id):
        raise ValueError("site_id must contain lowercase letters, digits, and single hyphens")
    source_urls = [source_url] if isinstance(source_url, str) else list(source_url)
    if not source_urls:
        raise ValueError("at least one source URL is required")
    for value in source_urls:
        validate_source_url(value)
    if len(source_urls) != len(set(source_urls)):
        raise ValueError("source URLs must be unique")
    if not display_name.strip():
        raise ValueError("display_name must not be empty")

    documents = {
        "backend/model.json": initial_backend_model(site_id),
        "scope/purpose.json": {
            "schema_version": "offline-clone.purpose.v1",
            "status": "draft",
            "purpose_id": "configure-purpose",
            "statement": (
                "TODO: freeze the source site's primary user purpose before "
                "source acceptance."
            ),
            "primary_actor_ids": [],
            "mainline_journey_ids": [],
            "out_of_scope": [],
        },
        "scope/invariants.json": {
            "schema_version": "offline-clone.invariants.v1",
            "status": "draft",
            "invariants": [],
        },
        "scope/routes.json": {"schema_version": "offline-clone.routes.v1", "routes": []},
        "scope/journeys.json": {
            "schema_version": "offline-clone.journeys.v1",
            "journeys": [],
        },
        "scope/checkpoints.json": {
            "schema_version": "offline-clone.checkpoints.v1",
            "status": "draft",
            "viewports": {},
            "checkpoints": [],
        },
        "scope/coverage.json": {
            "schema_version": "offline-clone.coverage.v1",
            "status": "draft",
            "dimensions": [],
        },
    }
    asset_manifest = {
        "schema_version": "offline-clone.assets.v1",
        "snapshot_id": f"{site_id}-pending",
        "created_at": created_at or utc_now(),
        "remote_runtime_policy": "forbidden",
        "closure_status": "pending",
        "no_assets_reason": None,
        "assets": [],
    }
    manifest = {
        "schema_version": CURRENT_MANIFEST_SCHEMA_VERSION,
        "site_id": site_id,
        "display_name": display_name,
        "state_model": "stateful",
        "source": {
            "origins": source_urls,
            "baseline": {
                "locale": "en-US",
                "currency": None,
                "delivery_region": None,
                "timezone": None,
                "auth_state": "anonymous",
                "tenant": None,
                "workspace": None,
                "role": None,
                "capabilities": [],
                "feature_flags": [],
                "user_agent": None,
                "viewport": None,
                "capture_id": None,
            },
            "capture_policy": {
                "safe_methods": ["GET", "HEAD"],
                "runtime_remote_requests": "forbidden",
            },
        },
        "scope": {
            "purpose": "scope/purpose.json",
            "invariants": "scope/invariants.json",
            "routes": "scope/routes.json",
            "journeys": "scope/journeys.json",
            "checkpoints": "scope/checkpoints.json",
            "claims": "scope/claims.jsonl",
            "coverage": "scope/coverage.json",
        },
        "paths": {
            "candidate_root": "clone",
            "candidate_excludes": [],
            "asset_manifest": "source-assets/manifest.json",
            "backend_model": "backend/model.json",
            "artifact_root": "artifacts/offline-clone",
        },
    }

    # Validate every generated contract before the first directory or file is created.
    generated_problems = [
        *_schema_problems(manifest, MANIFEST_SCHEMA, "manifest"),
        *_schema_problems(asset_manifest, ASSET_SCHEMA, "asset_manifest"),
        *_schema_problems(
            documents["scope/coverage.json"], COVERAGE_SCHEMA, "coverage"
        ),
    ]
    if generated_problems:
        raise ManifestValidationError(generated_problems)

    requested_root = Path(site_dir)
    is_junction = bool(
        hasattr(requested_root, "is_junction") and requested_root.is_junction()
    )
    if requested_root.is_symlink() or is_junction:
        raise ValueError("site directory must not be a symbolic link or junction")
    if requested_root.exists():
        if not requested_root.is_dir():
            raise FileExistsError(f"site directory is not a directory: {requested_root}")
        if next(requested_root.iterdir(), None) is not None:
            raise FileExistsError(
                f"refusing to initialize non-empty site directory: {requested_root}"
            )
    root = requested_root.resolve()
    directories = (
        "backend",
        "scope",
        "source-assets",
        "clone",
        "clone/frontend",
        "clone/backend",
        "clone/static",
        "clone/static/assets",
    )
    serialized_documents = {
        relative: json.dumps(document, indent=2, ensure_ascii=False) + "\n"
        for relative, document in documents.items()
    }
    serialized_documents.update(
        {
            "scope/claims.jsonl": "",
            "source-assets/manifest.json": json.dumps(
                asset_manifest, indent=2, ensure_ascii=False
            )
            + "\n",
            MANIFEST_NAME: yaml.safe_dump(
                manifest, sort_keys=False, allow_unicode=True
            ),
        }
    )

    # Resolve and collision-check every destination before performing any write.
    for relative in (*directories, *serialized_documents):
        destination = resolve_inside(root, relative)
        if destination.exists() or destination.is_symlink():
            raise FileExistsError(f"refusing to overwrite init destination: {destination}")

    root.mkdir(parents=True, exist_ok=True)
    for relative in directories:
        (root / relative).mkdir(exist_ok=False)
    for relative, text in serialized_documents.items():
        destination = root / relative
        with destination.open("x", encoding="utf-8", newline="") as stream:
            stream.write(text)

    manifest_path = root / MANIFEST_NAME
    return load_manifest(manifest_path)
