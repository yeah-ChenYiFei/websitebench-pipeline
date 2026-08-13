# Provenance

This repository was extracted on **2026-08-13** from the WebsiteBench main
repository (`WcodeW`) to serve as a standalone offline-clone production
pipeline. Its output for one site is a Harbor-standard instance plus a
successfully deployed public demo site.

- Source checkout: `/home/user/yiwen/WcodeW`
- Source branch: `codex/web2code2web-integration-20260812`
- Source HEAD at copy time: `bbeb051899c83482b0c661dc29ec5ab08fba8062`
- Copy semantics: **working-tree content** (the source tree carried
  uncommitted modifications and untracked-but-needed files, e.g.
  `.github/workflows/clone-diagnostics.yml`,
  `materials/tripit/tools/frontend_samples.json`,
  `src/websitebench/offline_clone/{diagnostics,secrets}.py`). The file set was
  `git ls-files --cached --others --exclude-standard` over the selected paths,
  minus paths deleted from the working tree.

## Carried

- `src/websitebench/` (complete), `websitebench/` data (schemas, capability
  packs, corpora), `prompts/offline-clone/` (all phases, including
  `references/08-deploy.md`), `skills/` + `.agents/`,
  `tools/offline_clone/` (generic tools + example specs only),
  selected `scripts/` (including the three MCP launchers), selected `docs/`
  + all ADRs, `materials/tripit/` and `harbor/sites/tripit/` as the golden
  sample, harbor skeleton files, the site-agnostic test suites, and CI
  (`tests.yml`, `clone-diagnostics.yml`, `tests-tripit.yml`).
- Deployment machinery: `deploy/generic-offline-clone/` (tracked set, minus
  the other sites' `deployment.*.v2.json` descriptors), `deploy/shared/`
  (imported by the deploy package's mail/config tests),
  `deploy/eight-site-clones/scripts/sanitize-response-headers.mjs` (the one
  file `public-demo-site.yml` uses on the tripit path),
  `deploy/public-demo-release-authority.md`,
  `.github/workflows/public-demo-site.yml`,
  `.github/workflows/deploy-tripit-public.yml`,
  `docs/public-demo-new-site-deployment.md`, and the deployment tests
  (`test_deployment_runs_shared_diagnostics`,
  `tests/site_backend/test_generic_container_launch.py`).

## Deliberately not carried

- `src/clawbench/` compatibility package and its 9 `clawbench-*` entry points
  (pyproject edited accordingly). Historical ClawBench *identifiers inside
  data* remain immutable per `AGENTS.md`.
- The legacy deployment packages (`deploy/eight-site-clones/` except the one
  script above, `deploy/amazon-clone/`, `deploy/node-offline-clone/`,
  `deploy/websitebench-sites/`, `deploy/websitebench-cloudflare-worker/`)
  and every non-tripit `deploy-<site>-public.yml` wrapper.
- All other sites' `materials/`, `harbor/sites/`, `harbor/instances/`, their
  per-site workflows and site-specific tests/specs/scripts.
- Historical evidence directories (`project/`, `artifacts/`, review-staging
  helpers, one-off `upgrade_*.py` scripts).

## Local edits made during extraction

- `pyproject.toml`: clawbench package/scripts/force-include removed; sdist
  list trimmed; description updated.
- `src/websitebench/harbor/derive.py`: `SITE_ID_ALIASES` emptied (the edx
  alias belonged to the main repository); `repository_root()` anchors on a
  directory containing both `materials/` and `harbor/`.
- `scripts/fetch_assets.py`: Python imports migrated from `clawbench.*` to
  `websitebench.*`; the `clawbench.asset-fetch-spec.v1` schema id in data is
  intentionally unchanged (immutable identity).
- Entry prompt: duplicated "Context hygiene" heading collapsed and its stale
  hook claim dropped; missing "## Stopping rules" parent heading restored.
- `.github/workflows/deploy-tripit-public.yml`: registration push trigger
  rebound from branch `web2code2web` to this repository's `main`.
- `CONTRIBUTING.md`: stale `--gate` flag corrected to `--section`; example
  site switched to tripit.
- `.gitignore`: petfinder/ClawBench-specific entries removed.
- Tests: hardcoded non-carried sites retargeted to tripit where the test
  checks generic mechanics (`tests/harbor/test_opencli_{cli,runner,contracts}`),
  presence-skips added where main-repo data is legitimately absent
  (`tests/site_backend/test_stdio_bridge.py`,
  `tests/local_clone_auth/test_local_clone_auth.py`,
  `tests/site_backend/test_generic_container_launch.py` — amazon descriptor,
  `deploy/generic-offline-clone/tests/config.test.mjs` — edx/petfinder
  descriptors), and site-bound suites whose subject was not carried were
  deleted (amazon/edx/capterra isolation, viewer corpus tests, site identity
  migrations, petfinder instances, task-replay, public-clone-auth,
  r1-staging helper).
- `materials/tripit/clone/tests/test_release_structural.py`: the source
  working tree was mid-way through the tripit visual re-freeze (the
  checkpoints schema and `scope/checkpoints.json` had already dropped
  `source_artifact_sha256` from visual contracts; `tests/offline_clone`
  fixtures and `src` followed, but this one release test still asserted the
  digest field and was failing in the source checkout too). This repository
  follows the working-tree contract: the test now binds artifacts by path
  (and still verifies a digest whenever the frozen document records one).
  All 51 carried source rasters were byte-verified against the last committed
  digests before that change (`ok=51 bad=0`).
- New files: `README.md`, `ACCEPTANCE.md`, `CLAUDE.md`, `.mcp.json`,
  `.claude/skills/trace-guided-offline-clone` (symlink), this file.
- New instance: `harbor/instances/tripit/` scaffolded with
  `websitebench-harbor init-instance --legacy-v1` (v1 layout, matching the
  tripit site contract's `websitebench.harbor.site.v1`), then
  `opencli_profile: marketing-and-auth-entry` and tags filled in;
  `websitebench-harbor validate` reports `status: valid`.

## Known gaps at extraction time

- The tripit visual re-freeze was in flight in the source working tree at
  copy time: `scope/checkpoints.json`'s `freeze_decision.rationale` still
  says top-level rasters are retained "path + sha256" while the data rows
  carry only paths. The digests recorded at source HEAD `bbeb051` all match
  the carried artifacts (verified during extraction), so re-adding them later
  is a mechanical, evidence-preserving step once the upstream freeze settles.

- `harbor/sites/tripit/interactions/derivation.json` was deleted in the source
  working tree at copy time (contract + adapters remain); re-running
  `websitebench-harbor derive-from-clone` regenerates it.
- The tripit instance's oracle (`solution/solve.sh`) and calibration runs are
  not implemented yet; the scripts honestly exit non-zero and acceptance
  stage 6 blocks evaluation release until calibration is real.
- Deploying from THIS repository requires its own GitHub remote with the
  Cloudflare/Basic-auth secrets described in
  `docs/public-demo-new-site-deployment.md`; the live reference
  `https://tripit.website-bench.com` was deployed from the main repository.
  Local `--check-only`/`--dry-run` paths work without credentials.
