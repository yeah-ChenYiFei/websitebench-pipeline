import hashlib
import json
from pathlib import Path


SITE = Path(__file__).resolve().parents[2]


def test_declared_assets_exist_and_match() -> None:
    manifest = json.loads((SITE / "source-assets" / "manifest.json").read_text("utf-8"))
    assert manifest["closure_status"] == "declared"
    assert manifest["remote_runtime_policy"] == "forbidden"
    assert len(manifest["assets"]) == 10
    for item in manifest["assets"]:
        source = SITE / item["source_path"]
        runtime = SITE / item["runtime_path"]
        assert source.is_file()
        assert runtime.is_file()
        assert source.read_bytes() == runtime.read_bytes()
        assert hashlib.sha256(source.read_bytes()).hexdigest() == item["sha256"]


def test_no_remote_runtime_literals() -> None:
    clone = SITE / "clone"
    for path in clone.rglob("*"):
        if (
            path.is_file()
            and path.suffix in {".html", ".css", ".js", ".py"}
            and "tests" not in path.parts
            and "websitebench" not in path.parts
        ):
            text = path.read_text("utf-8")
            assert "https://fentybeauty.com" not in text
            assert "cdn.shopify.com" not in text
