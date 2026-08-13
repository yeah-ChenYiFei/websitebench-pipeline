# Site backend runtime contract and safe effects

Status: superseded in part by payment scope v2 and authorization-free deployment (historical only)  
Date: 2026-08-01

## Decision

Each migrated offline clone declares one versioned `backend/runtime.json`.
`websitebench.site_backend` is the shared implementation behind that contract.
Deployment descriptors reference the contract and must not restate database,
mail or payment semantics.

The module exposes a small boundary:

- `SiteBackend.open(config)`;
- `lifecycle.initialize/reset/backup/restore/health`;
- `mail.issue/enqueue`;
- `payments.create_intent/attempt/attempt_verified_stripe/consume_approval`.

Site migration and seed logic remain site-owned hooks. Capability packs do not
infer a site's business schema.

## Database and identity

Code and state-machine semantics are shared, but permanent SQLite databases
and volumes are not. A single-row site binding makes wrong-site database open,
restore and mounting fail closed. `consume_approval` participates in the
caller's existing SQLite transaction so payment approval consumption and the
site's subsequent order snapshot commit atomically. Consumers must call it
before any business mutation. A final-fact mismatch commits the terminal
invalidation before releasing SQLite's write lock, restores an empty caller
transaction and then rejects. This avoids both partial-order commits and a
rollback/restart interval in which another connection could consume the old
approval.

## Mail

Sites may share one verified sending domain/address, but each runtime contract
must provide distinct sender display name and structured subject, lead, expiry
and footer copy. The component escapes those plain-text values and renders
both text and HTML. Arbitrary caller HTML is not an interface.

Verification OTPs are kept in process memory only long enough to deliver and
are persisted only as salt/hash. A restart cannot replay an unsent OTP body,
but a code already delivered to the user remains verifiable from its hash.
Migration invalidates any legacy cleartext pending OTP and requires reissue.
Business outbox rows retain a
template identifier and server variable snapshot, not rendered bodies,
provider secrets or raw provider errors.

The optional business-mail effects client may submit only a claimed
non-secret `{purpose, template_id, recipient, variables}` envelope to the
site-local Resend route. The effects gateway owns the provider credential,
revalidates the frozen runtime template and renders escaped text/HTML itself.
It rejects arbitrary rendered content and all secret-bearing OTP purposes.
Delivery occurs only after the caller's business transaction commits; a
sanitized retry state must not turn a confirmed order or enrollment into a
failed payment.

## Payment

`local-sandbox` is the default deterministic adapter. `stripe-test` is an
optional external test seam and rejects live keys. Both use integer minor
units, currency, owner, canonical fingerprint, idempotency keys, immutable
events and `is_simulation=true`. The API accepts opaque scenarios; it never
accepts card number, CVV, expiry or bank credentials.

Stripe return host/path, currency, line-item limits and site metadata are
frozen in the runtime contract. Each site has its own webhook secret. Final
commit rereads the provider Session and revalidates site, owner, amount,
currency and fingerprint in the site transaction. An opaque Session ID cannot
be submitted to ordinary `attempt()` as proof of approval. Stripe flows use a
separate provider-verified interface whose server-only callable retrieves or
authenticates the Session before the common module independently rechecks its
immutable facts.

## Deployment

- `offline-harbor`: persistent site SQLite, local outbox and local sandbox.
- `cloudflare-review`: explicitly ephemeral/resettable SQLite, effects gateway
  mail and optional Stripe test.
- `docker-volume`: one site-specific app, named persistent volume and private
  site network; only the effects gateway joins a second egress network.
  Provider-effect Host routes require a separate site-specific internal token.

Real external deployment remains dry-run by default. It requires an exact
digest-bound, short-lived named-human authorization and a passing scoped
project release check. Deployment cannot approve fidelity, rights, Harbor or
publication.

Node deployment tooling invokes the Python runtime validator as the sole
authority for v2 contracts. Normal container preflight never authorizes an
unbound legacy database; legacy adoption is a separate, explicit,
site-provenance-checking operation. An already correctly bound old site may
defer integrity until its site-owned repair migration runs, but the
`prepare_bound_site_migration` seam rejects missing and foreign bindings and
requires final `health` before traffic.

## Consequences

Amazon is the first migrated site. Its page routes, cart fields and business
entities remain outside the common interface. edX now has a code-level
additive payment overlay and Stripe-test deployment descriptor, including
post-commit enrollment receipts through the restricted business-mail path.
That candidate remains inactive until a named human accepts the exact current
hash-bound payment scope, the profile explicitly selects the payment overlay,
and separate deployment/release gates authorize an external effect.
