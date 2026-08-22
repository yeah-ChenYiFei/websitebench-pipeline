#!/usr/bin/env bash
set -Eeuo pipefail
exec "${PYTHON_BIN:-python3}" server.py
