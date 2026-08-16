# Site 33 Safe Local Checkout Design

## Purpose and scope

Task 265 adds one authenticated, clone-local purchase journey for the Deep
Learning Specialization. The journey starts at the public specialization,
offers one inferred plan, displays a synthetic memory-only payment form,
reviews immutable totals, and records either a sandbox failure or an atomic
paid order and enrollment. It never contacts Coursera, a payment provider, or
any other remote origin.

The sole plan is explicitly labeled as inferred because authenticated source
checkout evidence is unavailable. Its server-owned facts are USD 49.00
subtotal, USD 0.00 tax, and USD 49.00 total. The only payment adapter is
`local-sandbox`, and its only scenarios are `sandbox-approved`,
`sandbox-declined`, and `sandbox-retry`.

## Architecture

`materials/33/clone/backend/checkout.py` is the checkout domain boundary. It
owns checkout and order schema, the frozen plan facts and canonical
fingerprint, draft creation, generated payment-flow calls, payment attempts,
approval consumption, order queries, paid-enrollment transitions, and checkout
reset/snapshot helpers.

`backend/learning_db.py` remains the owner of the site lifecycle. Its migrate,
reset, and state-snapshot functions delegate checkout table work to the new
module, and its enrollment schema remains the canonical learning record.
`app.py` supplies authenticated routes and server-rendered HTML only. It does
not issue SQL or call generated payment primitives directly.

This separation keeps the generated `SitePayments` transaction contract and
the business-state transaction visible in one focused module rather than
expanding the already large learning module or hiding transaction boundaries
in route handlers.

## Stored state and invariants

The checkout schema contains:

- Owner-bound checkout drafts with an opaque path ID, course/plan identity,
  amount, currency, canonical plan fingerprint, generated payment flow ID,
  status, and timestamps.
- Immutable paid order snapshots with an opaque order ID, owner, originating
  draft and payment flow, course/plan labels, subtotal/tax/total, currency,
  status, and timestamps.

The draft path ID is stored server-side and appears in the URL. Consequently,
the final attempt body needs no flow, owner, amount, currency, plan, or
fingerprint fields. A draft is readable and actionable only by its current
authenticated owner. Unknown and foreign IDs have the same not-found result.

The plan fingerprint is a frozen 64-character hexadecimal literal generated
once from the canonical server-owned plan facts with the repository-supported
canonical digest library. Runtime code compares against this literal; it does
not introduce new hashing or integrity infrastructure.

Draft creation validates the one supported course and plan, then creates the
draft and generated `local-sandbox` payment flow within a caller-owned site
SQLite transaction. A final attempt re-reads the draft and current plan and
revalidates owner, amount, currency, and fingerprint before calling the
generated runtime.

## Browser and route flow

1. The public Deep Learning specialization links authenticated users to the
   checkout plan page and sends anonymous users through local sign-in.
2. `GET /checkout/deep-learning` shows the one inferred USD 49.00 plan, the
   USD 0.00 tax and total, and a prominent offline-simulation warning.
3. `POST /checkout/deep-learning` creates an owner-bound draft and redirects
   to its synthetic payment page.
4. `GET /checkout/{draft_id}/payment` renders card-like number, expiry, and CVV
   controls without `name` attributes. They exist only in browser memory. The
   page visibly warns that no real payment data should be entered. Its form
   advances to review without submitting those controls.
5. `GET /checkout/{draft_id}/review` repeats the immutable inferred totals and
   offers exactly the three sandbox scenarios.
6. `POST /checkout/{draft_id}/attempt` accepts exactly
   `{scenario_id, idempotency_key}`. Any missing, duplicate, malformed, or
   additional key, including payment-looking fields, is rejected.
7. Approved attempts redirect to the owner-scoped order detail. Declined and
   retryable attempts create no order or enrollment and show a safe result
   with retry and back links.
8. `GET /orders` lists the authenticated owner's durable order history;
   `GET /orders/{order_id}` shows its immutable snapshot.
9. `POST /orders/{order_id}/cancel` atomically marks the order and associated
   paid enrollment canceled. History remains visible. Reopening links back to
   the collection/specialization so a fresh checkout can be started.

All pages provide a safe route back to the Deep Learning collection or the
owner's history. Existing free/audit enrollment behavior remains available,
but a paid transition can only be created by consuming a sandbox approval.

## Payment and transaction semantics

The generated `SitePayments` API is used without modification:

- `create_intent` is called with owner, 4900 minor units, `USD`, the frozen
  fingerprint, a server-generated idempotency key, and `local-sandbox`.
- `attempt` is called with the server-stored flow facts plus the submitted
  scenario and idempotency key.
- `consume_approval` is called only inside the same caller-owned SQLite
  transaction that inserts the order snapshot and upserts the paid enrollment.

On final submit, the checkout module begins one site-bound transaction,
re-reads the owner-bound draft and current plan constants, and revalidates the
current owner, 4900 amount, USD currency, and fingerprint. For an approved
result it consumes the approval, inserts the immutable order snapshot, updates
the draft, and creates or reactivates the paid enrollment before commit. Any
failure rolls back all four effects. Decline and retry outcomes never consume
an approval and never create an order or paid enrollment.

The generated runtime remains authoritative for scenario validity,
idempotency, foreign-owner checks, stale facts, stale fingerprints, and
duplicate approval consumption. Site-level validation rejects unsupported
plans and malformed HTTP bodies before generated API calls.

## Validation and errors

Authentication is required for every draft, payment, review, attempt, order,
and cancellation route. Owner mismatch, unknown draft/order, or foreign access
returns the same 404-style response without revealing record existence.
Unsupported course/plan/scenario values, malformed keys, and extra fields
return a 422 validation page. Generated conflicts such as reused idempotency or
duplicate consumption return a safe 409 result. Declines and retryable sandbox
outcomes return normal, non-success result pages rather than server errors.

No card number, CVV, expiry, bank, wallet, credential, cookie, authorization
header, or sensitive form value is persisted or logged. Payment-looking
browser controls have no submitted `name`, and the attempt endpoint rejects
them even if a client fabricates a request.

## Test strategy

Implementation follows strict behavior-sized RED/GREEN slices. Tests first
demonstrate the absence of each production behavior, then the smallest change
makes that slice pass. Coverage includes:

- migration, server-owned plan totals, frozen fingerprint, and reset/snapshot;
- authenticated public entry, owner-bound draft creation, and unsupported plan
  rejection;
- payment HTML controls with no names and review totals/warnings;
- exact attempt payload shape and explicit sensitive-field rejection;
- approved, declined, and retryable sandbox outcomes;
- atomic approval/order/enrollment commit and rollback behavior;
- idempotency, duplicate consumption, stale facts/fingerprint, and foreign
  owner rejection;
- owner-scoped history/detail/cancel/back navigation;
- durable order/enrollment state across service close/reopen and full reset;
- no regression in existing enrollment, auth, source-grounding, and public UI
  behavior.

Verification also runs the repository payment tests, backend/isolation checks,
the site test suite, static checks, all 23 trace-text preservation checks, the
supported payment-scope checker, and the current offline-clone diagnostic. The
diagnostic remains advisory and is reported honestly rather than treated as a
merge or release gate.

## Payment-scope record

`materials/33/scope/payment-scope.json` uses the repository-supported
`manifest-native-audit` mode because site 33 has an offline-clone v2 manifest
and no legacy site profile. It has no candidate blocker or retained blockers
and binds the current clone manifest, generated backend runtime/model, payment
capability pack, and site scope documents using the supported workflow digest
commands. The supported check is:

```bash
websitebench-workflow check-payment-scope \
  --proposal materials/33/scope/payment-scope.json
```

This audit records the local-sandbox scope; it does not authorize Stripe,
live payment, deployment, or any external effect.
