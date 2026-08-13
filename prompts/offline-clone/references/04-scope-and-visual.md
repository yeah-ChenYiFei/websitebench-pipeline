<!-- Phases 5–6: scope freeze and visual contract -->

> This file is a phase reference for `prompts/offline-clone/autonomous-source-to-clone.md`.
> **The operating rules in the entry prompt—authorization, autonomous decision boundaries, stopping rules, parallelism, and context—take precedence over this file.**
> Previous: `03-human-handoff.md` | Next: `05-implement.md`

## Phase 5: site initialization and scope freeze

When `existing_site=false`, run the following after plan approval:

```bash
websitebench-offline-clone init \
  --site-dir materials/<site-id> \
  --site-id <site-id> \
  --display-name "<display-name>" \
  --source-url <canonical-source-url>
```

Inspect and complete:

- `materials/<site-id>/clone.yaml`
- `materials/<site-id>/scope/`
- `materials/<site-id>/source-current/`
- `materials/<site-id>/source-assets/`
- `materials/<site-id>/clone/`
- `materials/<site-id>/tools/`

You may consult an existing clone's manifest, gate, Browserbase client, and
deployment wiring, but do not copy another site's UI, business fields,
fixtures, visual thresholds, or site conclusions. Keep every incomplete
scaffold draft/fail-closed. Placeholder evidence must not make a manifest pass
early.

Classify every source-site conclusion as:

- `directly-observed`;
- `structural-only`;
- `inferred`; or
- `unavailable`.

Only `directly-observed` evidence supports claims of pixel or flow equivalence.
Help documentation may reveal functionality to investigate, but cannot prove a
page's appearance, interaction, or success semantics.

Freeze and version:

- purpose, invariants, routes, journeys, and coverage;
- the route × state × viewport × role × interaction matrix;
- P0/P1/P2/omit/unavailable classifications;
- the deterministic seed;
- approved origins and the source-mutation allowlist;
- data, asset, and external-service boundaries; and
- every claim's evidence grade and artifact references.

Rules:

- Propose representative journeys as P0 or P1 according to business
  criticality, direct evidence, and user impact if omitted. Never classify a
  journey as P0 merely because the Agent discovered it automatically.
- Necessary prerequisites, critical errors, recovery, and permission states for
  a P0 journey are usually at least P1, but reassess them against the actual
  journey.
- Observed but non-core functionality may be P2.
- Newly discovered functionality first becomes a scope delta; never expand
  scope silently.
- An unavailable P0/P1 item prevents strict verification from passing unless
  the user explicitly approves reclassification.
- Discover routes, redirects, queries, and history from live DOM, navigation,
  and network evidence; never guess them.

Use the configuration-driven entry point for anonymous GET-only baseline
capture:

```bash
websitebench-workflow acquire-source \
  --spec <source-acquisition-spec> \
  --out-dir <source-output-dir> \
  --report <source-report>
```

Use the Browserbase Live View/Playwright path described above for post-login and
interactive evidence. Retain only sanitized, PII-free runtime/context identity.

## Phase 6: visual contract and asset closure

Before viewing candidate comparison results, obtain at least three source
frames for every P0/P1 checkpoint and run:

```bash
websitebench-workflow calibrate-visual \
  --spec <visual-calibration-spec> \
  --out <visual-calibration-report>
```

Freeze:

- the source screenshots;
- Browserbase/Playwright runtime identity;
- viewport and comparison region;
- source-to-source variance;
- the metric and a strict, nonzero threshold;
- the smallest dynamic mask and its rationale; and
- role, prerequisite data state, and action sequence.

Capture pre-action, hover/focus, expanded, mid-fill, loading, disabled,
validation-failure, permission-failure, service-failure, success, refresh, and
Back/Forward states. Preserve full-page evidence plus header, main, action,
overlay, and footer regions. Record sanitized DOM, geometry, network, console,
and trace evidence.

When Browserbase cannot access local loopback, mark local comparisons only as
provisional. Do not claim source and candidate used the same cloud environment.
Rerun formal online comparisons with the same Browserbase configuration.

Localize every in-scope image, font, icon, stylesheet, script, and runtime
resource, recording provenance. Vendored copies stay byte-exact with their
source downloads, checked by path existence and byte counts:

```text
in_scope_required = downloaded = byte_verified = candidate_referenced
missing = byte_count_mismatch = forbidden_remote_runtime = 0
```
