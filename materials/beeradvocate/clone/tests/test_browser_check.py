from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from browser_check import is_same_origin, origin, validate_loopback_base_url


def test_origin_normalizes_default_ports_and_hostname_case() -> None:
    assert origin("HTTPS://BeerAdvocate.Test/path") == (
        "https",
        "beeradvocate.test",
        443,
    )
    assert is_same_origin(
        "https://beeradvocate.test:443/static/app.css",
        "https://BEERADVOCATE.TEST",
    )


def test_same_origin_rejects_userinfo_prefix_and_port_changes() -> None:
    base_url = "http://127.0.0.1:4174"
    assert not is_same_origin(
        "http://127.0.0.1:4174@evil.example/assets/track.js",
        base_url,
    )
    assert not is_same_origin("http://127.0.0.1:4175/assets/app.js", base_url)
    assert not is_same_origin("data:text/plain,local", base_url)


def test_browser_check_accepts_only_explicit_http_loopback_origins() -> None:
    assert validate_loopback_base_url("http://127.0.0.1:4174/") == (
        "http://127.0.0.1:4174"
    )
    assert validate_loopback_base_url("http://localhost:4174") == (
        "http://localhost:4174"
    )
    assert validate_loopback_base_url("http://[::1]:4174") == "http://[::1]:4174"
    rejected = (
        "https://beeradvocate.com:443",
        "http://beeradvocate.com:4174",
        "http://127.0.0.1",
        "http://127.0.0.1:4174@evil.example",
        "http://[2001:db8::1]:4174",
        "http://127.0.0.1:4174/path",
    )
    for base_url in rejected:
        with pytest.raises(ValueError):
            validate_loopback_base_url(base_url)
