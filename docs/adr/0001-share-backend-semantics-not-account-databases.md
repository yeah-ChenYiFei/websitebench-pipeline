# Share backend semantics, not permanent account databases

The eight clones reuse one machine contract and reusable implementation for registration, sign-in, sessions, password recovery, mail delivery, ownership, idempotency, and persistence, but each clone keeps its own permanent account and business database. A shared permanent account store would reduce duplicate code but would couple privacy, deletion, reset, migration, Harbor isolation, and site-specific business identities; site-isolated databases preserve those boundaries while still allowing Amazon-proven semantics to be reused.

This decision is now enforced by `websitebench.site_backend`: every SQLite file
contains exactly one `websitebench_site_binding(site_id)`, and open, restore and
embedded reset operations fail closed when the declared site does not match.
`LocalAuthStore` accepts the same `site_id` and verifies the binding before
creating or reading account tables. A user registered on one site therefore
has no account on another site even when the email address is identical.

Frozen ClawBench runtimes retain `clawbench_site_binding` only behind the
explicit compatibility boundary in ADR 0004. Canonical and legacy open paths
reject the other binding namespace, so one SQLite file cannot acquire both
identities.

Session cookies use a site-derived `__Host-` name and remain Host-only,
Secure, HttpOnly and SameSite. Shared Redis infrastructure is limited to
global abuse budgets; challenges, attempts, locks and verified tickets are
namespaced under `site/<site_id>`. Provider credentials and permanent account
records are never shared through that namespace.

The versioned implementation contract and deployment consequences are recorded
in [ADR 0003](0003-site-backend-runtime-and-safe-effects.md).
