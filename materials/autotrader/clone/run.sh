#!/bin/sh
set -eu
cd "$(dirname "$0")"
exec python -m uvicorn app:app --host "${HOST:-127.0.0.1}" --port "${PORT:-8767}"
