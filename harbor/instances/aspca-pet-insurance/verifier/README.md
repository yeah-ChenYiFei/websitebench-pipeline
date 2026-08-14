# aspca-pet-insurance — instance verifier notes

Scoring is fully declarative and deterministic; there is no instance-specific
verifier code. The harness evaluates the candidate with the shared v2 judge
against the hidden suites in `../fixtures/hidden/`:

- `task-suite.json` — Playwright-DSL browser/API tasks. Expected values are
  not authored by hand; they are frozen facts captured from the reference
  runtime (`capture-reference`) into `reference-observations.json`. The judge
  replays the same actions against the candidate and compares observation by
  observation. `task_score = passed / total * 100`; reward = `task_score /
  100`.
- `visual-suite.json` — deterministic checkpoints (route + viewport +
  actions) compared region-by-region with area-weighted RGB SSIM against the
  captured reference rasters under `visual/`. Report-only.
- `cicd-suite.json` — the fixed trusted platform check set (deployment
  lifecycle, isolation, tree immutability, network closure, secret scan,
  browser smoke, accessibility, budgets). Report-only.

Operational notes:

- Each task starts from a fresh reference/candidate state (empty data
  directory), so in-task identifiers are deterministic (first quote
  `WB100001`, first policy `APH-000001`).
- The `restart` action re-launches the server against the same data
  directory; tasks use it to prove persistence.
- Diagnostics and calibration results are diagnostic-only: never present a
  `clean` verify report or a passing calibration as an acceptance, rights or
  deployment decision.

Local commands (repo root):

```bash
websitebench-harbor validate --instance harbor/instances/aspca-pet-insurance
websitebench-harbor capture-reference --instance harbor/instances/aspca-pet-insurance
websitebench-harbor materialize --instance harbor/instances/aspca-pet-insurance --output harbor-dist/aspca-pet-insurance
websitebench-harbor validate-bundle --bundle harbor-dist/aspca-pet-insurance
websitebench-harbor calibrate-v2 --bundle harbor-dist/aspca-pet-insurance --output harbor-calibration/aspca-pet-insurance
```
