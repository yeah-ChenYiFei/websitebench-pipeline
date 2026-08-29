# One repository, one persistent branch per site

WebsiteBench keeps shared Pipeline code on `main`. Every delivered website has
one persistent branch named `sites/<site-id>` in the same GitHub repository.
Each site branch contains the Pipeline plus only that site's material tree.

`sites/status.tsv` is the assignment snapshot for the 331-site catalog. A
`final` branch contains the maintainer-confirmed snapshot, `review` preserves an
existing PR snapshot without claiming acceptance, `review-required` marks a
closed-unmerged PR that needs explicit inspection, and `planned` is an empty
Pipeline-only branch for a site with no submitted PR.

This layout creates no extra repositories and needs no Git LFS, GitHub Actions,
or paid storage service. It does rely on contributors using an explicit shallow
single-branch clone. GitHub cannot force a plain `git clone URL` to ignore the
other branches.

## What each branch contains

| Branch | Content | Pull requests target |
| --- | --- | --- |
| `main` | Pipeline runtime, schemas, shared tools, docs and site-independent tests | `main` |
| `sites/<site-id>` | Everything on `main`, plus exactly one site material tree | `sites/<site-id>` |
| temporary contributor branch | A short-lived change based on one site branch | its matching `sites/<site-id>` |

`sites/registry.json` maps the public site id to its historical material path.
For example, `sites/coursera` currently maps to `materials/33`; migration must
preserve that identity unless a separate compatibility change is reviewed.
The plural `sites/` namespace is intentional: 44 of the requested names already
exist under the older `site/` working-branch namespace, while `sites/` had no
collision at the audit snapshot. This lets migration proceed without force
pushing an active PR branch.

## Clone only the Pipeline

```bash
git clone --single-branch --branch main --filter=blob:none --depth=1 \
  https://github.com/780078268/websitebench-pipeline.git
cd websitebench-pipeline
python scripts/site_workspace.py list
```

The initial checkout contains no delivered website. `--single-branch` is the
important part; `--filter=blob:none` and `--depth=1` reduce the transfer further.

## Contribute to one site

Ask the helper for a copy-pasteable command:

```bash
python scripts/site_workspace.py command coursera
```

It prints a clone command equivalent to:

```bash
git clone --single-branch --branch sites/coursera --filter=blob:none --depth=1 \
  https://github.com/780078268/websitebench-pipeline.git websitebench-coursera
cd websitebench-coursera
git switch -c fix/coursera-<short-description>
```

Push the temporary branch to a fork or the origin allowed for that contributor,
then open the PR with `sites/coursera` as the base. Never target `main` with a site
implementation PR.

## Review one site from an existing main checkout

Fetch and materialize only the persistent site branch in a sibling worktree:

```bash
python scripts/site_workspace.py checkout coursera
```

The helper performs a shallow, blob-filtered fetch of exactly
`refs/heads/sites/coursera`, then adds a detached worktree such as
`../websitebench-pipeline-coursera`. Other sites remain on GitHub.

To review a PR after its base has been migrated to the persistent site branch:

```bash
python scripts/site_workspace.py review coursera --pr 123
```

The helper first verifies through GitHub that PR 123 targets `sites/coursera`.
It then fetches only `refs/pull/123/head` and creates a detached sibling
worktree. A PR targeting `main` or another site's branch is rejected.

Removing a worktree does not remove Git objects already fetched into the local
object database. A fresh shallow clone is the simplest way to guarantee a
minimal local object store.

## Pipeline changes and propagation

Shared Pipeline fixes are reviewed against `main`. Git does not automatically
copy a later `main` commit into the persistent site branches. Maintainers should
periodically merge `main` into each active `sites/<site-id>` branch using an
explicit, auditable maintenance change. Do not silently overwrite site work.

If a shared fix is urgent for one site, merge it into that site's branch first
and record the resulting commit. A later batch propagation can update the
remaining branches.

## Migration from the existing large repository

The migration is branch construction, not a history rewrite:

1. Freeze the exact source PR head SHA for a site.
2. Start a new `sites/<site-id>` commit from the chosen slim `main` commit.
3. Restore only the registered `materials/<material-id>` subtree from the
   frozen source SHA.
4. Normalize required metadata such as `clone.yaml` without changing historical
   site identity.
5. Run the site tests and Pipeline diagnostic in an isolated worktree.
6. Push the persistent branch only after its tree and base are rechecked.
7. Change future PR bases to the persistent site branch.

Do not delete old refs, force-push `main`, or rewrite existing history during
this phase. Those are separate destructive operations and are unnecessary for
the single-branch contributor workflow. Keeping old refs means that an ordinary
unqualified clone can still be large; the supported clone commands above avoid
that transfer.

The current catalog snapshot is recorded in `sites/registry.json`; the original
202-site migration audit remains in `docs/site-branch-migration-audit-2026-08-28.md`.
A recorded PR or directory proves a recoverable Git
snapshot, not merge, deployment, fidelity acceptance, or legal redistribution
approval.
