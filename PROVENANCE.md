# Provenance

This repository was extracted on **2026-08-13** from the WebsiteBench main
repository (`WcodeW`) to serve as a standalone offline-clone production
pipeline.

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
  packs, corpora), `prompts/offline-clone/`, `skills/` + `.agents/`,
  `tools/offline_clone/` (generic tools + example specs only),
  selected `scripts/`, selected `docs/` + all ADRs,
  `materials/tripit/` and `harbor/sites/tripit/` as the golden sample,
  harbor skeleton files, the site-agnostic test suites, and CI
  (`tests.yml`, `clone-diagnostics.yml`, `tests-tripit.yml`).

## Deliberately not carried

- `src/clawbench/` compatibility package and its 9 `clawbench-*` entry points
  (pyproject edited accordingly). Historical ClawBench *identifiers inside
  data* remain immutable per `AGENTS.md`.
- All deployment machinery: `deploy/`, public-demo workflows and docs, and
  the prompt deploy phase (`references/08-deploy.md`; entry-prompt index and
  cross-links edited to match).
- All other sites' `materials/`, `harbor/sites/`, `harbor/instances/`, their
  per-site workflows and site-specific tests/specs/scripts.
- Historical evidence directories (`project/`, `artifacts/`, review-staging
  helpers, one-off `upgrade_*.py` scripts).

## Local edits made during extraction

- `pyproject.toml`: clawbench package/scripts/force-include removed; sdist
  list trimmed; description updated.
- `src/websitebench/harbor/derive.py`: `SITE_ID_ALIASES` emptied (the edx
  alias belonged to the main repository).
- Entry prompt: deploy phase row removed; duplicated "Context hygiene"
  heading collapsed and its stale hook claim dropped; missing "## Stopping
  rules" parent heading restored.
- `AGENTS.md`: "New public-demo sites" section removed.
- `CONTRIBUTING.md`: stale `--gate` flag corrected to `--section`; example
  site switched to tripit.
- `.gitignore`: petfinder/ClawBench/deploy-specific entries removed.
- New files: `README.md`, `ACCEPTANCE.md`, `CLAUDE.md`, this file.

## Known gaps at extraction time

- `harbor/instances/` carries no tripit instance yet — the pipeline's final
  step is demonstrated by `websitebench-harbor init-instance` scaffolding, not
  by a shipped example.
- `harbor/sites/tripit/interactions/derivation.json` was deleted in the source
  working tree at copy time (contract + adapters remain); re-running
  `websitebench-harbor derive-from-clone` regenerates it.
