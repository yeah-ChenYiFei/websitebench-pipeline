"""Build the BeerAdvocate asset manifest from the sanitized capture report."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from websitebench.site_compiler.canonical import sha256_file


SITE_ROOT = Path(__file__).resolve().parents[1]
CAPTURE_REPORT = (
    SITE_ROOT / "source-assets" / "2026-08-20.edge-r1" / "capture-report.json"
)
MANIFEST = SITE_ROOT / "source-assets" / "manifest.json"

ACTIVE_SUFFIXES = {
    "avatars/0-2.jpg",
    "beers/102.jpg",
    "beers/1160.jpg",
    "beers/1784.jpg",
    "beers/599268.jpg",
    "beers/799121.jpg",
    "beers/803735.jpg",
    "beers/804818.jpg",
    "beers/806254.jpg",
    "beers/85094.jpg",
    "brand/beeradvocate-nav-brandmark.png",
    "brand/beeradvocate-nav-logo.png",
    "ui/c_beer_image.gif",
}
SCREENSHOT_DERIVED_ASSETS = (
    {
        "source_path": "source-current/ea1/01-home-desktop.png",
        "runtime_path": "clone/static/assets/evidence/home-desktop.png",
        "priority": "p0",
        "required": True,
        "mime_type": "image/png",
        "dimensions": {"width": 1425, "height": 2909},
        "referenced_by": ["candidate:clone/app.py:homepage-missing-beer-slices"],
        "evidence_kind": "bounded",
        "capture_id": "2026-08-20.ea1.home-desktop",
    },
)


def _bounded_file(relative_value: object, root: Path, label: str) -> tuple[Path, Path]:
    relative = Path(str(relative_value))
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"{label} must be a site-relative path: {relative}")
    resolved = (SITE_ROOT / relative).resolve()
    resolved_root = root.resolve()
    if not resolved.is_relative_to(resolved_root):
        raise ValueError(f"{label} escapes {resolved_root}: {relative}")
    return relative, resolved


def _canonical_runtime_path(runtime_path: Path, mime_type: str) -> Path:
    suffixes = {
        "image/gif": ".gif",
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
    }
    try:
        return runtime_path.with_suffix(suffixes[mime_type])
    except KeyError as exc:
        raise ValueError(f"unsupported image MIME type: {mime_type}") from exc


def _atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.parent / f".{destination.name}.tmp"
    shutil.copyfile(source, temporary)
    temporary.replace(destination)


def main() -> int:
    report = json.loads(CAPTURE_REPORT.read_text(encoding="utf-8"))
    assets = []
    seen_ids: set[str] = set()
    seen_runtime_paths: set[Path] = set()
    captured_suffixes: set[str] = set()
    for captured in report["assets"]:
        asset = {
            key: value
            for key, value in captured.items()
            if key != "source_url_variants"
        }
        source_path, source_file = _bounded_file(
            asset["source_path"], CAPTURE_REPORT.parent, "source_path"
        )
        logical_suffix = "/".join(source_path.parts[-2:])
        captured_suffixes.add(logical_suffix)
        active = logical_suffix in ACTIVE_SUFFIXES
        reported_runtime_path, _ = _bounded_file(
            asset["runtime_path"],
            SITE_ROOT / "clone" / "static" / "assets",
            "runtime_path",
        )
        runtime_path = _canonical_runtime_path(
            reported_runtime_path, str(asset["mime_type"])
        )
        runtime_path, runtime_file = _bounded_file(
            runtime_path, SITE_ROOT / "clone" / "static" / "assets", "runtime_path"
        )
        asset["runtime_path"] = runtime_path.as_posix()

        if not source_file.is_file():
            raise FileNotFoundError(f"missing source asset: {source_path}")
        observed_bytes = source_file.stat().st_size
        observed_sha256 = sha256_file(source_file)
        if observed_bytes != int(asset["bytes"]):
            raise ValueError(
                f"capture byte mismatch for {source_path}: "
                f"{observed_bytes} != {asset['bytes']}"
            )
        if observed_sha256 != str(asset.get("sha256", "")):
            raise ValueError(f"capture digest mismatch for {source_path}")
        expected_id = f"beeradvocate.{observed_sha256[:16]}"
        if asset["id"] != expected_id:
            raise ValueError(f"capture id mismatch for {source_path}: {asset['id']}")
        if asset["id"] in seen_ids:
            raise ValueError(f"duplicate asset id: {asset['id']}")
        if runtime_path in seen_runtime_paths:
            raise ValueError(f"duplicate runtime path: {runtime_path}")
        seen_ids.add(str(asset["id"]))
        seen_runtime_paths.add(runtime_path)

        if not runtime_file.is_file():
            _atomic_copy(source_file, runtime_file)
        if runtime_file.stat().st_size != observed_bytes:
            raise ValueError(f"asset byte-count mismatch: {source_path} -> {runtime_path}")
        if observed_sha256 != sha256_file(runtime_file):
            raise ValueError(f"asset byte mismatch: {source_path} -> {runtime_path}")
        asset["priority"] = "p0" if active else "p2"
        asset["required"] = active
        asset["referenced_by"] = ["candidate:clone/app.py"] if active else []
        assets.append(asset)

    for descriptor in SCREENSHOT_DERIVED_ASSETS:
        source_path, source_file = _bounded_file(
            descriptor["source_path"], SITE_ROOT / "source-current", "source_path"
        )
        runtime_path, runtime_file = _bounded_file(
            descriptor["runtime_path"],
            SITE_ROOT / "clone" / "static" / "assets",
            "runtime_path",
        )
        if not source_file.is_file():
            raise FileNotFoundError(f"missing screenshot evidence: {source_path}")
        digest = sha256_file(source_file)
        asset_id = f"beeradvocate.{digest[:16]}"
        if asset_id in seen_ids or runtime_path in seen_runtime_paths:
            raise ValueError(f"duplicate screenshot-derived asset: {runtime_path}")
        if not runtime_file.is_file():
            _atomic_copy(source_file, runtime_file)
        if source_file.read_bytes() != runtime_file.read_bytes():
            raise ValueError(
                f"screenshot-derived asset mismatch: {source_path} -> {runtime_path}"
            )
        seen_ids.add(asset_id)
        seen_runtime_paths.add(runtime_path)
        assets.append(
            {
                "id": asset_id,
                "source_path": source_path.as_posix(),
                "runtime_path": runtime_path.as_posix(),
                "bytes": source_file.stat().st_size,
                "sha256": digest,
                **{
                    key: value
                    for key, value in descriptor.items()
                    if key not in {"source_path", "runtime_path"}
                },
            }
        )

    reported_missing = {str(path) for path in report.get("missing_required_paths", [])}
    missing_required_paths = sorted(
        reported_missing | (ACTIVE_SUFFIXES - captured_suffixes)
    )
    closure_ready = bool(
        report.get("closure_ready", not report.get("failures"))
    ) and not missing_required_paths
    manifest = {
        "schema_version": "offline-clone.assets.v1",
        "snapshot_id": "2026-08-20.beeradvocate.edge-r1",
        "created_at": report["captured_at"],
        "remote_runtime_policy": "forbidden",
        "closure_status": "declared" if closure_ready else "pending",
        "no_assets_reason": None,
        "assets": assets,
    }
    temporary_manifest = MANIFEST.with_suffix(".json.tmp")
    temporary_manifest.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary_manifest.replace(MANIFEST)
    print(
        json.dumps(
            {
                "assets": len(assets),
                "required": sum(a["required"] for a in assets),
                "closure_status": manifest["closure_status"],
                "missing_required_paths": missing_required_paths,
            }
        )
    )
    return 0 if closure_ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
