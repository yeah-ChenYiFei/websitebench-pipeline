#!/usr/bin/env sh
set -eu

cat > executable <<'EOF'
#!/usr/bin/env sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
export PYTHONPATH="$ROOT/clone"
exec /usr/bin/python3 "$ROOT/clone/app.py"
EOF
chmod 755 executable
