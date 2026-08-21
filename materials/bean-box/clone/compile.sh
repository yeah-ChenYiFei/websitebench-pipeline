#!/usr/bin/env bash
set -Eeuo pipefail

cat > executable <<'EXECUTABLE'
#!/usr/bin/env bash
set -Eeuo pipefail
: "${HOST:?HOST is required}"
: "${PORT:?PORT is required}"
: "${DATA_DIR:?DATA_DIR is required}"
: "${SEED:?SEED is required}"
: "${TZ:?TZ is required}"

APP_ROOT="$PWD"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONHASHSEED="$SEED"
export PYTHONPATH="$APP_ROOT/vendor:$APP_ROOT${PYTHONPATH:+:$PYTHONPATH}"
export WEBSITEBENCH_DATA_DIR="$DATA_DIR"
export WEBSITEBENCH_SITE_BACKEND_RUNTIME="$APP_ROOT/backend/runtime.json"
export WEBSITEBENCH_USE_SANDBOX_RUNTIME_MIRROR=1
export WEBSITEBENCH_SITE_BACKEND_DATABASE="$DATA_DIR/bean-box.sqlite3"
exec "${PYTHON:-python3}" -m uvicorn app:app --host "$HOST" --port "$PORT"
EXECUTABLE

chmod 755 executable
