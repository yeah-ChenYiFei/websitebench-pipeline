#!/usr/bin/env bash
set -Eeuo pipefail

: "${PORT:=8080}"
: "${WEBSITEBENCH_DATA_DIR:=/tmp/websitebench-aspca-pet-insurance}"

# Runtime state must never land inside the repository tree.
export WEBSITEBENCH_DATA_DIR

# The backend runtime contract normally resolves to <site>/backend/runtime.json.
# Inside a Harbor bundle only reference/ is copied, so it is vendored here and
# pointed at explicitly.
export WEBSITEBENCH_SITE_BACKEND_RUNTIME="${WEBSITEBENCH_SITE_BACKEND_RUNTIME:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/site-config/runtime.json}"

# Without an explicit database path the site backend resolves its data
# directory relative to the runtime contract, which would put SQLite state
# inside the bundle. Pin it into the data dir; the filename must match the
# runtime contract's database_filename.
export WEBSITEBENCH_SITE_BACKEND_DATABASE="${WEBSITEBENCH_SITE_BACKEND_DATABASE:-$WEBSITEBENCH_DATA_DIR/aspca-pet-insurance.sqlite3}"

mkdir -p "$WEBSITEBENCH_DATA_DIR"

exec python3 -m uvicorn app:app --host 0.0.0.0 --port "$PORT"
