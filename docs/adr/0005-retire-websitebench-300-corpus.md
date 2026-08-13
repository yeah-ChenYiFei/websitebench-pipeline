# Retire the WebsiteBench-300 corpus and release gates

Status: accepted

Date: 2026-08-09

## Context

WebsiteBench-300 coupled a fixed workbook and 300 profiles to generated site
plans, an eight-lane dispatcher, workflow state, behavior-analysis aggregates,
rights records, and per-site plus corpus release gates. Those fixed
denominators made otherwise reusable compiler and trace tooling depend on a
single active corpus.

Repository policy separately requires the four records in
`websitebench/corpora/websitebench-300/inventory-migrations/2026-07-29-clawbench-160/`
to retain their exact historical ClawBench identity. Copying, renaming,
normalizing, regenerating, or treating those records as current evidence would
break that identity.

## Decision

Retire the active WebsiteBench-300 corpus without creating an archive copy.
Delete its workbook, inventory, taxonomy, profiles, compiled output, workflow
database/dispatch/receipts, analysis output, dedicated schemas, scheduling
commands, and all 301 release gates. The four historical migration files stay
at their existing paths and retain their bytes and hashes; a retirement note
makes clear that they are not active inputs or release evidence.

Keep `websitebench-site check`, `compile`, `explain`, and `materialize` on a
generic Platform Inventory v2 contract. Inventory IDs are positive but need not
be contiguous or bounded by 300. Source references, capability classifications,
declared counts, duplicate platform keys, and invalid source URL counts remain
machine-validated.

Keep WebCloning trace normalization, safe selection/import, exploration,
replay, behavior diff, and validation. Retire fixed membership and aggregate
summary builders. Existing historical compatibility entrypoints may parse or
import immutable records only where the repository compatibility boundary
already permits it.

## Consequences

Each maintained site and Harbor instance retains its own verification contract;
none is promoted by this retirement. Generic compiler behavior is covered by a
two-site hermetic fixture rather than repository corpus data. Deleted schemas,
profiles, and corpus resources are no longer bundled into the Python wheel or
viewer schema package.

Dated evidence, historical trajectories and hashes, already-vendored
compatibility runtimes, maintained offline clones, account/payment safety
contracts, and public deployment configuration are unchanged. This decision
does not authorize or trigger deployment.
