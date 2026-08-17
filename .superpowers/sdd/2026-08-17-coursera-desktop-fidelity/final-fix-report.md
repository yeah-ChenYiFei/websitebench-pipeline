# Site 33 checkout trial-pricing final fix

## Investigation and root cause

The reported mismatch was reproduced by changing the focused backend expectations
before production code. The RED command was:

```text
python -m pytest materials/33/clone/tests/test_checkout_backend.py::test_checkout_schema_exposes_the_server_owned_cny_trial_plan materials/33/clone/tests/test_checkout_backend.py::test_create_draft_binds_owner_and_cny_trial_facts_to_generated_payment materials/33/clone/tests/test_checkout_backend.py::test_approved_attempt_atomically_creates_paid_order_and_enrollment -q
3 failed in 0.21s
```

The failures showed the old `USD`, `4900`, `deep-learning-specialization-paid`,
and missing-trial facts. The prior checkout suite itself passed while asserting
those USD facts (`20 passed in 1.29s`), so the regression was locked into the
tests rather than surfaced by them.

Data-flow tracing found one independent hard-coded backend plan in
`clone/backend/checkout.py`: it created the generated local-sandbox intent at
USD 4,900, supplied the same amount/currency/fingerprint at attempt and
approval consumption, and inserted the same facts into the durable order. In
parallel, `clone/app.py` hard-coded the learner-visible CNY trial strings.
Consequently the flow was:

```text
old backend USD constants -> checkout draft -> generated payment flow
-> attempt/approval consumption -> USD order/enrollment

unrelated app literals -> ¥196/month, ¥0 today UI
```

## Supported-contract decision

The generated `SitePayments` seam accepts non-negative integer minor amounts;
zero-valued local-sandbox intents are valid. It rejects a currency that differs
from `backend/runtime.json`, retains owner/fingerprint/idempotency checks, and
requires an active caller-owned transaction for approval consumption. No custom
payment, auth, hash, or gate mechanism was added.

The backend scaffold command intentionally refuses to overwrite an existing
runtime. The supported change was therefore to update the existing sole runtime
contract at `materials/33/backend/runtime.json` to `CNY`, use the generated
seam as-is, refresh the existing hash-bound payment-scope document with the
repository's `sha256_file` and `payment_scope_subject_sha256` helpers, then run
`websitebench-workflow check-payment-scope`. The result passed.

## Fix

`TRIAL_PLAN` is the single server-owned model. It records CNY, a zero-value
activation total, seven trial days, CNY 19,600 minor-unit monthly renewal, and
the corresponding frozen fingerprint. New checkout drafts and durable orders
persist the trial and renewal fields. Generated payment intent, attempt, and
approval consumption use the same CNY zero amount and fingerprint. Draft and
order replays revalidate every persisted server-owned trial fact.

The checkout entry renders its hidden plan ID and visible terms from
`checkout.plan()`. Review and order history/detail render persisted draft/order
facts rather than duplicating pricing literals. Existing database rows gain
explicit legacy defaults (`trial_days=0`, `renewal_minor=0`,
`renewal_currency=USD`, `renewal_interval=none`) without rewriting their old
snapshots; all newly-created trial orders carry the intended facts.

## Files changed

- `materials/33/backend/runtime.json`
- `materials/33/clone/backend/checkout.py`
- `materials/33/clone/app.py`
- `materials/33/clone/tests/test_checkout_backend.py`
- `materials/33/clone/tests/test_checkout_flow.py`
- `materials/33/clone/tests/test_desktop_contract.py`
- `materials/33/scope/payment-scope.json`
- `materials/33/KNOWN_DIFFERENCES.md`

## Verification

GREEN after the production change:

```text
python -m pytest materials/33/clone/tests/test_checkout_backend.py -q
21 passed in 1.38s

websitebench-workflow check-payment-scope --proposal materials/33/scope/payment-scope.json
status: passed

websitebench-offline-clone verify --site materials/33 --section static
diagnostic_status: clean

python -m pytest tests/site_backend/test_runtime_and_lifecycle.py tests/site_backend/test_payments.py -q
25 passed in 0.10s
```

`websitebench-offline-clone contribution report --site materials/33 --out
contribution-report.json --bundle-out contribution-handoff.zip` was regenerated
and left untracked as required. Its live diagnostic remains incomplete with
`[Errno 1] Operation not permitted`; the static section is complete and clean.

Focused flow, desktop, and site backend-isolation suites that use FastAPI's
`TestClient` are **incomplete, not passing** in this environment. A 30-second
probe of `test_payment_fields_are_memory_only_and_review_submits_two_safe_keys`
exited 124 before fixture setup. `pytest -o faulthandler_timeout=5` located the
stall in `starlette.testclient.TestClient.__enter__`, and an empty `FastAPI()`
application reproduced it under Python 3.14 with httpx 0.28.1 (the installed
FastAPI wrapper also emits the httpx/Starlette deprecation warning). This occurs
before any site route or checkout code executes. The same fixture boundary
prevents the desktop and applicable site isolation suites from completing.

## Runtime and safety summary

- Runtime path: `materials/33/backend/runtime.json`
- Site ID: `33`
- Database / volume identity: `data/33.sqlite3` / `websitebench-33-data`
- Enabled mail purposes: `registration`, `password-reset`
- Payment profile: `local-sandbox` only, CNY, no card data, provider call, or
  live payment
- Deployment profiles: `offline-harbor`, `cloudflare-review`, `docker-volume`

## Self-review and remaining limitations

I re-read the changed data flow, checked the payment-scope inputs and subject
hash through the repository helpers, scanned site-33 non-vendored files for
old `USD`, `4900`, and stale paid-plan facts, and ran `git diff --check`.
An independent review found that legacy USD snapshots would have displayed as
CNY and that the specialization entry duplicated trial copy; both were fixed.
The focused assertion now confirms `USD 4900` renders as `$49.00` and a
one-time checkout while CNY trial copy derives from the shared model.
Owner binding, exact fingerprint validation, idempotency, approval consumption,
atomic order/enrollment commit, decline/retry behavior, and tamper rejection
remain covered by the backend suite. The only verification limitations are the
environment-level TestClient stall and the sandbox restriction on the live
diagnostic; neither is reported as a passing suite.
