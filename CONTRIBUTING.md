# Contributing offline clones

New clone work should follow the resource-first workflow documented in
[`docs/offline-clone-harness.md`](docs/offline-clone-harness.md):

1. Freeze the site's purpose, core journeys, semantic invariants, and explicit
   non-goals before implementation.
2. Capture a stable source baseline and close the required local resource set.
   Real-site media/files and screenshots are allowed and encouraged across
   first-party, external, internal, and authenticated surfaces. Request needed
   login access from the configured session authority and reuse the authorized
   session for the bounded task; follow
   [`docs/source-evidence-access-policy.md`](docs/source-evidence-access-policy.md).
3. Build and visually verify the frontend route/state matrix before expanding
   backend behavior. Record the interaction ledger as you walk: the clone URL,
   each activated selector, one visible-text and one raw-markup proof per route,
   and the form action behind each mutation. No frozen scope artifact contains a
   selector, so this walk is the only place they come from.
4. Implement only the backend semantics needed by the frozen journeys, with
   server-side validation and deterministic reset behavior.
5. Derive the Harbor interaction contract directly from the artifacts the
   build froze with `websitebench-harbor derive-from-clone`,
   resolve its `pending` list from the ledger, and replay each profile against
   the local clone with `websitebench-harbor run-opencli`; see
   [`docs/opencli-contract-replay.md`](docs/opencli-contract-replay.md). Use
   `--reconcile` for a hand-authored contract. Replay results are advisory and
   never gate a release.
6. Iterate through evidence-backed functional and visual diagnostics. Reports must
   distinguish directly compared, structural-only, unavailable, and inferred
   states.
7. Keep credentials, session secrets, private user data, browser profiles,
   runtime databases, and generated artifacts out of Git.
8. Document source ownership, redistribution limits, simulations, and known
   fidelity gaps without overstating completion.

The lifecycle, ownership model, definitions of done, and expansion policy are
defined in [`PROJECT.md`](PROJECT.md). Keep scope, evidence, blockers, and
current diagnostic reports with the affected site; no repository-wide plan
controls implementation or release.

Run before committing:

```bash
ruff check src tests websitebench
python -m pytest tests/project tests/offline_clone tests/harbor tests/viewer -q
python -m pytest materials/tripit/clone/tests -q
```

Every clone exposes the same two diagnostic sections -- `static` needs nothing,
`live` boots the clone in an isolated browser walk -- and CI runs them per site as
`.github/workflows/tests-<site>.yml`. Run the site you touched; add
`--section static` for the fast half:

```bash
python -m websitebench.offline_clone.cli verify --site materials/<site>
```

Full-stack benchmark instances must follow
[`docs/harbor-fullstack-benchmark.md`](docs/harbor-fullstack-benchmark.md).
Keep reusable website contracts under `harbor/sites/`, task-specific overlays
under `harbor/instances/`, and generated Harbor bundles under the ignored
`harbor-dist/`. Browser Use CLI is the Agent exploration path; trusted
Playwright and direct HTTP checks are the formal scoring path.

Agent-generated code and evidence are valid inputs to every technical stage.
Evaluate them by the same reproducible diagnostics as any other contribution;
`clean`, `findings`, and `incomplete` all require maintainer judgment. Do not add
signature-by-author, manual-browser or author-identity gates.

Start a new contribution with the non-deployable scaffold, then create its
diagnostic handoff bundle:

```bash
websitebench-offline-clone contribution init --repo . --site-id <site-id> \
  --display-name "<name>" --source-url https://example.test/
websitebench-offline-clone contribution report --site materials/<site-id> \
  --out contribution-report.json --bundle-out contribution-handoff.zip
```

The default backend profile is `full`; select `--backend-profile none` only when
every persistent/backend capability is explicitly not applicable. Contribution
scaffolding never creates a Harbor instance or public deployment dispatcher.

When a change affects scope, isolation, scoring, authoring layout, release
evidence, or corpus expansion, update the machine-verification guide, reusable
prompt briefs, schemas, tools, and tests that are actually affected.
