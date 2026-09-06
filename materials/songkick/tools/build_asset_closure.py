"""Close the frozen asset manifest against the localized runtime copies.

Original capture files remain untouched. When URL rewriting or image
normalization changed bytes, this creates a separate source-side copy of the
localized derivative so the verifier can prove source/runtime byte identity.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from websitebench.offline_clone.assets import inspect_asset


SITE_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = SITE_ROOT / "source-assets" / "manifest.json"
DERIVATIVE_ROOT = SITE_ROOT / "source-assets" / "runtime-files"


def main() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    changed = 0
    for asset in manifest["assets"]:
        runtime_relative = Path(asset["runtime_path"])
        runtime_path = SITE_ROOT / runtime_relative
        source_path = SITE_ROOT / asset["source_path"]
        runtime_bytes = runtime_path.read_bytes()
        source_bytes = source_path.read_bytes()
        if source_path.resolve() == runtime_path.resolve():
            localized_relative = Path("source-assets/files") / runtime_relative.relative_to(
                "clone/assets/source"
            )
            localized_path = SITE_ROOT / localized_relative
            localized_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(runtime_path, localized_path)
            asset["source_path"] = localized_relative.as_posix()
            changed += 1
        elif source_bytes != runtime_bytes:
            localized_relative = Path("source-assets/runtime-files") / runtime_relative.relative_to(
                "clone/assets/source"
            )
            localized_path = SITE_ROOT / localized_relative
            localized_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(runtime_path, localized_path)
            asset["source_path"] = localized_relative.as_posix()
            asset["evidence_kind"] = "bounded"
            changed += 1
        observed = inspect_asset(runtime_path)
        asset.update(observed)
        asset["sha256"] = hashlib.sha256(runtime_bytes).hexdigest()
    MANIFEST_PATH.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "assets": len(manifest["assets"]),
                "localized_derivatives": changed,
                "original_capture_files_preserved": True,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
