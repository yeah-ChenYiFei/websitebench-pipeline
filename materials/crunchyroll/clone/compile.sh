#!/usr/bin/env bash
set -Eeuo pipefail

if (($# != 0)); then
  printf 'compile.sh takes no arguments\n' >&2
  exit 64
fi

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
TARGET="$ROOT/executable"
umask 022
cat > "$TARGET" <<'EXECUTABLE'
#!/usr/bin/env python3
from __future__ import annotations

import os
import random
import sys
import time
from pathlib import Path

root = Path(__file__).resolve().parent
required = {}
for name in ("HOST", "PORT", "DATA_DIR", "SEED", "TZ"):
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"{name} is required")
    required[name] = value

data_dir = Path(required["DATA_DIR"])
data_dir.mkdir(parents=True, exist_ok=True)
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
os.environ["PYTHONHASHSEED"] = required["SEED"]
os.environ["WEBSITEBENCH_DATA_DIR"] = str(data_dir)
os.environ["WEBSITEBENCH_SITE_BACKEND_RUNTIME"] = str(root / "backend" / "runtime.json")
os.environ["WEBSITEBENCH_SITE_BACKEND_DATABASE"] = str(data_dir / "crunchyroll.sqlite3")
os.environ["WEBSITEBENCH_LOCAL_HTTP_COOKIE"] = "1"
if hasattr(time, "tzset"):
    time.tzset()
random.seed(required["SEED"])
sys.path[:0] = [str(root / "vendor"), str(root)]

import uvicorn

uvicorn.run("app:app", host=required["HOST"], port=int(required["PORT"]), log_level="warning")
EXECUTABLE
chmod 755 "$TARGET"
