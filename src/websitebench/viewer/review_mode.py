"""Revision-controlled diagnostic review sessions for Clone Atlas."""

from __future__ import annotations

import json
import os
import secrets
import tempfile
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from websitebench.offline_clone.secrets import sensitive_findings

from .item_keys import require_canonical_item_key
from .schema import validation_errors

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback
    fcntl = None


SESSION_SCHEMA = "websitebench.viewer-review-session.v1"
EXPORT_SCHEMA = "websitebench.viewer-review-session-export.v1"
AUTHORITY = "diagnostic-review-feedback-only"
DISPOSITIONED_STATUSES = {"resolved", "known_difference", "dismissed"}


class ReviewModeError(ValueError):
    """Raised when a review session or finding is invalid."""


class ReviewModeConflict(ReviewModeError):
    def __init__(self, item_key: str, expected: int, current: int) -> None:
        self.item_key = item_key
        self.expected = expected
        self.current = current
        super().__init__(
            f"review session revision conflict for {item_key}: "
            f"expected {expected}, current {current}"
        )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _session_id(item_key: str) -> str:
    return f"review-{item_key}"


def empty_review_session(item_key: str) -> dict[str, Any]:
    require_canonical_item_key(item_key)
    return {
        "schema_version": SESSION_SCHEMA,
        "session_id": _session_id(item_key),
        "item_key": item_key,
        "revision": 0,
        "findings": [],
        "created_at": None,
        "updated_at": None,
        "authority": AUTHORITY,
    }


def _optional_text(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return value


def _text(value: Any) -> Any:
    return value.strip() if isinstance(value, str) else value


def _finding_text_values(finding: dict[str, Any]) -> Iterator[str]:
    for field in ("observation", "expected"):
        value = finding.get(field)
        if isinstance(value, str):
            yield value
    target = finding.get("target")
    if isinstance(target, dict):
        for value in target.values():
            if isinstance(value, str):
                yield value
    for value in finding.get("evidence_refs", []):
        if isinstance(value, str):
            yield value
    resolution = finding.get("resolution")
    if isinstance(resolution, dict):
        summary = resolution.get("summary")
        if isinstance(summary, str):
            yield summary
        for value in resolution.get("evidence_refs", []):
            if isinstance(value, str):
                yield value


def _reject_sensitive_content(finding: dict[str, Any]) -> None:
    findings = sorted(
        {
            match
            for value in _finding_text_values(finding)
            for match in sensitive_findings(value)
        }
    )
    if findings:
        raise ReviewModeError(
            "review finding contains sensitive content: " + ", ".join(findings)
        )


def _require_disposition_summary(finding: dict[str, Any]) -> None:
    if finding.get("status") not in DISPOSITIONED_STATUSES:
        return
    resolution = finding.get("resolution", {})
    summary = resolution.get("summary") if isinstance(resolution, dict) else None
    if not isinstance(summary, str) or not summary.strip():
        raise ReviewModeError(
            f"{finding['status']} findings require a resolution summary"
        )


def _new_finding(payload: dict[str, Any], *, reviewer: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ReviewModeError("finding must be an object")
    allowed = {
        "status",
        "severity",
        "category",
        "target",
        "observation",
        "expected",
        "evidence_refs",
        "resolution",
    }
    unknown = sorted(set(payload).difference(allowed))
    if unknown:
        raise ReviewModeError("unsupported finding fields: " + ", ".join(unknown))
    target = payload.get("target", {})
    if not isinstance(target, dict):
        raise ReviewModeError("finding target must be an object")
    resolution = payload.get("resolution", {})
    if not isinstance(resolution, dict):
        raise ReviewModeError("finding resolution must be an object")
    now = _now()
    finding = {
        "finding_id": f"finding-{secrets.token_hex(8)}",
        "reviewer": reviewer,
        "status": payload.get("status", "open"),
        "severity": payload.get("severity", "p1"),
        "category": payload.get("category", "visual"),
        "target": {
            "checkpoint": _optional_text(target.get("checkpoint")),
            "viewport": _optional_text(target.get("viewport")),
            "route": _optional_text(target.get("route")),
            "role": _optional_text(target.get("role")),
            "state": _optional_text(target.get("state")),
        },
        "observation": _text(payload.get("observation", "")),
        "expected": _text(payload.get("expected", "")),
        "evidence_refs": payload.get("evidence_refs", []),
        "resolution": {
            "summary": _text(resolution.get("summary", "")),
            "evidence_refs": resolution.get("evidence_refs", []),
        },
        "created_at": now,
        "updated_at": now,
    }
    _require_disposition_summary(finding)
    _reject_sensitive_content(finding)
    return finding


def _updated_finding(existing: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(patch, dict):
        raise ReviewModeError("finding patch must be an object")
    allowed = {
        "status",
        "severity",
        "category",
        "target",
        "observation",
        "expected",
        "evidence_refs",
        "resolution",
    }
    unknown = sorted(set(patch).difference(allowed))
    if unknown:
        raise ReviewModeError("unsupported finding patch fields: " + ", ".join(unknown))
    value = json.loads(json.dumps(existing))
    for field in ("status", "severity", "category", "evidence_refs"):
        if field in patch:
            value[field] = patch[field]
    for field in ("observation", "expected"):
        if field in patch:
            value[field] = _text(patch[field])
    if "target" in patch:
        target = patch["target"]
        if not isinstance(target, dict):
            raise ReviewModeError("finding target must be an object")
        value["target"] = {
            field: _optional_text(target.get(field, value["target"].get(field)))
            for field in ("checkpoint", "viewport", "route", "role", "state")
        }
    if "resolution" in patch:
        resolution = patch["resolution"]
        if not isinstance(resolution, dict):
            raise ReviewModeError("finding resolution must be an object")
        value["resolution"] = {
            "summary": _text(
                resolution.get("summary", value["resolution"].get("summary", ""))
            ),
            "evidence_refs": resolution.get(
                "evidence_refs", value["resolution"].get("evidence_refs", [])
            ),
        }
    value["updated_at"] = _now()
    _require_disposition_summary(value)
    _reject_sensitive_content(value)
    return value


class ReviewSessionStore:
    """Atomic, optimistic-concurrency storage keyed by item."""

    def __init__(self, root: Path, repo_root: Path) -> None:
        self.root = root.resolve()
        self.repo_root = repo_root.resolve()
        self._thread_lock = threading.RLock()

    def _path(self, item_key: str) -> Path:
        require_canonical_item_key(item_key)
        return self.root / item_key / "session.json"

    @contextmanager
    def _locked(self) -> Iterator[None]:
        with self._thread_lock:
            self.root.mkdir(parents=True, exist_ok=True)
            lock_path = self.root / ".review-mode.lock"
            lock_path.touch(mode=0o600, exist_ok=True)
            with lock_path.open("r+", encoding="utf-8") as handle:
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    if fcntl is not None:
                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _load_unlocked(self, item_key: str) -> dict[str, Any] | None:
        path = self._path(item_key)
        if not path.is_file():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ReviewModeError(f"cannot read review session {path}: {exc}") from exc
        errors = validation_errors(value, "review_session", self.repo_root)
        if errors:
            raise ReviewModeError("invalid review session: " + "; ".join(errors))
        if value["item_key"] != item_key:
            raise ReviewModeError("stored review session item_key does not match its path")
        return value

    def load(self, item_key: str) -> dict[str, Any] | None:
        with self._locked():
            return self._load_unlocked(item_key)

    def current(self, item_key: str) -> dict[str, Any]:
        return self.load(item_key) or empty_review_session(item_key)

    @staticmethod
    def _atomic_write(path: Path, value: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", dir=path.parent
        )
        temporary = Path(temporary_name)
        try:
            os.chmod(temporary, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def _save(self, session: dict[str, Any]) -> dict[str, Any]:
        errors = validation_errors(session, "review_session", self.repo_root)
        if errors:
            raise ReviewModeError("invalid review session: " + "; ".join(errors))
        self._atomic_write(
            self._path(session["item_key"]),
            session,
        )
        return session

    def add_finding(
        self,
        item_key: str,
        payload: dict[str, Any],
        *,
        expected_revision: int,
        reviewer: str,
    ) -> dict[str, Any]:
        with self._locked():
            session = self._load_unlocked(item_key)
            session = session or empty_review_session(item_key)
            if session["revision"] != expected_revision:
                raise ReviewModeConflict(
                    item_key, expected_revision, session["revision"]
                )
            finding = _new_finding(payload, reviewer=reviewer)
            session["findings"].append(finding)
            now = _now()
            session["revision"] += 1
            session["created_at"] = session["created_at"] or now
            session["updated_at"] = now
            return self._save(session)

    def update_finding(
        self,
        item_key: str,
        finding_id: str,
        patch: dict[str, Any],
        *,
        expected_revision: int,
    ) -> dict[str, Any]:
        with self._locked():
            session = self._load_unlocked(item_key)
            if session is None:
                raise ReviewModeError("review session does not exist")
            if session["revision"] != expected_revision:
                raise ReviewModeConflict(
                    item_key, expected_revision, session["revision"]
                )
            for index, finding in enumerate(session["findings"]):
                if finding["finding_id"] == finding_id:
                    session["findings"][index] = _updated_finding(finding, patch)
                    break
            else:
                raise ReviewModeError(f"unknown review finding: {finding_id}")
            session["revision"] += 1
            session["updated_at"] = _now()
            return self._save(session)

    def list(self, *, item_key: str | None = None) -> list[dict[str, Any]]:
        if item_key is not None:
            require_canonical_item_key(item_key)
            paths = [self._path(item_key)] if self._path(item_key).is_file() else []
        else:
            paths = sorted(self.root.glob("*/session.json"))
        sessions = []
        for path in paths:
            key = path.parent.name
            session = self.load(key)
            if session is not None:
                sessions.append(session)
        return sessions

    def export(self, *, item_key: str | None = None) -> dict[str, Any]:
        bundle = {
            "schema_version": EXPORT_SCHEMA,
            "exported_at": _now(),
            "sessions": self.list(item_key=item_key),
            "authority": AUTHORITY,
        }
        errors = validation_errors(bundle, "review_session_export", self.repo_root)
        if errors:
            raise ReviewModeError("invalid review session export: " + "; ".join(errors))
        return bundle
