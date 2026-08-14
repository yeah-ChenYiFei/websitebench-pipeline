#!/usr/bin/env bash
# Oracle solve: install the private oracle site tree as the candidate repo.
# Calibration runs this with:
#   WEBSITEBENCH_BUNDLE_ROOT        materialized bundle root
#   WEBSITEBENCH_SOLUTION_SITE_ROOT bundle/solution/site (oracle payload)
#   WEBSITEBENCH_CANDIDATE_ROOT     candidate repo root to populate
set -Eeuo pipefail

: "${WEBSITEBENCH_SOLUTION_SITE_ROOT:?WEBSITEBENCH_SOLUTION_SITE_ROOT is required}"
: "${WEBSITEBENCH_CANDIDATE_ROOT:?WEBSITEBENCH_CANDIDATE_ROOT is required}"

SRC="$WEBSITEBENCH_SOLUTION_SITE_ROOT"
DST="$WEBSITEBENCH_CANDIDATE_ROOT"

[ -f "$SRC/deploy.sh" ] || { echo "oracle payload missing deploy.sh" >&2; exit 1; }

mkdir -p "$DST"
# Replace the seed contents with the oracle site tree (fresh, deterministic).
find "$DST" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
cp -a "$SRC/." "$DST/"
rm -f "$DST/README.md"
chmod 0755 "$DST/deploy.sh"

echo "oracle solution installed into $DST"
