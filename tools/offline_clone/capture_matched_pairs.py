#!/usr/bin/env python3
"""Deterministically capture source/candidate pairs for machine comparison.

This tool covers the configured matrix and emits reproducible evidence for
independent visual and interaction verification.

Expected matrix format (adapt keys here if your repository differs):

    rows:
      - id: home-default-desktop
        route: /
        viewport: {width: 1440, height: 900}
        state: default      # any other state is reported as needs-driver;
                            # this generic script only drives default
                            # navigation state — wire a per-site driver for
                            # loading/validation/overlay states.
        pair: captured
      - id: search-overlay-desktop
        state: overlay
        pair:
          mode: driver
          driver: search-overlay-capture-v1
          source:
            path: frozen-pairs/search-overlay.source.png
            sha256: <sha256>
          candidate:
            path: driver-output/search-overlay.candidate.png
            sha256: <sha256>

Source images are copied from --source-evidence-dir/<id>.png|.jpg (frozen
capture evidence — a live source cannot be re-screenshotted offline);
candidate images are screenshotted from the served clone with Playwright.
Non-default or externally captured rows use a ``pair`` mapping with
``mode: external|frozen|driver`` and explicit, already-frozen source/candidate
paths and SHA-256 values. ``driver`` mode also requires a stable driver ID.
The output ``matched-pairs.json`` binds the full matrix and every copied image.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    print(
        json.dumps({"status": "error", "error": "PyYAML required: pip install pyyaml"})
    )
    sys.exit(2)

SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_row_id(value: Any) -> str | None:
    row_id = str(value) if value is not None else ""
    if not row_id or row_id in {".", ".."} or "/" in row_id or "\\" in row_id:
        return None
    return row_id


def _resolve_declared_artifact(
    *,
    matrix_path: Path,
    row_id: str,
    pair: dict[str, Any],
    side: str,
) -> tuple[Path | None, str | None]:
    value = pair.get(side)
    if not isinstance(value, dict):
        return None, f"{row_id}: pair.{side} must be an object with path and sha256"
    raw_path = value.get("path")
    expected = value.get("sha256")
    if not isinstance(raw_path, str) or not raw_path:
        return None, f"{row_id}: pair.{side}.path must be a non-empty string"
    if not isinstance(expected, str) or not SHA256_PATTERN.fullmatch(expected):
        return None, f"{row_id}: pair.{side}.sha256 must be lowercase SHA-256"
    artifact = Path(raw_path)
    if not artifact.is_absolute():
        artifact = matrix_path.parent / artifact
    artifact = artifact.resolve()
    if not artifact.is_file():
        return None, f"{row_id}: declared {side} artifact not found: {artifact}"
    if artifact.suffix.lower() not in IMAGE_EXTENSIONS:
        return None, f"{row_id}: declared {side} artifact must be PNG or JPEG"
    actual = _sha256(artifact)
    if actual != expected:
        return (
            None,
            f"{row_id}: declared {side} artifact hash mismatch; expected {expected}, got {actual}",
        )
    return artifact, None


def _copy_declared_pair(
    *,
    matrix_path: Path,
    row_id: str,
    pair: dict[str, Any],
    out: Path,
) -> tuple[dict[str, Any] | None, str | None]:
    raw_mode = pair.get("mode")
    mode = "external" if raw_mode == "frozen" else raw_mode
    if not isinstance(mode, str) or mode not in {"external", "driver"}:
        return None, f"{row_id}: pair.mode must be external, frozen, or driver"
    driver = pair.get("driver")
    if mode == "driver" and (not isinstance(driver, str) or not driver.strip()):
        return None, f"{row_id}: pair.driver must identify the declared driver"
    artifact_stem = pair.get("artifact_stem", row_id)
    if (
        not isinstance(artifact_stem, str)
        or not artifact_stem
        or artifact_stem in {".", ".."}
        or "/" in artifact_stem
        or "\\" in artifact_stem
        or not re.fullmatch(r"[A-Za-z0-9._-]+", artifact_stem)
    ):
        return None, (
            f"{row_id}: pair.artifact_stem must be a safe portable filename stem"
        )

    artifacts: dict[str, Path] = {}
    for side in ("source", "candidate"):
        artifact, error = _resolve_declared_artifact(
            matrix_path=matrix_path,
            row_id=row_id,
            pair=pair,
            side=side,
        )
        if error:
            return None, error
        assert artifact is not None
        artifacts[side] = artifact

    entry: dict[str, Any] = {"id": row_id, "mode": mode}
    if mode == "driver":
        entry["driver"] = driver.strip()
    for side, artifact in artifacts.items():
        target = out / f"{artifact_stem}.{side}{artifact.suffix.lower()}"
        shutil.copy2(artifact, target)
        entry[side] = {
            "path": target.relative_to(out).as_posix(),
            "sha256": _sha256(target),
        }
    return entry, None


def _print_result(
    *,
    status: str,
    captured: list[str],
    external: list[str],
    drivers: list[str],
    needs_driver: list[str],
    missing_source: list[str],
    invalid_pairs: list[str],
    manifest: Path | None = None,
) -> None:
    print(
        json.dumps(
            {
                "status": status,
                "captured": captured,
                "external": external,
                "drivers": drivers,
                "needs_driver": needs_driver,
                "missing_source": missing_source,
                "invalid_pairs": invalid_pairs,
                "manifest": str(manifest) if manifest is not None else None,
                "note": (
                    "Every frozen matrix row needs one verified source/candidate "
                    "pair. Non-default rows require an explicit external/frozen "
                    "pair or declared driver output with per-artifact SHA-256."
                    if status != "captured"
                    else ""
                ),
            },
            indent=2,
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", type=Path, required=True)
    parser.add_argument("--candidate-url", required=True)
    parser.add_argument("--source-evidence-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    try:
        matrix_path = args.matrix.resolve()
        matrix = yaml.safe_load(matrix_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        print(json.dumps({"status": "error", "error": str(error)}))
        return 1
    rows = matrix.get("rows") if isinstance(matrix, dict) else None
    if not isinstance(rows, list) or not rows:
        print(
            json.dumps(
                {"status": "error", "error": f"{args.matrix}: expected non-empty rows"}
            )
        )
        return 1

    if args.out.exists() and any(args.out.iterdir()):
        print(
            json.dumps(
                {
                    "status": "error",
                    "error": (
                        f"{args.out}: refusing non-empty matched-pair output; "
                        "use a fresh round directory"
                    ),
                }
            )
        )
        return 1
    args.out.mkdir(parents=True, exist_ok=True)
    captured: list[str] = []
    needs_driver: list[str] = []
    external: list[str] = []
    drivers: list[str] = []
    missing_source: list[str] = []
    invalid_pairs: list[str] = []
    entries: list[dict[str, Any]] = []
    capture_rows: list[tuple[dict[str, Any], str, Path, dict[str, Any]]] = []
    seen_ids: set[str] = set()
    base = args.candidate_url.rstrip("/")

    for row in rows:
        if not isinstance(row, dict):
            invalid_pairs.append("every row must be an object with a safe id")
            continue
        row_id = _safe_row_id(row.get("id"))
        if row_id is None:
            invalid_pairs.append(f"unsafe or empty row id: {row.get('id')!r}")
            continue
        if row_id in seen_ids:
            invalid_pairs.append(f"duplicate row id: {row_id}")
            continue
        seen_ids.add(row_id)

        pair = row.get("pair", "captured")
        if isinstance(pair, dict):
            entry, error = _copy_declared_pair(
                matrix_path=matrix_path,
                row_id=row_id,
                pair=pair,
                out=args.out,
            )
            if error:
                invalid_pairs.append(error)
                continue
            assert entry is not None
            entries.append(entry)
            if entry["mode"] == "driver":
                drivers.append(row_id)
            else:
                external.append(row_id)
            continue
        if isinstance(pair, str) and pair in {"external", "frozen", "driver"}:
            invalid_pairs.append(
                f"{row_id}: pair: {pair} must be an object with mode, "
                "source, candidate, hashes, and driver when applicable"
            )
            continue
        if pair is not None and pair != "captured":
            invalid_pairs.append(f"{row_id}: unsupported pair declaration {pair!r}")
            continue

        source: Path | None = None
        for extension in IMAGE_EXTENSIONS:
            candidate = args.source_evidence_dir / f"{row_id}{extension}"
            if candidate.is_file():
                source = candidate.resolve()
                break
        if source is None:
            missing_source.append(row_id)
            continue
        target = args.out / f"{row_id}.source{source.suffix.lower()}"
        shutil.copy2(source, target)
        if row.get("state", "default") != "default":
            needs_driver.append(row_id)
            continue
        viewport = row.get("viewport") or {}
        if not isinstance(viewport, dict):
            invalid_pairs.append(f"{row_id}: viewport must be an object")
            continue
        capture_rows.append((row, row_id, target, viewport))

    if invalid_pairs or needs_driver or missing_source:
        _print_result(
            status="incomplete",
            captured=captured,
            external=external,
            drivers=drivers,
            needs_driver=needs_driver,
            missing_source=missing_source,
            invalid_pairs=invalid_pairs,
        )
        return 1

    if capture_rows:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            print(
                json.dumps(
                    {
                        "status": "error",
                        "error": (
                            "playwright required: pip install playwright && "
                            "playwright install chromium"
                        ),
                    }
                )
            )
            return 2

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                for row, row_id, source, viewport in capture_rows:
                    page = browser.new_page(
                        viewport={
                            "width": int(viewport.get("width", 1280)),
                            "height": int(viewport.get("height", 800)),
                        }
                    )
                    try:
                        page.goto(
                            base + str(row.get("route", "/")),
                            wait_until="networkidle",
                        )
                        target = args.out / f"{row_id}.candidate.png"
                        page.screenshot(path=str(target), full_page=True)
                        entries.append(
                            {
                                "id": row_id,
                                "mode": "captured",
                                "source": {
                                    "path": source.relative_to(args.out).as_posix(),
                                    "sha256": _sha256(source),
                                },
                                "candidate": {
                                    "path": target.relative_to(args.out).as_posix(),
                                    "sha256": _sha256(target),
                                },
                            }
                        )
                        captured.append(row_id)
                    finally:
                        page.close()
            finally:
                browser.close()

    if len(entries) != len(rows):
        invalid_pairs.append(
            f"verified {len(entries)} pairs for {len(rows)} frozen matrix rows"
        )
        _print_result(
            status="incomplete",
            captured=captured,
            external=external,
            drivers=drivers,
            needs_driver=needs_driver,
            missing_source=missing_source,
            invalid_pairs=invalid_pairs,
        )
        return 1

    by_id = {entry["id"]: entry for entry in entries}
    ordered_entries = [by_id[str(row["id"])] for row in rows]
    manifest = args.out / "matched-pairs.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "clawbench.matched-pairs.v1",
                "matrix_sha256": _sha256(matrix_path),
                "rows": ordered_entries,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    _print_result(
        status="captured",
        captured=captured,
        external=external,
        drivers=drivers,
        needs_driver=needs_driver,
        missing_source=missing_source,
        invalid_pairs=invalid_pairs,
        manifest=manifest,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
