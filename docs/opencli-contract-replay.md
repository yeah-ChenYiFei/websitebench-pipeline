# OpenCLI contract replay against local clones

This Harbor-only convention applies to an offline clone this repository owns,
served on `127.0.0.1`. Nothing here ever touches an upstream origin or performs
source-site reconnaissance.

**Results are advisory.** A replay artifact creates no trace coverage and
satisfies no source, frontend, Harbor, merge or release decision. The runner exits `0`
whenever it produced an artifact, including when steps fail, precisely so that
wiring it into CI cannot turn it into a gate by accident. Scoring dimensions,
`verifier/run.py` and calibration evidence are untouched by this path.

## The contract is the source of truth

Each site declares one contract:

```yaml
# harbor/sites/<site-id>/site.yaml
opencli:
  version: 1.8.6
  contract: interactions/opencli-interaction-contract.json
  network_requirements:
    allowlist: [127.0.0.1, localhost]
```

The contract holds named profiles; a profile holds ordered steps. It is
validated by `websitebench/schemas/harbor-opencli-interaction-contract.schema.json`
at authoring time, and it drives both adapter generation and replay.

**Conditional requirement:** every current site has exactly one same-id instance.
The moment its `site.yaml` gains an `opencli` block, that instance must select a
real `opencli_profile`. Land the site block, contract and unique instance update
together. Historical v1 task records keep their original per-task selections and
are read only through the explicit legacy path.

### Executable verbs

`state`, `click`, `submit` — enforced at dispatch in
`src/websitebench/harbor/opencli/backends.py`, deliberately not as a schema
`enum`. The schema is a portable authoring contract duplicated into the viewer
wheel and embedded into already-materialized bundles; the verb set is a
capability of one executor version. Coupling them would make every new verb
retroactively invalidate shipped bundles.

On a server-rendered clone a `click` is usually a form submission: the runner
resolves the selector, finds its enclosing `<form>`, serializes the controls and
issues the form's own method and action. `submit` is the same machinery without
the anchor branch.

### `required_state` is graded in two halves

Contract `required_state` mixes machine-checkable values with author prose.
Asserting the prose produces false failures; passing it silently produces false
confidence. So each observation carries an `asserted` flag, and only asserted
observations can fail a step.

| Assertable | Descriptive (recorded, never graded) |
| --- | --- |
| `title`, `visible`, `list_contains`, `link_text`, `favorite_absent`, `text_absent`, `animal_id`, `body_contains`, `required_fields` | everything else, including `action`, `expectation`, `expects` |

`summary.unasserted_observations` reports how many entries were recorded but not
graded, so prose never hides behind a green run.

**`visible`, `list_contains`, `link_text` and `text_absent` are matched against
the page with every tag stripped and every entity decoded.** An attribute
fragment or an `&amp;` written into one of them fails against a *perfectly
correct* clone, which is the worst failure this system can produce: it sends the
agent to repair something that is not broken. Markup belongs in `body_contains`,
which matches the raw document minus `<script>` and `<style>` bodies. It is the
more brittle key by construction — prefer visible text whenever the expectation
can be written as visible text.
`tests/harbor/test_opencli_contracts.py` enforces the split corpus-wide.

### Optional profile `session`

Owner-scoped steps need a session before step 1. A profile may declare one:

```json
"session": {
  "route": "fixture/session",
  "method": "POST",
  "fields": {"csrf": "petfinder-r2-public-fixture", "account": "alex-green"}
}
```

This is setup, not a measured interaction: it is not a step and never appears in
the step tally. Values must be public local fixtures — constants that already
live in the reference implementation — never real credentials. The artifact
records field **names** only, and the issued cookie never reaches it.

Where the CSRF token is per-request rather than a constant (edX), skip the
precondition and use a `submit` step instead: the adapter fetches the form,
picks up the live token, and applies the step's `fields` overrides.

## Backends

| Backend | Transport | Works headless |
| --- | --- | --- |
| `adapter` (default) | generated `browser: false` adapters over plain HTTP | yes |
| `browser` | `opencli browser <session> <cmd>` | only when `opencli doctor` is green |

`opencli browser` requires the Chrome Browser Bridge **extension**:
`getBrowserFactory` in OpenCLI returns the raw-CDP bridge only for registered
Electron apps and routes every other site through the extension-backed
`BrowserBridge`. `OPENCLI_CDP_ENDPOINT` is honoured on the Electron path only,
so there is no raw-CDP fallback. Requesting `--backend browser` while the bridge
is down is refused with exit `2` rather than failing obscurely at step 1;
`--backend auto` degrades to `adapter` and records `opencli-unavailable` in the
artifact's `degradation` list.

The adapter backend emulates a browser form post faithfully, including the
`Referer` and `Origin` headers that CSRF-checking clones require. It only ever
sends the page the form was actually fetched from.

## Generating adapters

```bash
websitebench-harbor opencli-adapters --site harbor/sites/petfinder/site.yaml
websitebench-harbor opencli-adapters --site harbor/sites/petfinder/site.yaml --check
websitebench-harbor opencli-adapters --site harbor/sites/petfinder/site.yaml --install
```

Adapters are generated from templates under
`src/websitebench/harbor/opencli/templates/` into
`harbor/sites/<site-id>/interactions/adapters/` — four files per site, one per
command plus a shared helper. They are committed so they are reviewable, and
`--check` (mirrored by `tests/harbor/test_opencli_adapters.py`) fails if the
committed files drift from the generator.

`--install` copies them into `~/.opencli/clis/wb-<site-id>/`, where OpenCLI picks
them up with no build step. The `wb-` prefix is **mandatory**: OpenCLI ships 163
official site adapters including `amazon` and `imdb`, and an unprefixed
directory would silently override one. `--install` mutates the user's home
directory, so it is opt-in and never runs from a test.

Static validation needs neither network nor browser and works today:

```bash
opencli validate wb-petfinder
opencli list -f json | jq '.[] | select(.site == "wb-petfinder")'
```

## Deriving a contract

The clone build's route/state walk writes `tools/frontend_samples.json` and the
site scope files. Derivation reads those structured artifacts and writes the
contract plus generated adapters directly:

```bash
websitebench-harbor derive-from-clone \
  --clone-manifest materials/<site-id>/clone.yaml
```

The current same-id instance must already exist and select a profile defined by
the generated contract. When adding the contract, use
`--assign-profile <site-id>=<profile>` if its selection needs to be set, and use
`--force` only when intentionally replacing an existing contract. Unresolved
selectors and routes are returned in the command's `pending` list; no derivation
sidecar or stored drift state is created.

## Running a replay

The canonical replay target is the running clone under `materials/<dir>/clone`,
not the Harbor reference tree. `--target candidate` is the default.

```bash
python scripts/serve_all_clones.py start

websitebench-harbor run-opencli \
  --site harbor/sites/taskrabbit/site.yaml \
  --profile signin-to-booking-flow \
  --target candidate \
  --base-url http://127.0.0.1:8452 \
  --out harbor/sites/taskrabbit/interactions/replay-evidence/signin-to-booking-flow.json
```

`--base-url` must be HTTP(S) loopback and its host must appear in the profile's
network allowlist. `--no-reset` skips the local reset call. `--admin-token`
supplies the reset credential explicitly; otherwise the CLI reads
`WEBSITEBENCH_ADMIN_TOKEN`. Sensitive values are runtime-only and never enter
the artifact. `--force` permits overwriting an existing result.

Replay artifacts use `websitebench.harbor.opencli.replay-result.v1`. Each step
records its outcome, declared route, HTTP status, duration and sanitized
observations. The top level records the selected profile, target binding,
OpenCLI doctor report, summary and degradation notes. It carries
`"authority": "diagnostic-only"` and no content or contract digest.

| Exit code | Meaning |
| --- | --- |
| `0` | an artifact was written, regardless of step outcomes |
| `2` | no artifact could be produced |

Replay evidence is advisory. It creates no trace coverage, does not affect
Harbor scoring or calibration, and does not decide acceptance, merge or release.
When retained, place it at
`harbor/sites/<site-id>/interactions/replay-evidence/<profile-id>.json`.
Temporary `test-output/` artifacts can inform local debugging but cannot replace
the committed evidence path when a repository fixture intentionally retains a run.
Contract loading, site/profile mapping, generated-adapter parity and replay
behavior are covered by the Harbor tests.

## Adding a site

1. Capture the route/state walk, interaction ledger and frontend samples during
   the clone build.
2. Initialize `harbor/sites/<site-id>` and its unique
   `harbor/instances/<site-id>` pair, then give the site unique verifier ports.
3. Run `derive-from-clone`, assigning the unique instance profile when needed.
4. Resolve the returned pending items from the interaction ledger and rerun with
   `--force` when the generated contract must change.
5. Run `opencli-adapters --check`, replay each profile against the loopback clone,
   and run `python -m pytest tests/harbor/`.

Historical replay evidence remains immutable input. It can be read for audit
context, but it is not rewritten or promoted by the current derivation flow.
