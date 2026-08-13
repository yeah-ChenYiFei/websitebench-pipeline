#!/usr/bin/env bash
set -Eeuo pipefail

: "${PORT:=8080}"
: "${WEBSITEBENCH_DATA_DIR:=/tmp/websitebench-tripit}"

# Runtime state must never land inside the repository tree. The vendored clone
# resolves its data directory from several environment names depending on which
# lineage it came from, so export all of them from the one value above.
export WEBSITEBENCH_DATA_DIR
export CLAWBENCH_DATA_DIR="$WEBSITEBENCH_DATA_DIR"

# The backend runtime contract normally resolves to <site>/backend/runtime.json.
# Inside a Harbor bundle only reference/ is copied, so it is vendored here and
# pointed at explicitly.
export WEBSITEBENCH_SITE_BACKEND_RUNTIME="${WEBSITEBENCH_SITE_BACKEND_RUNTIME:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/site-config/runtime.json}"

mkdir -p "$WEBSITEBENCH_DATA_DIR"

exec python3 -m uvicorn app:app --host 0.0.0.0 --port "$PORT"
