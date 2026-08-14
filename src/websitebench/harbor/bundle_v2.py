"""Static validation for materialized deterministic Harbor v2 bundles."""

from __future__ import annotations

import base64
import bz2
import gzip
import io
import json
import lzma
import re
import stat
import tarfile
import tomllib
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

import yaml
from PIL import Image

from .case_protocol import (
    CaseProtocolError,
    load_case_manifest,
    validate_case_references,
)

class BundleValidationError(ValueError):
    def __init__(self, problems: list[str]) -> None:
        self.problems = tuple(problems)
        super().__init__(
            "Harbor v2 bundle validation failed:\n"
            + "\n".join(f"- {problem}" for problem in problems)
        )


_MODEL_RUNTIME = re.compile(
    r"(?:api\.openai\.com|api\.anthropic\.com|generativelanguage\.googleapis\.com|"
    r"bedrock-runtime|aiplatform\.googleapis\.com|api\.groq\.com|api\.mistral\.ai|"
    r"api\.cohere\.com|openrouter\.ai|api-inference\.huggingface\.co|"
    r"OPENAI_API_KEY|ANTHROPIC_API_KEY|"
    r"AZURE_OPENAI_API_KEY|COHERE_API_KEY|GEMINI_API_KEY|GOOGLE_API_KEY|"
    r"HUGGINGFACE_TOKEN|MISTRAL_API_KEY|AWS_BEDROCK|AWS_ACCESS_KEY_ID|"
    r"AWS_SECRET_ACCESS_KEY|AWS_SESSION_TOKEN|GOOGLE_APPLICATION_CREDENTIALS|VERTEX_AI|"
    r"(?:^|\b)(?:from|import)\s+(?:openai|anthropic|boto3|cohere|litellm|"
    r"mistralai|ollama|sentence_transformers|transformers|vllm|"
    r"google\.(?:generativeai|genai))\b|"
    r"(?:^|[=<>~\s])(?:openai|anthropic|boto3|botocore|cohere|google-generativeai|"
    r"google-genai|google-cloud-aiplatform|groq|litellm|mistralai|"
    r"ollama|sentence-transformers|transformers|vllm)(?:[=<>~\s]|$)|"
    r"[\"'](?:openai|@anthropic-ai/sdk|@google/(?:generative-ai|genai)|"
    r"@azure/openai|@aws-sdk/client-bedrock-runtime|cohere-ai|mistralai|ollama|"
    r"@huggingface/inference)[\"']|"
    r"\b(?:gpt-[0-9]|claude-[0-9]|gemini-[0-9]|llama-[0-9]|command-r(?:-plus)?|"
    r"dall-e-[0-9]|text-embedding-[a-z0-9-]+)\b)",
    re.IGNORECASE | re.MULTILINE,
)
_MODEL_ARCHIVE_MEMBER = re.compile(
    r"(?:^|[/_.-])(?:openai|anthropic|boto3|botocore|cohere|google[_-]gen(?:erative)?ai|"
    r"google[_-]cloud[_-]aiplatform|groq|litellm|mistralai|ollama|"
    r"sentence[_-]transformers|transformers|vllm)(?:[/_.-]|$)",
    re.IGNORECASE,
)
_VERIFIER_OUTPUT = re.compile(
    r"(?:/run/verifier-final|/logs/verifier|scorecard\.json|reward\.txt|"
    r"task-results\.json|visual-results\.json|cicd-results\.json)"
)
_PERSISTED_SECRET = re.compile(
    r"(?:-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|"
    r"\b(?:OPENAI|ANTHROPIC|GEMINI|GOOGLE_API|COHERE|MISTRAL|AWS_SECRET_ACCESS|"
    r"AWS_ACCESS_KEY|HUGGINGFACE|VERTEX)[A-Z0-9_]*\s*[:=]\s*[\"']?"
    r"(?!\$\{|<|REDACTED|CHANGEME)[^\s\"']+)",
    re.IGNORECASE,
)
_CONFIG_KEYS = {
    "model",
    "model_name",
    "model_api",
    "prompt",
    "embedding",
    "embeddings",
    "completion",
    "chat_completion",
    "multimodal",
    "llm_judge",
}
_MODEL_SERVICE_HOST = re.compile(
    r"(?:^|[.-])(?:openai|anthropic|claude|gemini|generativelanguage|bedrock|"
    r"vertex|aiplatform|cohere|mistral|groq|openrouter|huggingface|ollama|vllm)"
    r"(?:[.-]|$)",
    re.IGNORECASE,
)


def _safe_relative(value: str) -> bool:
    posix, windows = PurePosixPath(value), PureWindowsPath(value)
    return not (
        posix.is_absolute()
        or windows.is_absolute()
        or windows.drive
        or ".." in posix.parts
        or ".." in windows.parts
    )


def _keys(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if isinstance(key, str):
                found.add(key.lower())
            found.update(_keys(child))
    elif isinstance(value, list):
        for child in value:
            found.update(_keys(child))
    return found


def _archive_contains_model_runtime(path: Path) -> bool:
    """Inspect vendored dependency archives without importing or extracting them."""

    try:
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as archive:
                return any(
                    _MODEL_ARCHIVE_MEMBER.search(info.filename)
                    for info in archive.infolist()[:100_000]
                )
        if tarfile.is_tarfile(path):
            with tarfile.open(path, mode="r:*") as archive:
                for index, member in enumerate(archive):
                    if index >= 100_000:
                        break
                    if _MODEL_ARCHIVE_MEMBER.search(member.name):
                        return True
    except (OSError, tarfile.TarError, zipfile.BadZipFile):
        return False
    return False


def _image_pixels(path: Path) -> bytes | None:
    """Decode RGB pixels so renamed/re-encoded reference rasters still match."""

    try:
        with Image.open(path) as source:
            if source.width * source.height > 50_000_000:
                return None
            image = source.convert("RGB")
            payload = (
                int(image.width).to_bytes(4, "big")
                + int(image.height).to_bytes(4, "big")
                + image.tobytes()
            )
    except (OSError, ValueError, Image.DecompressionBombError):
        return None
    return payload


def _image_bytes_pixels(payload: bytes) -> bytes | None:
    try:
        with Image.open(io.BytesIO(payload)) as source:
            if source.width * source.height > 50_000_000:
                return None
            image = source.convert("RGB")
            pixels = (
                int(image.width).to_bytes(4, "big")
                + int(image.height).to_bytes(4, "big")
                + image.tobytes()
            )
    except (OSError, ValueError, Image.DecompressionBombError):
        return None
    return pixels


def _archive_hidden_leaks(
    path: Path,
    *,
    sensitive_payloads: set[bytes],
    sensitive_pixels: set[bytes],
    encoded_sensitive_payloads: set[bytes],
) -> list[str]:
    """Inspect nested archive members without trusting names or compression."""

    try:
        with path.open("rb") as source:
            header = source.read(8)
        unsupported_archive = header.startswith(
            (b"7z\xbc\xaf\x27\x1c", b"Rar!", b"\x28\xb5\x2f\xfd")
        ) or path.suffix.lower() in {".7z", ".rar", ".zst", ".zstd"}
        if unsupported_archive:
            return ["unsupported-archive-format"]
        is_archive = (
            zipfile.is_zipfile(path)
            or tarfile.is_tarfile(path)
            or header.startswith((b"\x1f\x8b", b"BZh", b"\xfd7zXZ\x00"))
        )
    except OSError:
        return ["archive-unreadable"]
    if not is_archive:
        return []
    if path.stat().st_size > 128 * 1024 * 1024:
        return ["archive-too-large-to-verify"]
    budget = [512 * 1024 * 1024, 100_000]
    findings: set[str] = set()

    def inspect_member(name: str, payload: bytes, depth: int) -> None:
        budget[0] -= len(payload)
        budget[1] -= 1
        if budget[0] < 0 or budget[1] < 0:
            findings.add("archive-expansion-limit")
            return
        lower_name = name.replace("\\", "/").lower()
        if PurePosixPath(lower_name).name in {
            "task-suite.json",
            "visual-suite.json",
            "cicd-suite.json",
            "reference-observations.json",
        }:
            findings.add("hidden-artifact-name")
        if payload in sensitive_payloads:
            findings.add("hidden-artifact-content")
        pixels = _image_bytes_pixels(payload)
        if pixels is not None and pixels in sensitive_pixels:
            findings.add("reference-raster-pixels")
        if len(payload) <= 16 * 1024 * 1024:
            if any(encoded in payload for encoded in encoded_sensitive_payloads):
                findings.add("hidden-artifact-base64")
        if depth >= 3 or findings & {"archive-expansion-limit"}:
            return
        stream = io.BytesIO(payload)
        try:
            if zipfile.is_zipfile(stream):
                stream.seek(0)
                with zipfile.ZipFile(stream) as archive:
                    for info in archive.infolist():
                        if info.flag_bits & 0x1:
                            findings.add("encrypted-archive-member")
                            continue
                        if info.is_dir():
                            continue
                        if info.file_size > 64 * 1024 * 1024:
                            findings.add("archive-member-too-large-to-verify")
                            continue
                        inspect_member(
                            f"{name}!/{info.filename}", archive.read(info), depth + 1
                        )
                return
        except (OSError, RuntimeError, zipfile.BadZipFile):
            findings.add("archive-member-unreadable")
            return
        stream.seek(0)
        try:
            with tarfile.open(fileobj=stream, mode="r:*") as archive:
                recognized = True
                for member in archive:
                    if member.issym() or member.islnk():
                        findings.add("archive-link-member")
                        continue
                    if not member.isfile():
                        continue
                    if member.size > 64 * 1024 * 1024:
                        findings.add("archive-member-too-large-to-verify")
                        continue
                    extracted = archive.extractfile(member)
                    if extracted is None:
                        findings.add("archive-member-unreadable")
                        continue
                    inspect_member(
                        f"{name}!/{member.name}", extracted.read(), depth + 1
                    )
                return
        except (OSError, tarfile.TarError):
            recognized = False
        if payload[:2] == b"\x1f\x8b":
            try:
                with gzip.GzipFile(fileobj=io.BytesIO(payload)) as compressed:
                    expanded = compressed.read(64 * 1024 * 1024 + 1)
            except (OSError, EOFError):
                findings.add("archive-member-unreadable")
                return
            if len(expanded) > 64 * 1024 * 1024:
                findings.add("archive-member-too-large-to-verify")
                return
            inspect_member(f"{name}!/gzip-payload", expanded, depth + 1)
        elif payload.startswith(b"BZh"):
            try:
                expanded = bz2.BZ2Decompressor().decompress(
                    payload, max_length=64 * 1024 * 1024 + 1
                )
            except (OSError, EOFError, ValueError):
                findings.add("archive-member-unreadable")
                return
            if len(expanded) > 64 * 1024 * 1024:
                findings.add("archive-member-too-large-to-verify")
                return
            inspect_member(f"{name}!/bzip2-payload", expanded, depth + 1)
        elif payload.startswith(b"\xfd7zXZ\x00"):
            try:
                expanded = lzma.LZMADecompressor().decompress(
                    payload, max_length=64 * 1024 * 1024 + 1
                )
            except (lzma.LZMAError, EOFError):
                findings.add("archive-member-unreadable")
                return
            if len(expanded) > 64 * 1024 * 1024:
                findings.add("archive-member-too-large-to-verify")
                return
            inspect_member(f"{name}!/xz-payload", expanded, depth + 1)
        elif depth == 0 and not recognized:
            findings.add("archive-unreadable")

    try:
        inspect_member(path.name, path.read_bytes(), 0)
    except (OSError, RuntimeError, zipfile.BadZipFile, tarfile.TarError):
        findings.add("archive-unreadable")
    return sorted(findings)


def validate_bundle(
    root: Path | str, *, allow_legacy_deploy_v2: bool = False
) -> dict[str, Any]:
    bundle = Path(root).resolve()
    problems: list[str] = []
    try:
        manifest = json.loads(
            (bundle / "bundle-manifest.json").read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BundleValidationError(
            [f"bundle-manifest.json is unreadable: {exc}"]
        ) from exc
    if not isinstance(manifest, dict) or manifest.get("schema_version") != (
        "websitebench.harbor.bundle.v2"
    ):
        raise BundleValidationError(["bundle is not websitebench.harbor.bundle.v2"])
    active_case_protocol = (bundle / "tests/fixtures/case-manifest.json").is_file()
    if not active_case_protocol and not allow_legacy_deploy_v2:
        raise BundleValidationError(
            [
                "pre-compile Harbor v2 bundle validation requires "
                "allow_legacy_deploy_v2=True (CLI: --legacy-deploy-v2)"
            ]
        )
    if active_case_protocol:
        try:
            case_manifest, case_summary = load_case_manifest(
                bundle / "tests/fixtures/case-manifest.json",
                allow_draft=False,
                allow_sealed=True,
            )
            if case_summary.status != "sealed":
                problems.append("bundle case manifest must have bundle-only sealed status")
            task_suite = json.loads(
                (bundle / "tests/fixtures/task-suite.json").read_text(
                    encoding="utf-8"
                )
            )
            visual_suite = json.loads(
                (bundle / "tests/fixtures/visual-suite.json").read_text(
                    encoding="utf-8"
                )
            )
            cicd_suite = json.loads(
                (bundle / "tests/fixtures/cicd-suite.json").read_text(
                    encoding="utf-8"
                )
            )
            validate_case_references(
                case_manifest,
                task_suite=task_suite,
                visual_suite=visual_suite,
                cicd_suite=cicd_suite,
            )
            platform_cases = sorted(
                str(check.get("id"))
                for check in cicd_suite.get("checks", [])
                if isinstance(check, dict) and check.get("kind") == "platform"
            )
            if platform_cases:
                problems.append(
                    "trusted platform checks cannot occupy active site cases: "
                    f"{platform_cases}"
                )
        except (CaseProtocolError, OSError, UnicodeError, json.JSONDecodeError) as exc:
            problems.append(f"bundle case protocol is invalid: {exc}")
    judge = manifest.get("judge")
    if (
        not isinstance(judge, dict)
        or judge.get("kind") != "deterministic"
        or judge.get("model_runtime") is not False
    ):
        problems.append("bundle judge declaration is not deterministic/model-free")

    entries = manifest.get("files")
    if not isinstance(entries, list):
        problems.append("bundle manifest files must be an array")
        entries = []
    declared: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            problems.append("bundle manifest contains malformed file entry")
            continue
        relative = entry["path"]
        if relative in declared:
            problems.append(f"bundle manifest repeats path: {relative}")
            continue
        declared[relative] = entry
        if not _safe_relative(relative):
            problems.append(f"bundle manifest path escapes root: {relative}")
            continue
        path = bundle / relative
        try:
            metadata = path.lstat()
        except OSError as exc:
            problems.append(f"declared file is unavailable: {relative}:{exc}")
            continue
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            problems.append(
                f"declared file is not an independent regular file: {relative}"
            )
            continue
        if entry.get("bytes") != metadata.st_size:
            problems.append(f"declared file size differs: {relative}")

    actual = {
        path.relative_to(bundle).as_posix()
        for path in bundle.rglob("*")
        if path.is_file() and path.name != "bundle-manifest.json"
    }
    if actual != set(declared):
        problems.append(
            "bundle exact file set mismatch: "
            f"missing={sorted(set(declared) - actual)}:extra={sorted(actual - set(declared))}"
        )

    required = {
        "environment/Dockerfile",
        "environment/docker-compose.yaml",
        "tests/Dockerfile",
        "tests/test.sh",
        "tests/run_v2.py",
        "tests/websitebench/harbor/sandbox_v2.py",
        "tests/evaluation-contract.json",
        "tests/fixtures/task-suite.json",
        "tests/fixtures/visual-suite.json",
        "tests/fixtures/cicd-suite.json",
        "tests/fixtures/reference-observations.json",
        "tests/judge-dependencies.json",
        "tests/network-policy.json",
        "tests/calibration-contract.json",
        "task.toml",
    }
    if active_case_protocol:
        required.update(
            {
                "tests/fixtures/case-manifest.json",
                "tests/websitebench/harbor/browser_use_adapter.py",
                "tests/websitebench/harbor/case_protocol.py",
                "tests/websitebench/harbor/compiler_v2.py",
                "tests/websitebench/harbor/executors_v2.py",
                "tests/websitebench/harbor/formal_v2.py",
                "tests/websitebench/harbor/finalizer_v2.py",
                "tests/websitebench/viewer/_schemas/harbor-case-manifest.schema.json",
                "tests/websitebench/viewer/_schemas/harbor-case-result.schema.json",
                "tests/websitebench/viewer/_schemas/harbor-eval-v2.schema.json",
                "tests/websitebench/viewer/_schemas/harbor-receipt.schema.json",
            }
        )
    absent = sorted(required - set(declared))
    if absent:
        problems.append(f"bundle is missing required v2 files: {absent}")

    seed = bundle / "environment/seed"
    for forbidden in (
        "case-manifest.json",
        "task-suite.json",
        "visual-suite.json",
        "cicd-suite.json",
        "reference-observations.json",
    ):
        if any(path.name == forbidden for path in seed.rglob("*")):
            problems.append(
                f"hidden suite/reference observations leaked into Agent image: {forbidden}"
            )
    if any(path.suffix.lower() == ".png" for path in seed.rglob("*")):
        # Public starter PNGs are valid, so only paths with reference labels
        # are forbidden here.
        for path in seed.rglob("*.png"):
            relative = path.relative_to(seed).as_posix().lower()
            if "reference" in relative:
                problems.append(f"reference raster leaked into Agent image: {relative}")

    text_extensions = {
        ".cfg",
        ".ini",
        ".js",
        ".json",
        ".lock",
        ".mjs",
        ".py",
        ".sh",
        ".toml",
        ".ts",
        ".txt",
        ".yaml",
        ".yml",
    }
    for path in (bundle / "tests").rglob("*"):
        relative_path = path.relative_to(bundle / "tests").as_posix()
        if _MODEL_ARCHIVE_MEMBER.search(relative_path):
            problems.append(
                f"model runtime package path found in verifier: tests/{relative_path}"
            )
        if path.is_file() and _archive_contains_model_runtime(path):
            problems.append(
                "model runtime package found in verifier archive: "
                f"{path.relative_to(bundle).as_posix()}"
            )
        if (
            not path.is_file()
            or path.suffix.lower() not in text_extensions
            and path.name.lower() != "dockerfile"
        ):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeError:
            continue
        relative = path.relative_to(bundle).as_posix()
        if _MODEL_RUNTIME.search(text):
            problems.append(
                f"model runtime/service/credential found in verifier: {relative}"
            )
        payload: Any = None
        if path.suffix.lower() == ".json":
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                payload = None
        elif path.suffix.lower() in {".yaml", ".yml"}:
            try:
                payload = yaml.safe_load(text)
            except yaml.YAMLError:
                payload = None
        elif path.suffix.lower() == ".toml":
            try:
                payload = tomllib.loads(text)
            except tomllib.TOMLDecodeError:
                payload = None
        forbidden_keys = sorted(_keys(payload) & _CONFIG_KEYS)
        if forbidden_keys:
            problems.append(
                f"model/Judge config keys found in verifier {relative}: {forbidden_keys}"
            )
        if path.suffix.lower() in {".py", ".js", ".mjs", ".ts", ".sh"}:
            configured = sorted(
                key
                for key in _CONFIG_KEYS
                if re.search(rf"(?i)\b{re.escape(key)}\b\s*[:=]", text)
            )
            if configured:
                problems.append(
                    f"model/Judge configuration assignments found in verifier "
                    f"{relative}: {configured}"
                )

    for path in seed.rglob("*"):
        if not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeError:
            continue
        if _VERIFIER_OUTPUT.search(text):
            problems.append(
                "candidate-visible file references verifier result directory/artifact: "
                f"{path.relative_to(seed)}"
            )
        if _PERSISTED_SECRET.search(text):
            problems.append(
                f"candidate-visible file contains persisted credential material: "
                f"{path.relative_to(seed)}"
            )

    sensitive_files = {
        bundle / "tests/fixtures/case-manifest.json",
        bundle / "tests/fixtures/task-suite.json",
        bundle / "tests/fixtures/visual-suite.json",
        bundle / "tests/fixtures/cicd-suite.json",
        bundle / "tests/fixtures/reference-observations.json",
    }
    observations: dict[str, Any] = {}
    try:
        observations = json.loads(
            (bundle / "tests/fixtures/reference-observations.json").read_text(
                encoding="utf-8"
            )
        )
        for fact in observations.get("visual_checkpoints", []):
            if isinstance(fact, dict):
                image_name = fact.get("reference_image")
                if isinstance(image_name, str) and _safe_relative(image_name):
                    sensitive_files.add(bundle / "tests/fixtures" / image_name)
    except (OSError, UnicodeError, json.JSONDecodeError):
        pass
    sensitive_payloads = {
        path.read_bytes() for path in sensitive_files if path.is_file()
    }
    sensitive_pixels = {
        pixels
        for path in sensitive_files
        if path.is_file() and (pixels := _image_pixels(path)) is not None
    }
    encoded_sensitive_payloads = {
        base64.b64encode(path.read_bytes())
        for path in sensitive_files
        if path.is_file() and path.stat().st_size <= 6 * 1024 * 1024
    }
    for path in seed.rglob("*"):
        if not path.is_file():
            continue
        payload = path.read_bytes()
        relative = path.relative_to(seed).as_posix()
        if payload in sensitive_payloads:
            problems.append(
                "hidden verifier artifact leaked into Agent image by exact content: "
                f"{relative}"
            )
        pixels = _image_pixels(path)
        if pixels is not None and pixels in sensitive_pixels:
            problems.append(
                "reference raster leaked into Agent image by decoded pixels: "
                f"{relative}"
            )
        if path.stat().st_size <= 8 * 1024 * 1024:
            if any(encoded in payload for encoded in encoded_sensitive_payloads):
                problems.append(
                    "hidden verifier artifact leaked into Agent image as base64: "
                    f"{relative}"
                )
        archive_findings = _archive_hidden_leaks(
            path,
            sensitive_payloads=sensitive_payloads,
            sensitive_pixels=sensitive_pixels,
            encoded_sensitive_payloads=encoded_sensitive_payloads,
        )
        for finding in archive_findings:
            problems.append(
                "candidate-visible archive is unsafe or unverifiable: "
                f"{relative}:{finding}"
            )

    try:
        evaluation_contract = json.loads(
            (bundle / "tests/evaluation-contract.json").read_text(encoding="utf-8")
        )
        reference_environment = observations["render_environment"]
        browser_contract = evaluation_contract["browser"]
        if (
            evaluation_contract.get("workers") != 4
            or evaluation_contract.get("reference_render_environment")
            != reference_environment
            or browser_contract.get("playwright_version") != "1.61.0"
            or browser_contract.get("font_profile") != "websitebench-linux-fonts-v1"
        ):
            problems.append(
                "evaluation contract differs from the captured four-worker render environment"
            )
        if active_case_protocol and (
            evaluation_contract.get("deployment_abi")
            != "websitebench.harbor.compile-executable.v1"
            or evaluation_contract.get("logical_shards") != 8
            or evaluation_contract.get("formal_browsers")
            != ["playwright", "browser-use"]
            or evaluation_contract.get("browser_use", {}).get("version") != "0.12.6"
            or evaluation_contract.get("paths", {}).get("case_manifest")
            != "/tests/fixtures/case-manifest.json"
        ):
            problems.append("evaluation contract differs from the active 200-case ABI")
    except (OSError, KeyError, TypeError, json.JSONDecodeError):
        problems.append("evaluation contract/reference render environment is unreadable")

    try:
        network = json.loads(
            (bundle / "tests/network-policy.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        network = {}
    if (
        network.get("default") != "deny"
        or network.get("public_internet") is not False
        or network.get("model_services") is not False
    ):
        problems.append("verifier network policy is not deny-by-default/model-closed")
    expected_network_keys = {
        "schema_version",
        "default",
        "loopback",
        "public_internet",
        "model_services",
        "mailbox_external_allowlist",
    }
    if set(network) != expected_network_keys or network.get("loopback") is not True:
        problems.append(
            "verifier network policy contains an undeclared sidecar/capability"
        )
    allowlist = network.get("mailbox_external_allowlist", [])
    if isinstance(allowlist, list) and any(
        isinstance(host, str) and _MODEL_SERVICE_HOST.search(host) for host in allowlist
    ):
        problems.append("verifier mailbox allowlist contains a model service host")

    try:
        dependencies = json.loads(
            (bundle / "tests/judge-dependencies.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        dependencies = {}
    expected_runtime = [
        "python==3.12.11",
        "attrs==26.1.0",
        "greenlet==3.5.4",
        "imageio==2.37.4",
        "iniconfig==2.3.0",
        "jsonschema==4.26.0",
        "jsonschema-specifications==2025.9.1",
        "lazy-loader==0.5",
        "networkx==3.6.1",
        "numpy==2.5.1",
        "packaging==26.2",
        "pillow==12.3.0",
        "playwright==1.61.0",
        "pluggy==1.6.0",
        "pyee==13.0.1",
        "pygments==2.20.0",
        "pytest==9.1.1",
        "referencing==0.37.0",
        "rpds-py==2026.6.3",
        "scikit-image==0.26.0",
        "scipy==1.18.0",
        "tifffile==2026.7.14",
        "typing-extensions==4.16.0",
    ]
    if (
        dependencies.get("runtime") != expected_runtime
        or dependencies.get("model_sdks") != []
        or dependencies.get("model_credentials") != []
    ):
        problems.append("Judge dependency contract is not the fixed model-free set")
    try:
        dockerfile = (bundle / "tests/Dockerfile").read_text(encoding="utf-8")
        installed = {
            match.group(1).lower().replace("_", "-")
            for match in re.finditer(
                r"(?m)^\s+([a-zA-Z0-9_.-]+==[^\s\\]+)\s*\\?$", dockerfile
            )
        }
        installed.discard("browser-use==0.12.6")
        declared = {value.lower().replace("_", "-") for value in expected_runtime[1:]}
        if (
            not dockerfile.startswith("FROM python:3.12.11-slim-bookworm\n")
            or installed != declared
            or "playwright install --with-deps chromium" not in dockerfile
        ):
            problems.append(
                "Judge Dockerfile differs from the fixed browser/dependency closure"
            )
        if active_case_protocol and (
            "python -m venv /opt/websitebench/browser-use-0.12.6" not in dockerfile
            or "browser-use==0.12.6" not in dockerfile
        ):
            problems.append("Browser Use 0.12.6 is not confined to its isolated venv")
    except (OSError, UnicodeError):
        problems.append("Judge Dockerfile is unreadable")

    try:
        task = tomllib.loads((bundle / "task.toml").read_text(encoding="utf-8"))
        verifier_network = task["verifier"]["environment"]
        allowlist = network.get("mailbox_external_allowlist", [])
        if allowlist:
            network_valid = (
                verifier_network.get("network_mode") == "allowlist"
                and verifier_network.get("allowed_hosts") == allowlist
            )
        else:
            network_valid = verifier_network.get("network_mode") == "no-network"
        if not network_valid:
            problems.append("task verifier network differs from sealed network policy")
    except (OSError, UnicodeError, tomllib.TOMLDecodeError, KeyError, TypeError):
        problems.append("task verifier network configuration is unreadable")

    if problems:
        raise BundleValidationError(problems)
    return {
        "schema_version": "websitebench.harbor.bundle-validation.v2",
        "status": "valid",
        "instance_id": manifest.get("instance_id"),
        "site_id": manifest.get("site_id"),
        "files": len(declared),
        "model_runtime": False,
        "reward_source": (
            "weighted_t2_journey" if active_case_protocol else "task_completion"
        ),
    }
