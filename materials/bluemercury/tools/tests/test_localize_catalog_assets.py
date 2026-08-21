from __future__ import annotations

import io
from email.message import Message

import pytest

import localize_catalog_assets as assets


class FakeResponse(io.BytesIO):
    def __init__(self, body: bytes, content_type: str = "image/png", length: str | None = None):
        super().__init__(body)
        self.headers = Message()
        self.headers["Content-Type"] = content_type
        if length is not None:
            self.headers["Content-Length"] = length


def test_url_policy_rejects_untrusted_schemes_hosts_credentials_and_private_dns(monkeypatch):
    assert assets.validate_url("https://cdn.shopify.com/files/image.jpg", resolve=False).hostname == "cdn.shopify.com"
    for url in (
        "http://cdn.shopify.com/image.jpg",
        "file:///etc/passwd",
        "https://evil.example/image.jpg",
        "https://user:password@cdn.shopify.com/image.jpg",
        "https://cdn.shopify.com:8443/image.jpg",
        "https://127.0.0.1/image.jpg",
    ):
        with pytest.raises((assets.AssetValidationError, ValueError)):
            assets.validate_url(url, resolve=False)
    monkeypatch.setattr(assets.socket, "getaddrinfo", lambda *args, **kwargs: [(2, 1, 6, "", ("127.0.0.1", 443))])
    with pytest.raises(assets.AssetValidationError, match="non-public"):
        assets.validate_url("https://cdn.shopify.com/image.jpg")


def test_slug_suffix_and_resolved_target_reject_path_escape(tmp_path):
    assert assets.safe_name(7, "safe-product", "https://cdn.shopify.com/x/image.jpg") == "007-safe-product.jpg"
    for handle in ("../escape", "UPPER", "bad/slash", "éclair", ""):
        with pytest.raises(assets.AssetValidationError):
            assets.safe_name(1, handle, "https://cdn.shopify.com/x/image.jpg")
    with pytest.raises(assets.AssetValidationError):
        assets.safe_name(1, "safe", "https://cdn.shopify.com/x/file.svg")
    with pytest.raises(assets.AssetValidationError):
        assets.safe_target(tmp_path, "../escape.jpg")


def test_streaming_limits_total_budget_and_image_signatures():
    png = b"\x89PNG\r\n\x1a\n" + b"x" * 32
    assert assets.sniff_mime(png) == "image/png"
    assert assets.sniff_mime(b"\xff\xd8\xff" + b"x" * 10) == "image/jpeg"
    assert assets.sniff_mime(b"RIFFxxxxWEBP" + b"x" * 10) == "image/webp"
    with pytest.raises(assets.AssetValidationError):
        assets.sniff_mime(b"<svg><script>")
    budget = assets.TotalBudget(maximum=len(png))
    assert assets.read_limited(FakeResponse(png, length=str(len(png))), budget) == png
    assert budget.used == len(png)
    with pytest.raises(assets.AssetValidationError, match="total-byte"):
        assets.read_limited(FakeResponse(b"x"), budget)
    with pytest.raises(assets.AssetValidationError, match="per-file"):
        assets.read_limited(FakeResponse(b"", length=str(assets.MAX_FILE_BYTES + 1)), assets.TotalBudget())


def test_invalid_source_is_rejected_before_any_network_call(monkeypatch):
    called = False
    def forbidden_opener(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("network must not be reached")
    monkeypatch.setattr(assets.urllib.request, "build_opener", forbidden_opener)
    result = assets.fetch((0, {"handle": "safe", "images": ["http://cdn.shopify.com/image.jpg"]}), budget=assets.TotalBudget())
    assert result["error"] == "AssetValidationError"
    assert called is False


def test_redirect_policy_revalidates_every_location():
    handler = assets.SafeRedirectHandler()
    with pytest.raises(assets.AssetValidationError):
        handler.redirect_request(None, None, 302, "Found", {}, "file:///etc/passwd")
