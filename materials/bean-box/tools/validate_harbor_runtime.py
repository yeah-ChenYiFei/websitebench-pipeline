"""Run the repository's quarantined Harbor compiler/runtime against Bean Box."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from websitebench.harbor.compiler_v2 import (
    CompilerSandboxError,
    compile_candidate,
    validate_runtime_lifecycle,
)


REPO = Path(__file__).resolve().parents[3]
CANDIDATE = REPO / "materials" / "bean-box" / "clone"
OUTPUT = REPO / "materials" / "bean-box" / "artifacts" / "offline-clone" / "harbor-runtime-dry-run.json"


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="bean-box-harbor-runtime-") as temporary:
        root = Path(temporary)
        artifact = compile_candidate(CANDIDATE, root / "private", timeout=120, seed=16)
        try:
            result = validate_runtime_lifecycle(
                artifact,
                port=8490,
                seed=16,
                working_root=root / "runtime",
                timezone="UTC",
            )
        except CompilerSandboxError as exc:
            logs = {}
            for log in root.rglob("*.log"):
                logs[str(log.relative_to(root))] = log.read_text(encoding="utf-8", errors="replace")[-8000:]
            result = {"valid": False, "error": str(exc), "logs": logs}
        if not result.get("valid") and "logs" not in result:
            result["logs"] = {
                str(log.relative_to(root)): log.read_text(encoding="utf-8", errors="replace")[-8000:]
                for log in root.rglob("*.log")
            }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps({"site_id": "bean-box", "candidate": str(CANDIDATE), **result}, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, indent=2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
