# WebsiteBench Clone Atlas

Clone Atlas is the WebsiteBench corpus and evaluation viewer. It is designed for
a growing benchmark with many offline websites, multiple categories, and results
from multiple model/harness combinations. It keeps four forms of evidence
separate:

- automatic artifact readiness (`present`, `missing`, `invalid`, or
  `not_applicable`);
- current clone diagnostics (`clean`, `findings`, or `incomplete`) plus an
  explicit maintainer-judgment requirement;
- schema-valid `websitebench.result.v1` candidate scores.

It never derives a composite task-quality score. Viewer-side screenshot metrics
are explicitly diagnostic and are not official visual scores.

The overview presents the benchmark workflow, category coverage, and the
website-by-model evaluation matrix. The Websites catalog separates items that
are still being built from evaluation-ready and evaluated items. Models groups
runs by stable candidate identity, while Results is the cross-model result
table. A run page is the primary source-versus-clone comparison surface.

## Local use

Create an Argon2 hash and set credentials without committing them:

```bash
websitebench-viewer hash-password
export WEBSITEBENCH_VIEWER_USERNAME=reviewer
export WEBSITEBENCH_VIEWER_PASSWORD_HASH='$argon2id$...'
export WEBSITEBENCH_VIEWER_SESSION_SECRET='at-least-32-random-characters-change-me'
export WEBSITEBENCH_VIEWER_COOKIE_SECURE=false
websitebench-viewer --repo-root . serve --profile internal
```

The remaining commands are:

```bash
websitebench-viewer --repo-root . validate --profile internal
websitebench-viewer --repo-root . index --profile public --out public-index.json
websitebench-viewer --repo-root . publish --out public-viewer --base-path /
websitebench-viewer --repo-root . capture --item offlineclone--amazon-shopping-mainline
websitebench-viewer --repo-root . capture --item offlineclone--amazon-shopping-mainline \
  --run-id run-2026-07-22
websitebench-viewer --repo-root . capture --item offlineclone--amazon-shopping-mainline \
  --checkpoint home-desktop --viewport desktop \
  --source-image source.png --candidate-image candidate.png
websitebench-viewer --repo-root . export-reviews --out reviews.json
websitebench-viewer --repo-root . export-review-sessions \
  --item offlineclone--amazon-shopping-mainline --out review-session.json
```

Calling `capture` without images provisions companion records from every
declared checkpoint; it does not assume a fixed number of scenes. Providing
`--run-id` keeps visual evidence isolated per model run.

## Review Mode

The internal task-detail page provides a diagnostic Review Mode for post-build
feedback. Open it directly with `?review=1`, or use **Flag checkpoint** from a
source-versus-clone visual comparison. A finding records:

- the exact corpus item artifact fingerprint and a fingerprint-specific session;
- checkpoint, viewport, route, role and state when known;
- P0/P1/P2 severity and a visual, copy, interaction, semantics, responsive,
  state, data, accessibility, performance or other category;
- the reviewer's observation, optional expected result and repository-relative
  evidence references;
- an append-preserving disposition and resolution-evidence references.

Review sessions use optimistic revisions, remain separate when the artifact
fingerprint changes, reject detected secrets and personal data, and are stored
under `artifacts/websitebench-viewer/review-sessions/` by default. Pass
`--review-sessions <path>` to `serve` or `export-review-sessions` to use another
root. The public profile neither renders Review Mode nor exposes its APIs.

Review Mode is diagnostic feedback. A resolved finding does not qualify a
clone; affected browser, visual, backend and network diagnostics still need
current evidence and maintainer judgment.

## Item keys and review migration

The active Viewer contract accepts only two item-key namespaces:

- `offlineclone--<site-id>` for the offline-clone harness;
- `websitebench--<site-id>` for canonical WebsiteBench site manifests.

Review and review-export payloads use the version-2 schemas. Importing a
version-1 export upgrades canonical keys in memory, and maps the historical
`offline-clone--<site-id>` spelling to `offlineclone--<site-id>`. The retired
`legacy--*` task adapters have no canonical benchmark target, so their reviews
are rejected with an explicit migration error rather than being attached to a
different site.

Before upgrading a workspace that still contains `legacy--*.json` review files
or visual manifests, archive those files outside the active Viewer artifact
root. They remain historical records and are not automatically deleted or
silently imported.

Result reports may include an optional `candidate` object with `model_id`,
`display_name`, `provider`, `harness`, and `reasoning_effort`. The viewer uses
that metadata to build stable model groups and the evaluation matrix. Older
reports without it remain valid and appear under an unspecified candidate.

The public profile is built from
`websitebench/viewer-public-allowlist.json`. Its recursive leak check rejects
private fixture markers, internal commands, internal path fields, and absolute
workspace paths. Review writes and imports are disabled in that profile.

## Static publishing and deployment

`publish` renders every public overview, catalog, model, website, and run route
to path-safe static HTML, copies the public index and visual assets, and emits a
site manifest. The generated directory can be served by any static host.

## Cloudflare deployment

[`compose.yaml`](../deploy/websitebench-viewer/compose.yaml) runs the viewer and
Cloudflare Tunnel. Create five external Docker secrets named
`viewer_username`, `viewer_password_hash`, `viewer_session_secret`,
`viewer_trusted_hosts`, and `cloudflare_tunnel_token`. The trusted-host secret
contains the assigned hostname plus `localhost`. Cloudflare terminates TLS and
the application keeps the session cookie `Secure`, `HttpOnly`, and
`SameSite=Strict`.

The Dockerfile-specific ignore list excludes the repository `.env`, configured
model credentials, local artifacts, and test outputs from the image build
context.

The first deployment intentionally uses the authenticated `internal` profile.
No hostname, password, session secret, or tunnel token belongs in the repo.
