#!/usr/bin/env bash
# Trusted, separate-environment verifier entry point.
#
# Site run.py launches fresh reference and candidate processes from
# /tests/reference and /app/repo, then sets the URL variables named in the
# runtime contract. Candidate failures must become failed CTRF nodes. A non-zero
# evaluator exit or malformed report is an INVALID verifier run, not score 0.
set -Eeuo pipefail

PRIVATE_LOG=/run/verifier-final
PUBLIC_LOG=/logs/verifier
VERDICT="$PRIVATE_LOG/verdict.json"

rm -rf -- "$PRIVATE_LOG"
install -d -m 700 -o root -g root "$PRIVATE_LOG"
install -d -m 700 -o 10001 -g 10001 /run/verifier-untrusted
install -d -m 755 -o root -g root "$PUBLIC_LOG"
find "$PUBLIC_LOG" -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +

publish_logs() {
  cp -a "$PRIVATE_LOG"/. "$PUBLIC_LOG"/
  chown -R root:root "$PUBLIC_LOG"
  chmod -R u+rwX,go+rX,go-w "$PUBLIC_LOG"
}

write_invalid() {
  local reason="$1"
  rm -f -- "$PRIVATE_LOG/reward.txt" "$PRIVATE_LOG/scorecard.json"
  python3 - "$VERDICT" "$reason" <<'PY'
import json
import os
import sys
import tempfile
from pathlib import Path

path = Path(sys.argv[1])
payload = {"schema_version": "websitebench.harbor.verdict.v1",
           "valid": False, "reason": sys.argv[2]}
fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
with os.fdopen(fd, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, indent=2, sort_keys=True)
    handle.write("\n")
    handle.flush()
    os.fsync(handle.fileno())
os.replace(temporary, path)
PY
  printf '%s\n' "$reason" > "$PRIVATE_LOG/crash.txt"
  publish_logs
}

trap 'code=$?; if [ "$code" -ne 0 ] && [ ! -f "$VERDICT" ]; then write_invalid "VERIFIER_CRASH:$code"; fi' EXIT

if [ ! -d /app/repo ]; then
  write_invalid "CANDIDATE_ARTIFACT_MISSING"
  exit 1
fi
chown -R root:root /app/repo
chmod -R u+rwX,go+rX,go-w /app/repo
pkill -KILL -u 10001 2>/dev/null || true

set +e
timeout -k 15 1050 python3 /tests/site/run.py \
  --contract /tests/runtime-contract.json \
  --required /tests/required-nodes.json \
  --output "$PRIVATE_LOG" \
  > "$PRIVATE_LOG/verifier.log" 2>&1
SITE_STATUS=$?
set -e
pkill -KILL -u 10001 2>/dev/null || true

if [ "$SITE_STATUS" -ne 0 ]; then
  write_invalid "SITE_VERIFIER_EXIT:$SITE_STATUS"
  exit 1
fi
if [ ! -s "$PRIVATE_LOG/ctrf.json" ]; then
  write_invalid "SITE_VERIFIER_NO_CTRF"
  exit 1
fi

mv -- "$PRIVATE_LOG/ctrf.json" "$PRIVATE_LOG/site-ctrf.json"
if [ -s /tests/platform-auth-checkout-policy.json ]; then
  set +e
  python3 /tests/platform_auth_checkout_gate.py \
    --policy /tests/platform-auth-checkout-policy.json \
    --required /tests/required-nodes.json \
    --site-report "$PRIVATE_LOG/site-ctrf.json" \
    --candidate-facts "$PRIVATE_LOG/candidate-facts.json" \
    --reference-facts "$PRIVATE_LOG/reference-facts.json" \
    --candidate-root /app/repo \
    --reference-root /tests/reference \
    --output "$PRIVATE_LOG/ctrf.json" \
    --evidence "$PRIVATE_LOG/platform-auth-checkout-evidence.json"
  PLATFORM_STATUS=$?
  set -e
  if [ "$PLATFORM_STATUS" -ne 0 ] || [ ! -s "$PRIVATE_LOG/ctrf.json" ]; then
    write_invalid "PLATFORM_AUTH_CHECKOUT_GATE_FAILED:$PLATFORM_STATUS"
    exit 1
  fi
else
  mv -- "$PRIVATE_LOG/site-ctrf.json" "$PRIVATE_LOG/ctrf.json"
fi

set +e
python3 /tests/compute_reward.py \
  "$PRIVATE_LOG/ctrf.json" \
  /tests/required-nodes.json \
  "$PRIVATE_LOG"
SCORE_STATUS=$?
set -e
if [ "$SCORE_STATUS" -ne 0 ]; then
  publish_logs
  exit 1
fi

publish_logs
echo "reward=$(cat "$PRIVATE_LOG/reward.txt")"
