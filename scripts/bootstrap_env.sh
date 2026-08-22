#!/usr/bin/env bash
set -Eeuo pipefail

# Recreate the repository environment after a branch switch or a removed venv.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${REPO_ROOT}/.venv"
UV_BIN="${UV_BIN:-$(command -v uv || true)}"
if [[ -z "${UV_BIN}" && -x "${HOME}/.local/bin/uv" ]]; then
  UV_BIN="${HOME}/.local/bin/uv"
fi

if [[ -n "${UV_BIN}" ]]; then
  "${UV_BIN}" venv "${VENV_DIR}" --clear --python "${PYTHON_VERSION:-3.12}"
  "${UV_BIN}" pip install --python "${VENV_DIR}/bin/python" -e "${REPO_ROOT}[dev]"
  exit 0
fi

PYTHON_BIN="${PYTHON_BIN:-$(command -v python3 || command -v python || true)}"
if [[ -z "${PYTHON_BIN}" ]]; then
  echo "error: Python 3.11+ is required; install Python or uv first" >&2
  exit 1
fi

rm -rf "${VENV_DIR}"
if ! "${PYTHON_BIN}" -m venv "${VENV_DIR}"; then
  echo "error: unable to create ${VENV_DIR}; install python3-venv (Debian/Ubuntu) or install uv" >&2
  exit 1
fi
"${VENV_DIR}/bin/python" -m pip install --upgrade pip
"${VENV_DIR}/bin/python" -m pip install -e "${REPO_ROOT}[dev]"
