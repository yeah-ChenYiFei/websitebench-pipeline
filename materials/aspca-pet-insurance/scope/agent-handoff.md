# Offline-clone final handoff

- Site: `aspca-pet-insurance`
- Status: complete for the authorized anonymous offline-clone scope
- Current reference: `references/08-deploy.md`
- Next reference: none
- Worktree disposition: preserved in place on `main`; no commit, merge, push,
  pull request, workflow dispatch, or deployment was performed.

## Authorization ceiling

- Source mutation was limited to the previously authorized synthetic quote
  walk, with a hard stop before any payment field.
- `REAL_EMAIL_AUTHORIZED=false`, `STRIPE_TEST_AUTHORIZED=false`, and
  `LIVE_PAYMENT_AUTHORIZED=false`.
- Authenticated member evidence remains optional and unavailable until a
  separate read-only credential handoff is explicitly authorized.
- `PUSH_AUTHORIZED=false`, `PR_AUTHORIZED=false`, and
  `PUBLIC_DEPLOYMENT_AUTHORIZED=false`; public-demo work stopped after
  `--check-only` and `--dry-run`.

## Delivered contract

- Frozen anonymous marketing pages and responsive home views.
- Stateful dog/cat quote creation, validation, deterministic rating,
  customization, add-a-pet, resume lookup, and non-payment enrollment.
- Site-bound SQLite lifecycle with migrations, deterministic reset, restart
  persistence, backup/site-binding, and concurrent quote creation tests.
- Captured anonymous portal login/register/forgot-password shells. Valid
  submissions fail closed and create no account, session, challenge, or mail.
- No payment fields, payment adapter calls, payment success state, receipt, or
  retry surface. Payment-shaped input is rejected before persistence.
- Zero remote runtime references in shipped candidate files.

The dated `scope/derived-task-brief.json` is retained as the original planning
record. The frozen current authority is `purpose.json`, `journeys.json`,
`invariants.json`, `coverage.json`, `routes.json`, `checkpoints.json`, and
`backend-capabilities.json`; those files narrow the early proposal to the
implemented anonymous contract above.

## Current machine evidence

- Offline-clone diagnostic: `clean`; static and live execution complete, no
  findings, no remote references, and no detected secrets.
  - Static: 502 declared assets, 335 globally verified, 212/212 candidate-
    required assets verified, 210/210 P0 assets verified, required closure
    `1.0`, five deferred checkpoints, one deferred route.
  - Live: 42 checkpoints, 37 page loads, three visual contracts. Home visual
    similarities are desktop `0.9958`, mobile `0.9999`, tablet `0.9999`
    against threshold `0.995`.
- Clone tests: 46 passed. The only warning is Starlette's upstream
  `TestClient`/`httpx` deprecation warning.
- Harbor instance and 17-file materialized bundle: valid.
- Harbor calibration: passed with exact repeat.
  - NOP: task `0`, reward `0`.
  - Oracle first and second: task `100`, CI/CD `100`, reward `1`, visual
    `99.99999995` on both runs.
- OpenCLI adapters: in sync. Advisory candidate replay passed quote `6/6` and
  auth `4/4`, with zero assertion failures.
- Repository regression:
  - expanded Ruff scope: passed;
  - prompt freshness: 15 passed;
  - `tests/offline_clone tests/harbor tests/project`: 388 passed, 8 skipped;
  - generic public-demo package: 29 passed, 2 skipped;
  - quote and portal JavaScript syntax checks: passed.
- Public-demo descriptor: `--check-only` valid with no warnings; Wrangler
  `--dry-run` completed. No Worker, container, route, secret, or domain was
  created or changed.

## Backend and deployment identity

- Runtime: `materials/aspca-pet-insurance/backend/runtime.json`
- Unique `site_id`: `aspca-pet-insurance`
- Database identity: `data/aspca-pet-insurance.sqlite3`
- Volume identity: `websitebench-aspca-pet-insurance-data`
- Mail: disabled; enabled purposes: none
- Payments: disabled; `local-sandbox` remains the mandatory schema/default
  adapter declaration and is not invoked by the clone
- Deployment profiles: `offline-harbor`, `cloudflare-review`, `docker-volume`
- Public-demo profile: `cloudflare-review`, ephemeral-reset persistence,
  fixed Worker `websitebench-aspca-pet-insurance-demo`, fixed domain
  `aspca-pet-insurance.website-bench.com`, one basic instance maximum

The generic Cloudflare profile still declares its fixed `redis-resend` and
`local-sandbox` infrastructure variables/secrets even when this site's runtime
capabilities are disabled. `MAIL_TEMPLATES` is empty, registration smoke is
absent, payments are disabled in the canonical runtime, and the clone exposes
no consuming route.

## Explicit limitations

- Five authenticated member checkpoints and the `portal-member` route are
  deferred. They are not implemented or credited. Browserbase is unnecessary
  for the completed anonymous scope; expanding this area requires a separately
  authorized credential-bearing source session.
- Live diagnostics report 24 non-default states without declarative state
  recipes. This is a coverage counter, not a finding; Harbor functional suites
  exercise the frozen primary journeys, but no claim is made that all 24 states
  were browser-reached by the generic diagnostic.
- No formal independent blind audit was performed, so the corresponding
  source-direct coverage `satisfied_items` remains empty.
- The manifest retains 290 optional historical capture rows. 167 have
  non-blocking MIME/dimension/CSS-validity differences; none is a required
  candidate dependency.
- `npm ci` reported three dependency-audit findings (two moderate, one high).
  No broad dependency upgrade was attempted; the package test suite is green.
- No real public deployment or publication validation was authorized.

## Durable paths

- Candidate: `materials/aspca-pet-insurance/clone/`
- Frozen scope: `materials/aspca-pet-insurance/scope/`
- Backend runtime/model: `materials/aspca-pet-insurance/backend/`
- Asset-scope maintenance: `materials/aspca-pet-insurance/tools/freeze_asset_scope.py`
  and `promote_localized_css.py`
- Harbor authoring: `harbor/sites/aspca-pet-insurance/` and
  `harbor/instances/aspca-pet-insurance/`
- Materialized bundle: `harbor-dist/aspca-pet-insurance/`
- Calibration: `harbor-calibration/aspca-pet-insurance/report.json`
- Public-demo descriptor: `deploy/generic-offline-clone/deployment.aspca-pet-insurance.v2.json`
- Site diagnostics dispatcher: `.github/workflows/tests-aspca-pet-insurance.yml`
- Fixed dispatcher: `.github/workflows/deploy-aspca-pet-insurance-public.yml`

## Human input

None is required for the completed anonymous clone. A separate explicit grant
and ephemeral credential handoff are required to add authenticated member
evidence. A separate explicit deployment grant is required before any real
public-demo workflow dispatch.
