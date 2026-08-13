#!/usr/bin/env bash
# Trusted Harbor v2 deterministic verifier entry point.
set -Eeuo pipefail

PRIVATE_LOG=/run/verifier-final
PUBLIC_LOG=/logs/verifier

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
  python3 - "$PRIVATE_LOG/verdict.json" "$reason" <<'PY'
import json
import sys
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps({
    "schema_version": "websitebench.harbor.verdict.v2",
    "status": "INVALID_RUN",
    "valid": False,
    "reason": sys.argv[2],
}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
  publish_logs
}

trap 'code=$?; if [ "$code" -ne 0 ]; then write_invalid "VERIFIER_CRASH:$code"; fi' EXIT

# Never inherit model credentials into the deterministic verifier runtime.
SENSITIVE_CREDENTIAL_NAMES=(
  "OPEN""AI_API_KEY"
  "AZURE_""OPEN""AI_API_KEY"
  "ANTH""ROPIC_API_KEY"
  "GEM""INI_API_KEY"
  "GOOGLE""_API_KEY"
  "GOOGLE""_APPLICATION_CREDENTIALS"
  "COH""ERE_API_KEY"
  "GROQ_API_KEY"
  "OPENROUTER_API_KEY"
  "XAI_API_KEY"
  "DEEPSEEK_API_KEY"
  "TOGETHER_API_KEY"
  "REPLICATE_API_TOKEN"
  "MIST""RAL_API_KEY"
  "HUGGING""FACE_TOKEN"
  "AWS_BED""ROCK_API_KEY"
  "AWS_BEARER_TOKEN_BEDROCK"
  "AWS_""ACCESS_KEY_ID"
  "AWS_""SECRET_ACCESS_KEY"
  "AWS_""SESSION_TOKEN"
  "VERTEX""_AI_CREDENTIALS"
  "WEBSITEBENCH_REFERENCE_RESET_CREDENTIAL"
  "WEBSITEBENCH_REFERENCE_RESET_URL"
  "WEBSITEBENCH_REFERENCE_STORAGE_STATE"
  "WEBSITEBENCH_REFERENCE_URL"
  "WEBSITEBENCH_REFERENCE_ALLOWED_ORIGINS"
)
unset "${SENSITIVE_CREDENTIAL_NAMES[@]}"
# Keep only the one explicitly contracted trusted-observer credential. This
# also strips future provider/CI secrets whose names were not known when this
# image was built.
while IFS= read -r environment_name; do
  case "$environment_name" in
    WEBSITEBENCH_MAILBOX_CREDENTIAL) ;;
    *API_KEY*|*ACCESS_KEY*|*AUTH_TOKEN*|*BEARER_TOKEN*|*CREDENTIAL*|*PASSWORD*|*PRIVATE_KEY*|*SECRET*|*_TOKEN)
      unset "$environment_name"
      ;;
  esac
done < <(compgen -e)
python3 - "$PRIVATE_LOG/judge-runtime-evidence.json" <<'PY'
import importlib.util
import json
import os
import re
import sys
from pathlib import Path

from websitebench.harbor.judge_v2 import verifier_network_policy_enforced
from websitebench.harbor.sandbox_v2 import sandbox_preflight

dependencies = Path("/tests/judge-image-dependencies.txt")
declared_dependencies = json.loads(
    Path("/tests/judge-dependencies.json").read_text(encoding="utf-8")
)
network_path = Path("/tests/network-policy.json")
network = json.loads(network_path.read_text(encoding="utf-8"))
sandbox = sandbox_preflight()
credential_names = [
    "OPEN" + "AI_API_KEY",
    "AZURE_" + "OPEN" + "AI_API_KEY",
    "ANTH" + "ROPIC_API_KEY",
    "GEM" + "INI_API_KEY",
    "GOOGLE" + "_API_KEY",
    "GOOGLE" + "_APPLICATION_CREDENTIALS",
    "COH" + "ERE_API_KEY",
    "GROQ_API_KEY",
    "OPENROUTER_API_KEY",
    "XAI_API_KEY",
    "DEEPSEEK_API_KEY",
    "TOGETHER_API_KEY",
    "REPLICATE_API_TOKEN",
    "MIST" + "RAL_API_KEY",
    "HUGGING" + "FACE_TOKEN",
    "AWS_" + "BEDROCK_API_KEY",
    "AWS_" + "ACCESS_KEY_ID",
    "AWS_" + "SECRET_ACCESS_KEY",
    "AWS_" + "SESSION_TOKEN",
    "AWS_BEARER_TOKEN_BEDROCK",
    "VERTEX" + "_AI_CREDENTIALS",
]
modules = [
    "open" + "ai",
    "anth" + "ropic",
    "boto" + "3",
    "coh" + "ere",
    "google.gen" + "ai",
    "lit" + "ellm",
    "mistral" + "ai",
    "olla" + "ma",
    "sentence_" + "transformers",
    "transform" + "ers",
    "v" + "llm",
]
credential_name_pattern = re.compile(
    r"(?:API_KEY|ACCESS_KEY|AUTH_TOKEN|BEARER_TOKEN|CREDENTIAL|PASSWORD|PRIVATE_KEY|SECRET|_TOKEN)$"
)
unexpected_credential_names = sorted(
    name
    for name, value in os.environ.items()
    if value
    and name != "WEBSITEBENCH_MAILBOX_CREDENTIAL"
    and credential_name_pattern.search(name)
)
credential_present = any(os.environ.get(name) for name in credential_names) or bool(
    unexpected_credential_names
)
def normalized_requirement(value):
    name, separator, version = value.partition("==")
    return (name.lower().replace("_", "-"), version) if separator else None
expected_dependencies = {
    normalized_requirement(value)
    for value in declared_dependencies["runtime"]
    if not value.startswith("python==")
}
actual_dependencies = {
    normalized_requirement(line.strip())
    for line in dependencies.read_text(encoding="utf-8").splitlines()
    if line.strip()
}
dependency_set_matches = actual_dependencies == expected_dependencies
def module_present(name):
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ModuleNotFoundError):
        return False
runtime_present = any(module_present(name) for name in modules)
def default_route_present():
    try:
        for line in Path("/proc/net/route").read_text(encoding="utf-8").splitlines()[1:]:
            fields = line.split()
            if len(fields) >= 4 and fields[1] == "00000000" and int(fields[3], 16) & 1:
                return True
        for line in Path("/proc/net/ipv6_route").read_text(encoding="utf-8").splitlines():
            fields = line.split()
            if len(fields) >= 10 and fields[0] == "0" * 32 and fields[1] == "00":
                return True
    except (OSError, ValueError):
        return True
    return False
runtime_default_route = default_route_present()
platform_network_attested = os.environ.get(
    "WEBSITEBENCH_NETWORK_POLICY_ENFORCED", ""
) == "1"
runtime_network_enforced = verifier_network_policy_enforced(
    network,
    default_route_present=runtime_default_route,
    platform_attested=platform_network_attested,
)
payload = {
    "schema_version": "websitebench.harbor.judge-runtime-evidence.v1",
    "dependency_set_matches_contract": dependency_set_matches,
    "browser_profile": "playwright-1.61.0/chromium/websitebench-linux-fonts-v1",
    "sandbox": sandbox,
    "model_credentials_present": credential_present,
    "unexpected_credential_names": unexpected_credential_names,
    "model_runtime_present": runtime_present,
    "runtime_default_route_present": runtime_default_route,
    "platform_network_policy_attested": platform_network_attested,
    "network_policy_enforced": runtime_network_enforced,
    "model_request_capable": credential_present or runtime_present or not runtime_network_enforced,
}
Path(sys.argv[1]).write_text(
    json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
if credential_present or runtime_present or not runtime_network_enforced or not dependency_set_matches:
    raise SystemExit(1)
PY
unset SENSITIVE_CREDENTIAL_NAMES

if [ ! -d /app/repo ]; then
  write_invalid "CANDIDATE_ARTIFACT_MISSING"
  exit 1
fi

# Candidate code is immutable. The kernel sandbox grants each opaque worker UID
# access only to its own WEBSITEBENCH_DATA_DIR and declared loopback ports.
chown -R root:root /app/repo
chmod -R a-w,u+rwX,go+rX /app/repo

cleanup_candidates() {
  pkill -KILL -x strace 2>/dev/null || true
  pkill -KILL -f '/websitebench/harbor/sandbox_v2.py .*--root /app/repo' \
    2>/dev/null || true
  python3 - <<'PY'
import os
from pathlib import Path
for status in Path("/proc").glob("[0-9]*/status"):
    try:
        pid = int(status.parent.name)
        uid_line = next(
            line for line in status.read_text(encoding="utf-8").splitlines()
            if line.startswith("Uid:")
        )
        uid = int(uid_line.split()[1])
        if 20000 <= uid <= 65535:
            os.kill(pid, 9)
    except (OSError, StopIteration, ValueError):
        pass
PY
}

cleanup_candidates

set +e
timeout -k 15 3600 python3 /tests/run_v2.py \
  --contract /tests/evaluation-contract.json \
  --candidate /app/repo \
  --output "$PRIVATE_LOG" \
  > "$PRIVATE_LOG/verifier.log" 2>&1
STATUS=$?
set -e
cleanup_candidates
if ! python3 -c 'from websitebench.harbor.mailbox import redact_log_file; redact_log_file("/run/verifier-final/verifier.log")'; then
  STATUS=90
fi

if [ "$STATUS" -ne 0 ]; then
  write_invalid "VERIFIER_CRASH:$STATUS"
  exit 1
fi

test -s "$PRIVATE_LOG/task-results.json"
test -s "$PRIVATE_LOG/visual-results.json"
test -s "$PRIVATE_LOG/cicd-results.json"
test -s "$PRIVATE_LOG/scorecard.json"
test -s "$PRIVATE_LOG/reward.txt"
publish_logs
echo "reward=$(cat "$PRIVATE_LOG/reward.txt")"
