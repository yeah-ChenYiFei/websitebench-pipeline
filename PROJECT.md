# WebsiteBench site workflow

WebsiteBench evaluates offline website clones through independently verifiable
site contracts. There is no repository-wide project plan, status CLI, or
cross-site release gate.

## Current technical state

Use the affected site's v2 manifest and current diagnostics to inspect its
technical-verification state:

```bash
websitebench-offline-clone status --site materials/<site-id>
websitebench-offline-clone verify --site materials/<site-id>
websitebench-workflow --help
```

Technical verification is not a deployment, rights, redistribution, or payment
authorization. Those decisions remain scoped to the selected site and release.

## Site lifecycle

1. Define the site's purpose, core journeys, route/state matrix, semantic
   invariants, and explicit non-goals.
2. Acquire the configured source evidence and close the required local resource
   set without persisting credentials or session secrets.
3. Build the route/state/visual surface, recording the interaction ledger while
   walking the clone.
4. Implement only the backend semantics required by the declared journeys, with
   deterministic reset and server-side invariants.
5. Derive the Harbor interaction contract and adapters from the clone's captured
   artifacts; replay is diagnostic and does not decide a release.
6. Run the selected site's functional, visual, browser, backend, isolation, and
   technical-verification checks. Record real, site-scoped blockers beside the
   affected evidence.
7. For Harbor work, author and calibrate the instance independently. NOP,
   oracle, repeatability, visibility, and network checks do not substitute for
   source evidence or release authority.

## Definitions of done

### Site

- Scope contract, route/state matrix, semantic invariants, and non-goals are
  explicitly defined.
- Runtime is offline: no remote image, font, API, or telemetry dependency.
- Core routes and states have direct browser evidence; unavailable or inferred
  states are explicitly labeled.
- Backend enforces identity, authorization, validation, and state-transition
  invariants with deterministic reset behavior.
- The current manifest, declared inputs, and reproducible evidence support the
  reported technical state.
- Ownership, redistribution limits, simulations, and known fidelity gaps are
  documented without overstating completion.

### Harbor site-instance pair

- Every current site has exactly one same-id instance; journeys are hidden
  tasks inside that instance.
- `instance.yaml` passes its schema and semantic checks.
- Agent-visible material excludes reference source, verifier, hidden fixture,
  and oracle content.
- Task, visual, and CI/CD suites cover the complete declared site scope and
  remain verifier-only.
- NOP, oracle, repeatability, automated-browser, visibility, and network
  evidence are current for the exact bundle.

## Responsibilities

| Role | Responsible for | Does not replace |
| --- | --- | --- |
| Site-instance author | Scope, source evidence, clone semantics, instruction, hidden suites, reset, oracle | Independent verifier scoring |
| Verifier author | Differential checks, isolation, calibration | Candidate implementation |
| Release manager | Release and redistribution decisions (deployment itself is outside this repository) | Missing evidence or authority |

Agent-produced code and evidence are evaluated by the same reproducible
machine checks as any other contribution. Author identity or a manual sign-off
does not create technical authority.

## Change control

When a change affects a site, update the site contract, evidence, schemas,
tools, and tests that actually consume it. Preserve unrelated dirty work and
historical evidence. Before merging, run the affected site suite plus relevant
shared checks, for example:

```bash
ruff check src tests websitebench
python -m pytest tests/offline_clone tests/harbor -q
python -m pytest materials/<site-id>/clone/tests -q
```
