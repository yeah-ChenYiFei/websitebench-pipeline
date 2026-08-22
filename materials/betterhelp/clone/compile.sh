#!/usr/bin/env bash
set -euo pipefail

if (($# != 0)); then
  printf 'compile.sh takes no arguments\n' >&2
  exit 64
fi

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
TARGET="$ROOT/executable"

# Harbor compiles the candidate once and then freezes the build tree.  Keep
# the generated launcher small and make the runtime's only writable location
# explicit through the deployment ABI.
umask 022
cat > "$TARGET" <<'RUNTIME'
#!/usr/bin/env bash
set -euo pipefail

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
: "${HOST:=127.0.0.1}"
: "${PORT:=3000}"
: "${DATA_DIR:?DATA_DIR is required}"
: "${SEED:=0}"
: "${TZ:=UTC}"

mkdir -p "$DATA_DIR"
export HOST PORT DATA_DIR SEED TZ
export WEBSITEBENCH_SITE_BACKEND_DATABASE="$DATA_DIR/betterhelp.sqlite3"
export WEBSITEBENCH_SITE_BACKEND_RUNTIME="$ROOT/backend/runtime.json"
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
exec python3 "$ROOT/app.py"
RUNTIME
chmod 755 "$TARGET"
