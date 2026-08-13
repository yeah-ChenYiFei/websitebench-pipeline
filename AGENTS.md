# Repository agent instructions

WebsiteBench offline-clone work uses configuration-driven machine diagnostics.
The request supplies the source scope, URLs and any usable authenticated
session. Agents may continuously acquire evidence, implement, run validation
and repair machine-detected differences without a manual checkpoint.

## Canonical naming and historical identity

`WebsiteBench` is the repository's canonical product, CLI, Python namespace and
vendored runtime name. Older `clawbench` names are compatibility-only for
existing scripts, immutable evidence and already-created clone runtimes. Do not
introduce them in new code, documentation, configuration or clone candidates.

Do not rename, normalize, regenerate or reinterpret historical ClawBench
trajectory records, evidence payloads or hashes, corpus identifiers, captured
artifacts, already-vendored runtime trees, compatibility schemas or recorded
command strings. Those values are immutable data identity unless a separately
scoped, evidence-preserving migration names the exact compatibility plan.
Historical review records and legacy schemas may be parsed explicitly, but
they never substitute for a current diagnostic report or maintainer judgment.

## Source evidence and secrets

For real-site evidence work, follow `docs/source-evidence-access-policy.md`.
Downloading in-scope media and files and taking screenshots from first-party,
third-party, internal and authenticated surfaces is allowed. Use only the
configured origins and available session. If login material is unavailable,
report the inaccessible surface and continue with the remaining configured
scope.

Never persist credentials, cookies, authorization headers, session secrets,
payment data or sensitive form values in the repository, logs, screenshots or
evidence artifacts. Do not expand source origins or production side effects
beyond the configured task scope.

## Harbor OpenCLI contracts

OpenCLI support in this repository is limited to Harbor interaction contracts
for offline clones the repository owns and serves on `127.0.0.1`. Source-site
exploration and formal evidence acquisition use the configured
WebsiteBench/Playwright paths under `docs/source-evidence-access-policy.md`.

The walk that produces the route/state/viewport matrix also produces the
interaction ledger, and the interaction contract is derived from artifacts the
build already captured. Contract authoring belongs to the clone build, not to a
later Harbor phase; see `prompts/offline-clone/build.md` step 6.

### Contract replay against local clones

See `docs/opencli-contract-replay.md`. Each current Harbor site has exactly one
same-id instance and may declare one interaction contract.
`websitebench-harbor derive-from-clone` writes the contract and its adapters
from the clone's captured artifacts, `websitebench-harbor run-opencli` replays a profile
against a running local target, and `websitebench-harbor opencli-adapters`
generates the `browser: false` adapters it uses. Because the subject is our own
fixture on `127.0.0.1`, that path is allowed a repository wrapper, CLI, schema
and Harbor authoring contract.

Replay results are advisory on the same terms: no trace coverage, no acceptance
decision, and
the runner exits `0` even when steps fail so it cannot become one. Never wire
replay into a scoring verifier or a merge condition.

## Backend and payment safety

Before implementing or changing persistent accounts, password recovery,
transactional email, checkout, payment, orders or a database for a new offline
clone, read `docs/websitebench-site-backend-mandate.md` and record whether each
capability is in scope. If any are in scope, run:

```powershell
websitebench-offline-clone backend scaffold --site <site-dir>
```

The generated `backend/runtime.json` is the only runtime contract. Do not
replace it with custom auth, mail or payment wiring; infer a business schema
from a capability pack; copy Amazon-specific fields or Stripe logic; share a
database or volume across `site_id` values; or create a parent-domain session
cookie. Use `websitebench.site_backend` through the generated integration seam.

Every site must have distinct database/volume identity and mail branding.
`local-sandbox` is the default payment adapter. `stripe-test` is allowed only
when the active machine payment-scope contract and profile checks pass. Live
keys and live payment credentials are always forbidden.

Before completion, run the applicable backend and isolation tests and report
the runtime path, unique `site_id`, database/volume identity, enabled mail
purposes, payment profile, deployment profile and any failed machine checks.

## Shared offline-clone tools

All agents must discover cross-site clone diagnostics through:

```powershell
python tools/offline_clone/run.py tools list
```

The shared tool group provides approved-origin browser exploration, functional
source/candidate comparison, region visual comparison and
actor-isolated backend semantic testing. Use the versioned declarative specs
under `tools/offline_clone/specs/`; do not copy a site-specific check into a new
generic tool. These reports are diagnostic inputs only and never satisfy a
quality or release decision by themselves.

Source exploration blocks non-GET requests unless the exact scenario records
authorization and the command explicitly opts in. Backend semantic tests target
loopback by default. Inject sensitive inputs from environment variables; never
put them in specs or reports.

The installed `websitebench-offline-clone tools ...` command is equivalent.
Prefer the repository-local launcher when the checkout path is non-ASCII or the
package has not been installed.

Agent-generated code, assets, fixtures, tests, reports and repair decisions are
eligible for every technical workflow stage. Current, reproducible machine
evidence is the recommended way to check an offline clone's fidelity
at any stage. These checks are diagnostic aids: passing or failing them does
not by itself decide whether a clone, PR, or deployment is complete — that
remains a human/agent judgment call informed by the evidence.
Machine evidence is evaluated by content; author-based approval has no technical gate status.

This autonomy does not authorize new production effects. Credentials, live
payments, messages, external publication and other irreversible effects remain
subject to the configured task authority and the safety rules in this file.

## Machine diagnostic status

Every offline clone is diagnosed by the same two sections, run per site:

```bash
websitebench-offline-clone verify --site materials/<site-id>
```

The report schema is `offline-clone.diagnostic-report.v1`; its authority is
`diagnostic-only`, its qualification is `maintainer-judgment-required`, and its
status is `clean`, `findings`, or `incomplete`. `static` reads the declared
contracts, the asset closure and the shipped files;
`live` boots the clone and walks its configured checkpoints in a browser. Site
knowledge belongs in that site's `scope/verify.json` — route aliases, state
recipes, routes an anonymous diagnostic cannot reach — never in a per-site
script. Adding a site adds data, not code. Preserve unrelated dirty work.
There is no repository-wide project plan or global evidence gate.

Diagnostics are a pure function: they run, print a report and exit. Nothing is
stored, so no earlier result can be inherited. Findings exit `0`; invalid input
or incomplete execution exits `2`. Neither outcome decides whether a clone may
merge or deploy. A clean run is not copyright, redistribution, legal,
deployment or external-publication authorization.
Secret protection and payment safety (see "Backend and payment safety" above)
remain mandatory. The sections cover structure, network closure, route
reachability and region-level visual comparison; everything else a site claims
rests on its own tests and on honest reporting. Maintainers decide from the
scope, implementation, tests, evidence, coverage gaps and diagnostics together.
