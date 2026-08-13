# ADR 0004: WebsiteBench is canonical; ClawBench is an explicit compatibility source

## Status

Superseded in part by machine-verification v3 contracts; retained as historical
canonical-naming context only.

## Context

This repository builds WebsiteBench. ClawBench is an upstream/reference
codebase whose useful implementation and historical corpus data are being
migrated here. Treating both names as interchangeable created mixed runtime
trees, mismatched effects headers and, most seriously, allowed two binding
table namespaces to coexist in one SQLite file.

## Decision

The canonical names for new work are:

| Interface fact | Canonical value |
| --- | --- |
| Python namespace | `websitebench.*` |
| CLI prefix | `websitebench-*` |
| runtime schema | `websitebench.site-backend-runtime.v1` |
| vendor root | `clone/websitebench/` |
| environment prefix | `WEBSITEBENCH_` |
| gate attempt bindings | `WEBSITEBENCH_OFFLINE_CLONE_*` |
| trusted internal header prefix | `X-WebsiteBench-` |
| session cookie prefix | `__Host-websitebench-` |
| SQLite tables | `websitebench_*` |
| Compose/volume/network prefix | `websitebench-` |

All public modules now live physically below `src/websitebench/`.
`websitebench.__path__` does not expose `src/clawbench`; canonical imports
therefore cannot fall back to a legacy implementation implicitly.

Legacy ClawBench interfaces are adapters only:

- old `clawbench-*` entry points and physical modules remain for existing
  scripts;
- frozen Change and unmigrated vendored runtimes retain their existing
  package, table, cookie and schema identities;
- Amazon uses the canonical WebsiteBench runtime; its former ClawBench
  database is accepted only by a provenance-checked, copy-only migration that
  retains the exact legacy bytes beside the atomically installed canonical
  database;
- edX authentication, database, mail branding, environment variables, trusted
  admin header, cookie names and vendored runtimes use WebsiteBench names; its
  pre-binding SQLite file is accepted only by the edX provenance-checked
  copy-only migration, while its payment behavior remains behind the current
  named-human R1 scope gate;
- generic deployment v1 remains a ClawBench compatibility contract;
- generic v2 may invoke a legacy backend only through the explicit
  schema-selected launcher adapter;
- canonical and legacy database/auth runtimes scan both binding namespaces and
  reject the other namespace or any dual binding.
- migrated release/evidence producers prefer canonical
  `WEBSITEBENCH_OFFLINE_CLONE_*` attempt bindings, accept a complete
  legacy-only `CLAWBENCH_OFFLINE_CLONE_*` set for the old harness, and reject
  mixed or partial bindings.

There is no free fallback between namespaces. The only accepted fallbacks are
named in code and tested, such as legacy Viewer environment variables and the
schema-selected legacy container launcher. Any on-disk migration must be
copy-only, verify the source binding and canonical copy integrity, invalidate
old sessions, retain the original bytes, and never add a second binding table
to the original database.

## Preserved identities

Do not bulk rename ClawBench provenance, legal attribution, repository URLs,
schema versions already used by evidence, migration/gate IDs, source captures,
hash-bound evidence, or existing external Cloudflare Worker/D1/queue names.
Those strings describe an upstream source, an immutable artifact or an
external resource—not the current product interface. New schema versions and
new external resources use WebsiteBench names.

## Consequences

New agents and humans have one public interface to learn. Compatibility logic
is concentrated at runtime, launcher and vendor seams. Tests must exercise
WebsiteBench interfaces by default and keep a smaller, explicit compatibility
suite for legacy ClawBench behavior.
