<!-- Phases 7–8: candidate implementation and backend -->

> This file is a phase reference for `prompts/offline-clone/autonomous-source-to-clone.md`.
> **The operating rules in the entry prompt—authorization, autonomous decision boundaries, stopping rules, parallelism, and context—take precedence over this file.**
> Previous: `04-scope-and-visual.md` | Next: `06-ledger-harbor.md`

## Phase 7: candidate implementation

Implement strictly according to the current lifecycle-gate order:

```text
source → assets → frontend → backend → verification
```

Replicate every frozen P0/P1 frontend state item by item:

- page geometry, grid, module order, spacing, alignment, density, scrolling,
  and responsive breakpoints;
- font files, size, weight, line height, letter spacing, wrapping, and all
  visible copy;
- colors, icons, logos, image crops, borders, radii, shadows, opacity, and
  stacking;
- sticky/fixed elements and complete page height;
- hover, focus, pressed, selected, disabled, and loading states;
- dropdowns, dialogs, drawers, tooltips, toasts, and date controls;
- empty, zero-result, validation, permission, service-error, and success states;
- animation, transitions, feedback order, keyboard behavior, outside-click
  dismissal, and focus restoration;
- URL/history, deep links, Back/Forward, refresh, and scroll restoration; and
- field order, defaults, validation timing, error placement/copy, permissions,
  persistence, idempotency, concurrency, and cancellation/recovery.

Every state-changing P0/P1 control must perform real local business behavior.
When P2 cannot be fully modeled, use only a registered
`truthful-simulation`; never emit a false success or misleading receipt.

Data reduction may reduce only the number of entities. For a frozen page
family, do not reduce functional entry points, fields, content density,
pagination, success/failure/empty/loading/permission states, or visual
expression.

After every change, run narrow tests first and then the shared diagnostics:

```bash
python tools/offline_clone/run.py tools explore ...
python tools/offline_clone/run.py tools compare-functional ...
python tools/offline_clone/run.py tools compare-visual ...
python tools/offline_clone/run.py tools test-backend ...
```

These tools have diagnostic authority only and cannot independently satisfy a
lifecycle gate.

## Phase 8: backend, email, uploads, and payments

First record whether each of these capabilities applies within scope:

- persistent authentication;
- password recovery;
- transactional/business email;
- uploads;
- checkout/payment; and
- a business database.

If any apply, run the following after recording the capability scope:

```bash
websitebench-offline-clone backend scaffold --site materials/<site-id>
```

`backend/runtime.json` is the only runtime contract. Use the generated
`websitebench.site_backend` integration seam. Do not create a custom auth,
email, payment, or database runtime that bypasses it, and do not infer this
site's business schema from another site or a capability pack.

Guarantee:

- unique site ID, SQLite database, backup, volume, cookie, Redis namespace,
  mail branding, and deployment identity;
- `site.public_origin=https://<site-id>.website-bench.com`;
- site-specific persistent SQLite, local outbox, and `local-sandbox` for
  `offline-harbor`;
- `ephemeral-reset` for `cloudflare-review`, disclosed accurately;
- a site-specific named volume for `docker-volume`;
- secrets sourced only from environment variables, GitHub Secrets, or
  controlled temporary injection; and
- fail-closed behavior across users, sites, databases/backups, volumes,
  sessions, Redis namespaces, and payment flows.

Payments default to `local-sandbox`, covering approved, declined, and retryable
outcomes. Enable `stripe-test` only when payment is explicitly in frozen scope,
the user has explicitly authorized a test payment, and this command passes:

```bash
websitebench-workflow check-payment-scope \
  --proposal materials/<site-id>/scope/payment-scope.json
```

Live payments, live keys, and real card data are prohibited. Real delivery
through Resend also requires a specific test recipient and separate
authorization; otherwise use the local outbox. Model inbound email import and
outbound email separately.

Verify identity, ownership, authorization, transitions, validation,
idempotency, concurrency, migration, backup/restore, restart, and deterministic
reset.
