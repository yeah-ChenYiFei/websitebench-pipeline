"""Content-addressed cache for anonymous source asset capture."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path


SHA256 = re.compile(r"^[0-9a-f]{64}$")
CACHE_SCHEMA_VERSION = "websitebench.asset-payload-cache.v1"
READABLE_CACHE_SCHEMA_VERSIONS = frozenset(
    {
        CACHE_SCHEMA_VERSION,
        "clawbench.asset-payload-cache.v1",
    }
)


def write_bytes_if_changed(path: Path, payload: bytes) -> bool:
    """Atomically write bytes, preserving the target when content is identical."""

    path = path.absolute()
    if path.is_symlink():
        raise ValueError(f"refusing to write through symbolic link: {path}")
    if path.is_file() and path.read_bytes() == payload:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".payload-",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return True


class AssetPayloadCache:
    """Map an exact source URL to an inspected, content-addressed payload."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def _url_record_path(self, url: str) -> Path:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return self.root / "urls" / digest[:2] / f"{digest}.json"

    def _blob_path(self, digest: str) -> Path:
        return self.root / "sha256" / digest[:2] / digest

    def get(self, url: str) -> bytes | None:
        record_path = self._url_record_path(url)
        if not record_path.is_file():
            return None
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return None
        digest = record.get("sha256") if isinstance(record, dict) else None
        if (
            not isinstance(record, dict)
            or record.get("schema_version") not in READABLE_CACHE_SCHEMA_VERSIONS
            or record.get("source_url") != url
            or not isinstance(digest, str)
            or not SHA256.fullmatch(digest)
        ):
            return None
        blob = self._blob_path(digest)
        try:
            payload = blob.read_bytes()
        except OSError:
            return None
        if hashlib.sha256(payload).hexdigest() != digest:
            return None
        return payload

    def put(self, url: str, payload: bytes) -> str:
        digest = hashlib.sha256(payload).hexdigest()
        write_bytes_if_changed(self._blob_path(digest), payload)
        record = {
            "schema_version": CACHE_SCHEMA_VERSION,
            "source_url": url,
            "sha256": digest,
            "bytes": len(payload),
        }
        write_bytes_if_changed(
            self._url_record_path(url),
            (
                json.dumps(
                    record,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            ).encode("utf-8"),
        )
        return digest
