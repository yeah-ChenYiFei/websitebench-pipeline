# Compile site profiles through versioned capability packs

Status: superseded by ADR 0005 (historical only)

## Context

The final WebsiteBench inventory contains 300 platforms across 53 original fine-grained categories. Those labels remain provenance only; eight coarser batch families are an inventory partition. Copying one-off scripts, backend notes, or frontend templates per site would repeat code while allowing authentication, ownership, persistence, negative paths, and evidence meaning to drift. Treating either classification layer as source truth would overclaim routes, entities, actors, and state transitions that the workbook does not observe.

## Decision

Normalize the workbook into a hash-bound Platform Inventory and give every platform one declarative Site Profile. Compose each profile through one primary archetype pack, zero or more cross-cutting overlay packs, and the mandatory `common-stateful-core` pack. The common pack reuses the Amazon-proven registration, sign-in, session, recovery, mail, database-lifecycle, and site-isolation semantics; it never shares permanent account data between sites.

`websitebench-site` is the only profile compiler. It produces an immutable Site IR, a complete frontend/backend plan, a content-addressed artifact DAG, a Profile Lock, and an explanation of provenance, blockers, and human-inspection invalidation. Inventory labels and pack selection remain `inferred` until a named human confirms the scope. Generated facts cannot count as source-direct evidence or approve fidelity.

Overrides are stable-ID typed operations at pack-declared extension points and require the exact base hash plus a rationale. Arbitrary recursive merge and unguarded JSON Patch are rejected. Changes to inventory, profile, packs, frontend artifacts, backend/reset semantics, or exact runtime packaging invalidate the corresponding scope, visual, semantic, runtime, and release evidence.

## Consequences

Batch work can load the inventory and pack registry once and reuse content hashes. All 300 profiles can be checked before any clone directory is materialized, while invalid source URLs and ambiguous multi-surface products remain explicit questions for the human supervisor instead of guessed inputs.

The compiler plans complete clones but does not bypass source capture, assets, implementation, Harbor evidence, rights review, or named-human fidelity acceptance. Site-specific evidence and typed overrides remain necessary, and a pack change can intentionally invalidate many downstream sites.
