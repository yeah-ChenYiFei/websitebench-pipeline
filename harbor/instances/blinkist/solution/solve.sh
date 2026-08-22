#!/usr/bin/env bash
set -Eeuo pipefail
: "${WEBSITEBENCH_CANDIDATE_ROOT:?required}"
cat > "$WEBSITEBENCH_CANDIDATE_ROOT/compile.sh" <<'SH'
#!/usr/bin/env bash
set -Eeuo pipefail
cat > executable <<'EXE'
#!/usr/bin/env bash
echo 'oracle server is not implemented' >&2
exit 2
EXE
chmod 755 executable
SH
chmod 755 "$WEBSITEBENCH_CANDIDATE_ROOT/compile.sh"
echo 'oracle solution is not implemented' >&2
exit 2
