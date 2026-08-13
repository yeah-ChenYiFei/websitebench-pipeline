<!-- Phases 1–2: repository preflight and read-only network reconnaissance -->

> This file is a phase reference for `prompts/offline-clone/autonomous-source-to-clone.md`.
> **The operating rules in the entry prompt—authorization, autonomous decision boundaries, stopping rules, parallelism, and context—take precedence over this file.**
> Previous: start | Next: `02-task-brief.md`

## Phase 1: repository preflight

Before creating a site or modifying a candidate, read all of the following:

- the current and any in-scope `AGENTS.md` files;
- `skills/trace-guided-offline-clone/SKILL.md` and its required references;
- `prompts/offline-clone/build.md`;
- `docs/codebase-offline-site-clone-workflow-zh.md`;
- `docs/source-evidence-access-policy.md`;
- `docs/opencli-contract-replay.md`;
- `docs/websitebench-site-backend-mandate.md`;
- `docs/browserbase-chrome-devtools.md`; and

Run:

```bash
python tools/offline_clone/run.py tools list
websitebench-offline-clone --help
websitebench-workflow --help
websitebench-harbor --help
```

Inspect the worktree and preserve all unrelated and pre-existing user changes.
Inspect these locations to prevent a new site from colliding with an existing
site ID, directory, Worker, or deployment descriptor:

- `materials/`
- `.github/workflows/`
- `websitebench/site-profiles/`

At this point, do not run `init`, modify the candidate, create an account, log
in, submit a source-site form, or cause any source-site side effect.

If the current execution environment is in plan-only mode, finish deriving
this brief and output the plan first, then continue after approval. Otherwise,
continue immediately after the brief validates. Do not add a pause merely for
human review; plan mode supplies review checkpoints. Branches that require a
human handoff or new authorization must still stop as usual.

## Phase 2: read-only network reconnaissance

Derive task fields from public-network information. Investigate in this order:

1. the input URL and its canonical redirect;
2. the home page's primary navigation, footer, and major calls to action;
3. `robots.txt`, sitemaps, and public routes;
4. official About, Product, Pricing, Help, Docs, and FAQ pages;
5. the public structure of official sign-in and registration entry points;
6. `site:<canonical-domain>` searches for missed official pages; and
7. when necessary, official app-store listings or official social profiles to
   confirm the brand name, never as a substitute for product-behavior evidence.

Evidence priority is:

```text
first-party directly observed
> first-party official documentation
> first-party search-discovered page
> trusted third-party description
> inference
```

Search snippets and third-party pages may help discover leads, but cannot prove
visual appearance, interaction, fields, error copy, or submission semantics.

Initially and automatically allowed discovery origins include only:

- the input URL's origin;
- the canonical redirect's origin; and
- subdomains under the same registrable domain that the canonical page links
  explicitly.

Approved external resource origins actually requested by the page may enter the
asset-observation list. External help, auth, payment, CDN, or service domains go
into `proposed_additional_origins`. Do not log in, interact, or mutate them
solely because they appeared in search results.

Only public GET/HEAD requests are allowed in this phase. Do not register, log
in, send email, invite users, start a trial, upload, check out, pay, or modify
source-site state.
