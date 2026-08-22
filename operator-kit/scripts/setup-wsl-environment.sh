#!/usr/bin/env bash
set -euo pipefail

readonly REPO_DIR="/mnt/d/codework/websitebench-pipeline"
readonly NODE_VERSION="v24.18.1"
readonly NODE_ARCHIVE="node-${NODE_VERSION}-linux-x64.tar.xz"
readonly NODE_SHA256="d6c664df3f3f61458e8c277585571328522d705166723a7c7823a9253a4d15a0"
readonly UV_VERSION="0.11.7"
readonly UV_ARCHIVE="uv-x86_64-unknown-linux-gnu.tar.gz"
readonly UV_SHA256="6681d691eb7f9c00ac6a3af54252f7ab29ae72f0c8f95bdc7f9d1401c23ea868"

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "This setup must run inside WSL/Linux." >&2
  exit 2
fi

if [[ ! -f "${REPO_DIR}/pyproject.toml" ]] || [[ ! -f "${REPO_DIR}/AGENTS.md" ]]; then
  echo "WebsiteBench workspace was not found at ${REPO_DIR}." >&2
  exit 2
fi

if [[ "${WEBSITEBENCH_SKIP_APT:-0}" == "1" ]]; then
  for required_command in curl git gcc g++ make xz; do
    if ! command -v "${required_command}" >/dev/null; then
      echo "Required command is missing after skipping apt: ${required_command}" >&2
      exit 2
    fi
  done
else
  sudo apt-get update
  sudo apt-get install -y ca-certificates curl git build-essential xz-utils
fi

if [[ "$(uname -m)" != "x86_64" ]]; then
  echo "This installer is pinned for x86_64; refusing architecture $(uname -m)." >&2
  exit 2
fi

readonly LOCAL_BIN="${HOME}/.local/bin"
readonly LOCAL_OPT="${HOME}/.local/opt"
readonly NODE_PREFIX="${LOCAL_OPT}/node-${NODE_VERSION}-linux-x64"
mkdir -p "${LOCAL_BIN}" "${LOCAL_OPT}"

node_path="$(command -v node 2>/dev/null || true)"
npm_path="$(command -v npm 2>/dev/null || true)"
npx_path="$(command -v npx 2>/dev/null || true)"
if [[ -z "${node_path}" ]] || [[ "${node_path}" == /mnt/* ]] \
  || [[ -z "${npm_path}" ]] || [[ "${npm_path}" == /mnt/* ]] \
  || [[ -z "${npx_path}" ]] || [[ "${npx_path}" == /mnt/* ]] \
  || [[ "$(node --version)" != "${NODE_VERSION}" ]]; then
  node_download_dir="$(mktemp -d)"
  node_archive_path="${node_download_dir}/${NODE_ARCHIVE}"
  curl --proto '=https' --tlsv1.2 -fL \
    "https://nodejs.org/dist/${NODE_VERSION}/${NODE_ARCHIVE}" \
    -o "${node_archive_path}"
  printf '%s  %s\n' "${NODE_SHA256}" "${node_archive_path}" | sha256sum --check --status
  tar -xJf "${node_archive_path}" -C "${LOCAL_OPT}"
  ln -sfn "${NODE_PREFIX}/bin/node" "${LOCAL_BIN}/node"
  ln -sfn "${NODE_PREFIX}/bin/npm" "${LOCAL_BIN}/npm"
  ln -sfn "${NODE_PREFIX}/bin/npx" "${LOCAL_BIN}/npx"
  ln -sfn "${NODE_PREFIX}/bin/corepack" "${LOCAL_BIN}/corepack"
fi

uv_path="$(command -v uv 2>/dev/null || true)"
if [[ -z "${uv_path}" ]] || [[ "${uv_path}" == /mnt/* ]] || [[ "$(uv --version)" != "uv ${UV_VERSION}"* ]]; then
  uv_download_dir="$(mktemp -d)"
  uv_archive_path="${uv_download_dir}/${UV_ARCHIVE}"
  curl --proto '=https' --tlsv1.2 -fL \
    "https://releases.astral.sh/github/uv/releases/download/${UV_VERSION}/${UV_ARCHIVE}" \
    -o "${uv_archive_path}"
  printf '%s  %s\n' "${UV_SHA256}" "${uv_archive_path}" | sha256sum --check --status
  tar -xzf "${uv_archive_path}" -C "${uv_download_dir}"
  install -m 0755 "${uv_download_dir}/uv-x86_64-unknown-linux-gnu/uv" "${LOCAL_BIN}/uv"
  install -m 0755 "${uv_download_dir}/uv-x86_64-unknown-linux-gnu/uvx" "${LOCAL_BIN}/uvx"
fi

export PATH="${LOCAL_BIN}:${NODE_PREFIX}/bin:${PATH}"
export UV_LINK_MODE="${UV_LINK_MODE:-copy}"

[[ "$(node --version)" == "${NODE_VERSION}" ]]
command -v npm >/dev/null
command -v npx >/dev/null
npm --version >/dev/null
npx --version >/dev/null
[[ "$(uv --version)" == "uv ${UV_VERSION}"* ]]

cd "${REPO_DIR}"
git config --local core.longpaths true

uv python install 3.12
uv sync --python 3.12 --frozen --extra dev
. .venv/bin/activate
if [[ "${WEBSITEBENCH_SKIP_PLAYWRIGHT_DEPS:-0}" == "1" ]]; then
  python -m playwright install chromium
else
  python -m playwright install --with-deps chromium
fi

python tools/offline_clone/run.py tools list
python -m pytest tests/test_prompt_freshness.py -q
websitebench-offline-clone --help >/dev/null
websitebench-harbor --help >/dev/null
python -m pytest \
  tests/harbor/test_deterministic_v2.py::test_sandbox_preflight_records_required_kernel_features \
  -q

echo "WebsiteBench WSL environment preflight completed."
