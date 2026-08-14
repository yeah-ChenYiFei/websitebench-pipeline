#!/usr/bin/env bash
# Trusted Harbor v2 runner/finalizer wrapper. All scoring logic lives in the
# generic Python runner and receipt finalizer.
set -Eeuo pipefail

PRIVATE_RUN=/run/websitebench-harbor-run
PUBLIC_RUN=/logs/verifier

install -d -m 700 -o root -g root "$PRIVATE_RUN"
find "$PRIVATE_RUN" -mindepth 1 -delete
install -d -m 755 -o root -g root "$PUBLIC_RUN"
find "$PUBLIC_RUN" -mindepth 1 -delete

# The trusted main interpreter has no model SDK. Provider/cloud/source
# credentials are removed before it starts; candidate and Browser Use receive
# stricter allowlisted environments in the runner itself.
while IFS='=' read -r name _value; do
  case "$name" in
    *API_KEY|*ACCESS_KEY*|*AUTH_TOKEN*|*BEARER_TOKEN*|*CREDENTIAL*|*PASSWORD*|*PRIVATE_KEY*|*SECRET*|*SESSION_TOKEN*|*_TOKEN|WEBSITEBENCH_REFERENCE_*)
      unset "$name"
      ;;
  esac
done < <(env)

cleanup_candidates() {
  pkill -KILL -f '/tests/websitebench/harbor/sandbox_v2.py .*--root /app/repo' 2>/dev/null || true
  pkill -KILL -f '/private/build/executable' 2>/dev/null || true
}
trap cleanup_candidates EXIT
cleanup_candidates

set +e
timeout -k 15 7200 python3 /tests/run_v2.py \
  --contract /tests/evaluation-contract.json \
  --candidate /app/repo \
  --output "$PRIVATE_RUN" \
  > /run/websitebench-harbor-driver.log 2>&1
RUNNER_STATUS=$?
set -e
cleanup_candidates

set +e
python3 - "$PRIVATE_RUN" "$PUBLIC_RUN" <<'PY'
import sys
from websitebench.harbor.finalizer_v2 import finalize_run
raise SystemExit(finalize_run(sys.argv[1], sys.argv[2]))
PY
FINALIZER_STATUS=$?
set -e

if [ "$RUNNER_STATUS" -ne 0 ] || [ "$FINALIZER_STATUS" -ne 0 ]; then
  exit 2
fi
echo "reward=$(cat "$PUBLIC_RUN/reward.txt")"
