# Site 33 — backend/runtime compliance audit (2026-08-21)

Cross-checked the clone backend against the repository backend mandate and
runtime specs: `docs/websitebench-site-backend-mandate.md`,
`docs/site-backend-runtime.md`, `docs/adr/0001...0003`, and the
Web2Code2Web execution plan in `requirements/`.

## Runtime contract (`backend/runtime.json`) — 8/8 PASS

| Requirement | Evidence |
|---|---|
| Unique stable `site_id` | `site.id = "33"` |
| Independent SQLite per site | `data/33.sqlite3`, engine sqlite |
| Session cookie `__Host-` derived from site id | runtime.py derives `__Host-websitebench-33-session` |
| Cookie Host-only / Secure / HttpOnly / SameSite | `host_only, secure, http_only, same_site=Lax` |
| Mail: purposes + OTP hash-only (secret_variables) | `password-reset`, `registration`; `code` marked secret |
| Payment `local-sandbox` with deterministic outcomes | approved / declined / retryable; `stripe_test: null` |
| Deployment profile `offline-harbor` | local-outbox + local-sandbox + persistent |
| No live keys / no real payment | no card fields with name, no live charges |

## Standard seam usage — PASS

- Registration/login/recovery/logout all go through the generated
  `LocalAuthStore` (`start_registration`, `verify_registration_code`,
  `complete_registration`, `sign_in`, `sign_out`, `start_password_reset`,
  `verify_password_reset_code`, `complete_password_reset`,
  `resolve_session`, `ensure_session`).
- Checkout uses `backend.payments.create_intent / attempt /
  consume_approval` with owner, integer minor units, currency, canonical
  fingerprint, idempotency key, and opaque scenario ids; the approval is
  consumed inside the caller transaction before the order write.
- Mail is site-bound (`template_id: 33.*.v1`), structured text only, and
  OTP is persisted as salt/hash via the shared store; `/local-inbox`
  exposes the local outbox for offline verification.
- Rate/abuse budget is enforced by the store
  (`local_auth_mail_rate_limits`, attempt caps).
- `scope/backend-capabilities.json` records the applicable capabilities
  (accounts, password-recovery, transactional-mail, orders, checkout).

## Machine evidence

- `pytest tests/site_backend tests/local_clone_auth` -> 73 passed.
- Site suite (292 tests) covers auth lifecycle, checkout, orders,
  persistence across restart, and owner isolation.
- Static diagnostics clean (87/87 assets, zero remote, zero secrets).

## Gaps (not compliance violations)

- `backend/node-bridge.json` and `site_backend_bridge.mjs` are absent; the
  Node stdio bridge is only needed for the Node deployment path and is not
  part of the current Python uvicorn runtime contract. The fixed-shape
  bridge test does not include site 33.
- Harbor derivation stage is not started: no `tools/frontend_samples.json`,
  no `materials/33/harbor/`, no interaction contract. This is the
  workflow step-3/5 deliverable (init-site/init-instance +
  derive-from-clone + materialize), not a backend-compliance gap.
- Live diagnostics remain blocked by the host kernel-sandbox limitation
  (`[Errno 95]`), recorded in KNOWN_DIFFERENCES.
