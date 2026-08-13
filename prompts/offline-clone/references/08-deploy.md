<!-- Phases 11–12: deployment preparation and online revalidation -->

> This file is a phase reference for `prompts/offline-clone/autonomous-source-to-clone.md`.
> **The operating rules in the entry prompt—authorization, autonomous decision boundaries, stopping rules, parallelism, and context—take precedence over this file.**
> Previous: `07-verify.md` | Next: end

## Phase 11: deployment preparation for the current codebase

For the full public-deployment configuration, dispatcher template, and
extension boundary for a new site, read
[`docs/public-demo-new-site-deployment.md`](../../../docs/public-demo-new-site-deployment.md)
first. It requires exactly one fixed public entry point per site.

Create:

- `deploy/generic-offline-clone/deployment.<site-id>.v2.json`
- `.github/workflows/deploy-<site-id>-public.yml`

Do not create `.github/workflows/<site-id>-clone.yml`.

The descriptor uses the current six-field v2 structure:

```text
schema_version
source_dir
backend_runtime
deployment_profile
runtime
cloudflare
```

Requirements:

- `schema_version=websitebench.generic-public-clone-deployment.v2`;
- `source_dir=materials/<site-id>/clone`;
- `backend_runtime=materials/<site-id>/backend/runtime.json`;
- `deployment_profile=cloudflare-review`;
- Worker=`websitebench-<site-id>-demo`;
- container port=10000;
- health path=`/healthz`;
- exact Python requirement pins; and
- the repository's current Python 3.12, Node 24, and full-SHA-pinned Actions in
  the workflow.

Do not put the domain in the descriptor. Derive it from `site.public_origin` in
`backend/runtime.json`.

The new-site workflow reuses `.github/workflows/public-demo-site.yml`:

- a push registers the workflow only and must not deploy;
- `workflow_dispatch` exposes a `deploy` boolean;
- `deploy=false` runs only verification, preparation, and Wrangler dry-run;
- only `deploy=true` permits real publication;
- secrets use the current repository-scope resolution mechanism;
- do not create a `<site-id>-production` GitHub Environment;
- do not add the legacy eight-site path's `CLOUDFLARE_DEPLOY_ENABLED` condition;
- configure Turnstile only when the generated candidate explicitly requires it;
  and
- keep the Basic Auth and `noindex` boundaries for the public demo.

The current shared workflow still has advisory baseline behavior for some
legacy sites. A new-site wrapper may fix exactly one `site` and invoke the
shared workflow. If stricter site-specific validation is needed, add checks
only for that site. Do not introduce a repository-wide plan, site-list input,
matrix, batch-publication path, or a policy change for any existing site.

Run only these local operations:

```bash
cd deploy/generic-offline-clone
npm ci
npm test
node scripts/prepare.mjs \
  --config deployment.<site-id>.v2.json \
  --check-only
node scripts/deploy.mjs \
  --config deployment.<site-id>.v2.json \
  --dry-run
```

Unless the user explicitly grants the corresponding authority for the current
task, do not commit, push, create a PR, dispatch a workflow, send real email, or
perform a real deployment. No `clean` diagnostic, test result, or Harbor score
authorizes copyright use, redistribution, or public publication.

## Phase 12: online revalidation after authorization

Perform a real deployment only when `PUBLIC_DEPLOYMENT_AUTHORIZED=true`, the
current scoped checks pass, and publication/redistribution rights satisfy the
current configuration.

Record a recoverable Worker version before deployment. After deployment,
revalidate with the same Browserbase configuration:

- DNS, TLS, and `/healthz`;
- site ID;
- candidate/deployment SHA;
- Worker version and Container build ID;
- Basic Auth, `noindex`, security response headers, and cookies;
- every P0/P1 success, failure, cancellation, and recovery journey;
- state-by-state regional visual comparison between source and online
  candidate;
- an unlabeled blind review; and
- zero forbidden remote runtime dependencies.

The current shared workflow automatically attempts rollback only when the
deploy command itself fails. If health, functionality, or visual checks fail
after a successful deployment, do not claim an automatic rollback exists.
Explicitly roll back under the same deployment authorization and revalidate.
Do not perform a real deployment when a recoverable version cannot be
confirmed.
