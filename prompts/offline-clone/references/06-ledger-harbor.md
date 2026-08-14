<!-- Phase 9: interaction ledger and Harbor -->

> This file is a phase reference for `prompts/offline-clone/autonomous-source-to-clone.md`.
> **The operating rules in the entry prompt—authorization, autonomous decision boundaries, stopping rules, parallelism, and context—take precedence over this file.**
> Previous: `05-implement.md` | Next: `07-verify.md`

## Phase 9: interaction ledger and Harbor

While walking the route/state matrix, record:

- the clone URL;
- a stable selector for every activated control;
- one visible-text proof;
- one raw-markup proof;
- the form action for every mutation; and
- journey, role, state, and evidence ID.

Selectors may come only from the current walk or this site's recorded
trajectory ledger. Never infer them from scope prose.

### Populate the ledger from recorded trajectories

When a journey has a recorded source-side trajectory, as described in “Human
trajectory recorder,” **prefer selectors and step order from `actions.jsonl`**
instead of inferring them in another manual walk. The ledger's
`tag / id / name / type / role / xpath` values come from actual clicks, `submit`
events directly identify the element associated with each mutation, and the
`pageLoad` chain gives the real routes and redirects.

The recorder cannot provide the **visible-text proof or raw-markup proof** the
ledger requires because it omits element text. Those two proofs must come from
a DOM-enabled capture pass or direct inspection of the running clone. Never
infer copy from a selector in the recording ledger.

### Candidate-side recording and two-sided comparison

After the frontend diagnostics run and before generating the Harbor contract,
record each of the same P0/P1 journeys once against the locally running clone:

```bash
websitebench-browser-trajectory record \
  --cdp-url http://127.0.0.1:9222 \
  --allowed-origin http://127.0.0.1:<clone-port> \
  --output materials/<site-id>/artifacts/trajectory/<trace-id>.clone
```

Then compare the two ledgers with `websitebench-browser-trajectory diff`; see
“Two-sided comparison” under “Human trajectory recorder” for usage and
normalization rules. Do not hand-write normalization; it already has an
implementation and tests.

Interpret divergence in a fixed order: **first suspect that the two human
demonstrations differ; then suspect a missing clone behavior.** Turn a confirmed
clone omission into a candidate repair item. Record a confirmed demonstration
difference in that trajectory's notes without changing the clone.

This comparison is diagnostic. It produces findings and informs the ledger and
repair loop, but **it is not an acceptance decision, creates no source
coverage, and does not replace phase 10 functional or visual verification.** It
has the same advisory standing as OpenCLI replay.

Before contract derivation, create the current same-id Harbor authoring pair for
every new site. Do not copy an existing site's suites or use a pre-compile v2
layout as a starter:

```bash
websitebench-harbor init-site \
  --site-dir harbor/sites/<site-id> \
  --site-id <site-id> \
  --display-name "<display-name>"

websitebench-harbor init-instance \
  --instance-dir harbor/instances/<site-id> \
  --instance-id <site-id> \
  --site-manifest sites/<site-id>/site.yaml \
  --author-name "WebsiteBench Pipeline" \
  --author-email websitebench@example.test
```

The new instance is intentionally a non-scorable draft. Its case manifest and
task, visual, and CI/CD suites must remain empty until site-specific evidence is
authored. `validate` must return exit code 0 with `status: draft`,
`scorable: false`, and the missing case counts. Do not call capture,
materialize, calibration, or scoring on that draft.

The generated public contract is `compile.sh -> executable`, not `deploy.sh`.
The candidate must use `HOST`, `PORT`, `DATA_DIR`, `SEED`, and `TZ`, stay in the
foreground, handle SIGTERM, and return exact JSON `{"status":"ok"}` from
`/__websitebench/health`. The site declares both `playwright` and
`browser-use` as formal browsers.

After the frontend diagnostics complete, run:

```bash
websitebench-harbor derive-from-clone \
  --clone-manifest materials/<site-id>/clone.yaml
```

Resolve every item in the command's `pending` output from the interaction
ledger, then rerun with `--force` when the contract needs to change. Derivation
writes the contract and `browser: false` adapters directly. Run
`websitebench-harbor run-opencli` for each profile against the running loopback
clone.

If the unique instance needs a derived profile assignment, rerun derivation
with `--assign-profile <site-id>=<profile-id>`. Then confirm the generated draft
shape:

```bash
websitebench-harbor validate \
  --instance harbor/instances/<site-id> \
  --corpus-root harbor
```

When benchmark authoring later completes the private case data, require exactly
200 cases: T1=20, T2=165, T3=15, with T2 split L1=35, L2=50, L3=80. Every T2
journey uses explicit terminal observations and must pass both formal browser
executors; screenshots and area-weighted RGB SSIM come only from fixed
Playwright rendering. Trusted platform checks are verifier infrastructure and
must not consume any of the 200 site cases.

OpenCLI replay is advisory: it creates no trace coverage and does not decide
acceptance. When OpenCLI is unavailable, record `opencli-unavailable` and
continue the build.
