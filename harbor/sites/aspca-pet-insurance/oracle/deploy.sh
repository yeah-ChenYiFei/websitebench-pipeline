#!/usr/bin/env bash
# Oracle candidate entrypoint — the same contract every candidate must meet:
# foreground process, binds $PORT, HTTP 200 on /healthz, mutable state only
# under $WEBSITEBENCH_DATA_DIR, exits on SIGTERM.
set -Eeuo pipefail

: "${PORT:=3000}"
: "${WEBSITEBENCH_DATA_DIR:=/tmp/websitebench-aspca-pet-insurance}"
export WEBSITEBENCH_DATA_DIR

HERE="${BASH_SOURCE[0]%/*}"
case "$HERE" in
  /*) ;;
  *) HERE="$PWD/$HERE" ;;
esac

# The vendored backend resolves its runtime contract and database explicitly
# so no state ever lands inside the candidate tree.
export WEBSITEBENCH_SITE_BACKEND_RUNTIME="${WEBSITEBENCH_SITE_BACKEND_RUNTIME:-$HERE/site-config/runtime.json}"
export WEBSITEBENCH_SITE_BACKEND_DATABASE="${WEBSITEBENCH_SITE_BACKEND_DATABASE:-$WEBSITEBENCH_DATA_DIR/aspca-pet-insurance.sqlite3}"

# The evaluator creates WEBSITEBENCH_DATA_DIR before entering the seccomp
# sandbox. Candidate entrypoints cannot fork there, so use only shell builtins
# before replacing this process with the vendored ASGI runtime.
export PYTHONPATH="$HERE/vendor${PYTHONPATH:+:$PYTHONPATH}"

cd "$HERE"
exec python3 -m uvicorn app:app --host 0.0.0.0 --port "$PORT"
