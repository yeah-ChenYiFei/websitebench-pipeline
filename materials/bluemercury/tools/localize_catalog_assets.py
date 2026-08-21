from __future__ import annotations

import concurrent.futures
import hashlib
import ipaddress
import json
import socket
import threading
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRODUCTS_PATH = ROOT / "clone" / "static" / "products.json"
SOURCE_DIR = ROOT / "source-assets" / "2026-08-19.catalog"
RUNTIME_DIR = ROOT / "clone" / "static" / "assets" / "catalog"
APPROVED_HOSTS = frozenset({"bluemercury.com", "cdn.shopify.com"})
ALLOWED_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".webp"})
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 512 * 1024 * 1024
CHUNK_BYTES = 64 * 1024


class AssetValidationError(ValueError):
    pass


def validate_url(url: str, *, resolve: bool = True) -> urllib.parse.ParseResult:
    if not isinstance(url, str) or len(url) > 2048:
        raise AssetValidationError("asset URL must be a bounded string")
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise AssetValidationError("asset URL must use https")
    if parsed.username or parsed.password or parsed.port not in (None, 443):
        raise AssetValidationError("asset URL credentials and custom ports are forbidden")
    host = parsed.hostname.casefold().rstrip(".")
    if host not in APPROVED_HOSTS:
        raise AssetValidationError("asset URL host is not approved")
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        raise AssetValidationError("IP-literal asset hosts are forbidden")
    if resolve:
        addresses = {row[4][0] for row in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
        if not addresses:
            raise AssetValidationError("asset host did not resolve")
        for value in addresses:
            address = ipaddress.ip_address(value)
            if not address.is_global:
                raise AssetValidationError("asset host resolves to non-public address")
    return parsed


def safe_name(index: int, handle: str, url: str) -> str:
    if not isinstance(index, int) or not 0 <= index <= 999:
        raise AssetValidationError("asset index is outside the bounded catalog")
    if not isinstance(handle, str) or not 1 <= len(handle) <= 80:
        raise AssetValidationError("product handle is not bounded")
    if any(not (part.isascii() and part.isalnum() and part == part.casefold()) for part in handle.split("-")):
        raise AssetValidationError("product handle is not a safe lowercase slug")
    suffix = Path(urllib.parse.urlparse(url).path).suffix.casefold()
    if suffix not in ALLOWED_SUFFIXES:
        raise AssetValidationError("asset extension is not allowed")
    return f"{index:03d}-{handle}{suffix}"


def safe_target(root: Path, name: str) -> Path:
    target = (root / name).resolve()
    if target.parent != root.resolve():
        raise AssetValidationError("asset target escaped its root")
    return target


def sniff_mime(body: bytes) -> str:
    if body.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if body.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(body) >= 12 and body[:4] == b"RIFF" and body[8:12] == b"WEBP":
        return "image/webp"
    raise AssetValidationError("asset signature is not an approved image")


class TotalBudget:
    def __init__(self, maximum: int = MAX_TOTAL_BYTES):
        self.maximum = maximum
        self.used = 0
        self._lock = threading.Lock()

    def reserve(self, amount: int) -> None:
        with self._lock:
            if amount < 0 or self.used + amount > self.maximum:
                raise AssetValidationError("catalog asset total-byte limit exceeded")
            self.used += amount


def read_limited(response, budget: TotalBudget) -> bytes:
    declared = response.headers.get("Content-Length")
    if declared:
        try:
            declared_size = int(declared)
        except ValueError:
            raise AssetValidationError("invalid Content-Length") from None
        if declared_size < 0 or declared_size > MAX_FILE_BYTES:
            raise AssetValidationError("asset exceeds the per-file byte limit")
    chunks: list[bytes] = []
    size = 0
    while True:
        chunk = response.read(CHUNK_BYTES)
        if not chunk:
            break
        size += len(chunk)
        if size > MAX_FILE_BYTES:
            raise AssetValidationError("asset exceeds the per-file byte limit")
        chunks.append(chunk)
    budget.reserve(size)
    return b"".join(chunks)


class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(item: tuple[int, dict], *, budget: TotalBudget) -> dict:
    index, product = item
    url = (product.get("images") or [None])[0]
    handle = product.get("handle")
    if not url:
        return {"index": index, "handle": handle, "url": None, "error": "no source image"}
    try:
        validate_url(url)
        name = safe_name(index, handle, url)
        source_path = safe_target(SOURCE_DIR, name)
        runtime_path = safe_target(RUNTIME_DIR, name)
        request = urllib.request.Request(url, headers={"User-Agent": "WebsiteBenchAssetCapture/1.0"})
        opener = urllib.request.build_opener(SafeRedirectHandler())
        with opener.open(request, timeout=30) as response:
            validate_url(response.geturl())
            body = read_limited(response, budget)
            declared_type = response.headers.get_content_type().casefold()
        detected_type = sniff_mime(body)
        if declared_type not in {detected_type, "application/octet-stream"}:
            raise AssetValidationError("asset MIME type does not match its signature")
        source_path.write_bytes(body)
        runtime_path.write_bytes(body)
        return {"index": index, "handle": handle, "url": url, "name": name,
                "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(),
                "mime_type": detected_type}
    except Exception as exc:
        return {"index": index, "handle": handle, "url": url, "error": type(exc).__name__}


def main() -> None:
    products_doc = json.loads(PRODUCTS_PATH.read_text(encoding="utf-8"))
    products = products_doc.get("products", products_doc)
    SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    budget = TotalBudget()
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda item: fetch(item, budget=budget), enumerate(products)))
    results.sort(key=lambda row: row["index"])
    (ROOT / "source-assets" / "catalog-provenance.json").write_text(
        json.dumps({"schema_version": "websitebench.catalog-assets.v1", "results": results}, indent=2),
        encoding="utf-8",
    )
    mapping = {row["handle"]: row.get("name") for row in results if row.get("name")}
    (ROOT / "clone" / "static" / "catalog-image-map.json").write_text(
        json.dumps(mapping, indent=2), encoding="utf-8"
    )
    print(json.dumps({"products": len(products), "downloaded": len(mapping),
                      "missing": len(products) - len(mapping), "bytes": budget.used}))


if __name__ == "__main__":
    main()
