<!-- Phase 10: machine verification and blind review -->

> This file is a phase reference for `prompts/offline-clone/autonomous-source-to-clone.md`.
> **The operating rules in the entry prompt—authorization, autonomous decision boundaries, stopping rules, parallelism, and context—take precedence over this file.**
> Previous: `06-ledger-harbor.md` (final phase reference)

## Phase 10: machine verification and blind review

Two diagnostic sections, one command:

```bash
websitebench-offline-clone verify --site materials/<site-id>
```

`static` starts no server or browser. It checks asset closure, runtime remote
references, credentials, and whether each checkpoint route resolves. `live`
starts the clone and visits every checkpoint in `scope/checkpoints.json`. It
asserts an HTTP 200 response, a title, no horizontal overflow, and no runtime
requests leaving the page. For a checkpoint with `visual_contract`, it also
performs a direct pixel comparison. The report schema is
`offline-clone.diagnostic-report.v1`, its authority is `diagnostic-only`, and
its only statuses are `clean | findings | incomplete`; every status requires
maintainer judgment.

To run only the fast section, use `--section static`.

One run produces one report. Complete execution, whether clean or findings,
exits `0`; invalid input or incomplete execution exits `2`. **There are no
tiers, attempts, or stored diagnostic state.**

Put site-specific knowledge in data at
`materials/<site-id>/scope/verify.json`, never in code:

| Field | Purpose |
| --- | --- |
| `routes` | Aliases when clone-service paths differ from source-site paths |
| `deferred` | Routes unreachable anonymously, recorded as coverage gaps rather than failures |
| `states` | How to reach a non-default state; an undeclared state increments `undeclared_states` |
| `status` | Expected value when a checkpoint records a non-200 source response |
| `prepare` | Preparation actions after each page loads, such as dismissing a cookie banner |

This file may be absent entirely; it is needed only for the five situations
listed above.

Complete verification covers at least:

- structural behavior;
- browser journeys;
- network closure;
- region-level visual comparison;
- backend semantics and actor/site isolation;
- migration, backup, restart, reset, idempotency, and concurrency;
- the full-stack candidate; and
- an independent blind audit.

The two diagnostic sections observe structure, network closure, region-level
visual comparison, and route reachability. Site-specific tests and maintainer
judgment cover the remaining dimensions, and the report must state the actual
extent of coverage honestly.

Reproducible evidence should identify the current candidate files, manifest,
source artifacts, browser, viewport, role, data state, and command.

Visual comparisons must decide region by region; a full-page average cannot
hide local differences. An independent audit must run in a new isolated context
that has not inspected candidate code or seen source/candidate labels. Randomize
A/B ordering and handle domains and preregistered dynamic values according to
the frozen rules. An audit that shares implementation history or labels has
diagnostic standing only and is not a formal independent audit.

The maintainer conclusion should consider the site's current manifest, declared
inputs, diagnostics, implementation, and scope. Do not delete findings, forge
evidence, modify an unrelated site, or rewrite incomplete as clean. Historical
project records may serve only as audit background.
