# Offline clone implementation brief

Work on the configured site, route/state matrix, runtime and writable roots.
Do not expand scope. Record source evidence, target viewports, roles, states,
journeys and non-goals. Mark claims as directly observed, structural-only,
machine-inferred or unavailable.

Follow `docs/source-evidence-access-policy.md`. In-scope acquisition from
first-party, external, internal and authenticated surfaces is allowed. Reuse
the available session and keep credentials and session secrets out of code and
evidence. Use WebsiteBench/Playwright for source exploration, navigation,
interaction, visual/layout inspection, asset acquisition and formal validation.

Build and verify in this order:

1. Localize images, fonts, icons, styles and runtime assets; preserve
   provenance and require zero runtime requests to the source site.
2. Match the route/state/viewport matrix, including loading, empty, error,
   overlay, responsive, keyboard and touch behavior where applicable. This walk
   produces two outputs, not one. Alongside the matrix, record the interaction
   ledger for every route you exercise: the exact clone URL, the selector of
   each control you activate, one visible-text string and one raw-markup string
   that prove the route rendered, and the form action behind each mutation. The
   ledger costs nothing extra here and is the only place selectors ever come
   from; no frozen scope artifact contains one.
3. Before persistent auth, email, payment, order or database work, read
   `docs/websitebench-site-backend-mandate.md`, record applicability and run
   `websitebench-offline-clone backend scaffold --site <site-dir>` when needed.
   Use its `backend/runtime.json` and WebsiteBench integration seam. Keep site
   IDs, SQLite databases, volumes, session namespaces, Redis tickets, payment
   flows and webhook secrets isolated.
4. Implement required server semantics. Enforce identity, ownership,
   authorization, transitions, validation, idempotency, concurrency,
   persistence, migration, restart and reset at the server boundary. Payments
   default to `local-sandbox`; live keys are forbidden.
5. Resolve semantic ambiguity mechanically: P0/P1 use `full-local-model`; P2
   uses `truthful-simulation`. Preserve certainty, evidence references and
   machine rationale.
6. Create the same-id `harbor/sites/<site-id>` and
   `harbor/instances/<site-id>` pair with `websitebench-harbor init-site` and
   `init-instance`. For a new site, retain the generated empty draft case,
   task, visual, and CI/CD files; do not copy another site's test content.
   Confirm `validate` reports `status: draft`, `scorable: false`, and the
   missing count for the exact 200-case protocol. The generated deployment
   contract is `compile.sh -> executable` with `HOST`, `PORT`, `DATA_DIR`,
   `SEED`, `TZ`, dual formal browsers, and exact
   `/__websitebench/health` JSON. Then derive the Harbor interaction contract
   from what the build already captured; do not defer it to a later Harbor
   phase. Run `websitebench-harbor derive-from-clone --clone-manifest
   materials/<site-dir>/clone.yaml`, assigning the derived profile to the
   unique instance when requested. The command returns a `pending` work list
   and writes the contract plus adapters directly. Tighten the inputs from the
   step 2 ledger: fill every `selector`, resolve each pending entry, remove steps
   the ledger cannot support, and rerun with `--force`. Then start the clone and replay each profile with
   `websitebench-harbor run-opencli --target candidate`. Put exactly one artifact
   per profile under
   `harbor/sites/<site-id>/interactions/replay-evidence/<profile-id>.json`, then
   repair until its `target` is `candidate`, its origin is HTTP(S) loopback, its
   allowlist matches the profile, and each step completes without errors or
   assertion failures. Replay quickly catches a dead route or moved selector
   before the Playwright and visual passes in step 7. Replay results stay
   advisory: they create no trace coverage and do not decide acceptance. If the
   `opencli` binary is unavailable, record `opencli-unavailable` and continue.
7. Run narrow checks after each change and then the full relevant suite.
   Preserve screenshots, traces, HTTP evidence, network audits and exact
   candidate/runtime identity. Continue repairing machine-detected differences
   until checks pass or evidence is unavailable.

Return changed paths, commands and results, current machine status, known
differences and unavailable evidence, plus the derived contract path, its
each profile's replay summary and every unresolved `pending`
entry. The generic diagnostic report states only `clean`, `findings`, or
`incomplete`; every state requires maintainer judgment.
