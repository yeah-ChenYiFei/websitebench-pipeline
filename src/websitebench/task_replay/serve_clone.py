"""Load a clone application by file path without shadowing WebsiteBench modules."""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from typing import Sequence

import uvicorn


def load_app(app_file: Path):
    """Import one FastAPI app under an isolated, deterministic module name."""

    resolved = app_file.resolve()
    spec = importlib.util.spec_from_file_location("websitebench_replay_clone_app", resolved)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load clone app: {resolved}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    app = getattr(module, "app", None)
    if app is None:
        raise RuntimeError(f"clone app has no app object: {resolved}")
    return app


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app-file", type=Path, required=True)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args(argv)
    uvicorn.run(load_app(args.app_file), host="127.0.0.1", port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
