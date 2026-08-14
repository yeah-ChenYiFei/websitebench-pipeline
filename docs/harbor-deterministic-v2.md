# Harbor v2 deterministic evaluation

Harbor v2 evaluates an offline website reconstruction with deterministic
contracts. The active deployment ABI is
`websitebench.harbor.compile-executable.v1`; the active scoring input is one
sealed 200-case manifest and one exact 200-result set. There is no
LLM-as-Judge component.

## Active deployment ABI

A new `websitebench.harbor.site.v2` manifest declares:

- `runtime.deployment_abi: websitebench.harbor.compile-executable.v1`;
- compile entrypoint `compile.sh` and runtime entrypoint `executable` at the
  candidate root;
- runtime variables `HOST`, `PORT`, `DATA_DIR`, `SEED`, and `TZ`;
- health endpoint `/__websitebench/health`, which must return HTTP 200 and the
  exact JSON value `{"status":"ok"}`;
- `formal_browsers: [playwright, browser-use]`, eight logical shards, and at
  most four concurrent workers.

`compile.sh` is executable, takes no arguments, and has 900 seconds by default.
The verifier first quarantines `/app/repo` into a private build root. Symbolic
links, hard links, special files, unsafe paths, and pre-existing build output
are rejected; a submitted `executable` is deleted before compilation. The
compiler runs without public network access and with CPU, memory, file and log
limits. A successful compile must leave no child process or listener and must
produce one independent regular executable at the build root. The complete
build tree is hashed and frozen read-only.

Every formal case receives a fresh runtime and `DATA_DIR`. The build stays
read-only, and Landlock permits runtime writes only under that data directory.
The verifier checks foreground lifetime, exact health output, a graceful
ten-second SIGTERM, restart with the same data directory, persistence, and
isolation from a fresh data directory. A stop whose process-group cleanup does
not complete forbids restart.

## Case manifest

`websitebench.harbor.case-manifest.v1` supports three states:

- `draft`: may contain no cases and is not scorable;
- `complete`: authoring form with exactly 200 cases;
- `sealed`: bundle-only projection of a complete manifest.

The fixed distribution is:

| Tier or level | Count |
| --- | ---: |
| T1 | 20 |
| T2 | 165 |
| T2/L1 | 35 |
| T2/L2 | 50 |
| T2/L3 | 80 |
| T3 | 15 |
| Total | 200 |

T2 cases are journeys. T1 and T3 are direct HTTP/API or trusted CI/CD cases.
Every task, visual checkpoint, and CI/CD check in the three hidden suites is
referenced exactly once by the manifest; duplicate, missing, extra, or dangling
IDs are rejected.

New scaffolds intentionally contain empty case, task, visual and CI/CD suites
with `status: draft`. Validation succeeds and reports `status: draft`,
`scorable: false`, the current counts and the missing counts. Capture,
materialization, calibration, and scoring reject a draft with exit code 2. Site
authors fill the current site's private case data; the repository does not
provide test content for a new site.

## Formal execution

Journey actions use a Playwright-neutral deterministic DSL with explicit
terminal observations. The same declaration is compiled into two independent
candidate runs:

1. pinned Playwright 1.61.0; and
2. pinned Browser Use 0.12.6 in `/opt/websitebench/browser-use-0.12.6`.

Both runs use a fresh candidate runtime, data directory, browser context and
profile. Both must match the declared terminal observations or the case's
functional value is zero. Browser Use is exposed only as a deterministic CDP
transport. Agent `run`, `extract`, `eval`, Python execution, cloud, profile,
tunnel, MCP, and cookie import/export surfaces are forbidden. Its HOME, temp,
XDG, socket and Chrome profile paths are isolated; model/cloud credentials are
removed; only the candidate and deterministic CDP loopback ports are allowed.
The Browser Use dependency closure is installed only into its separate virtual
environment and does not enter the main scoring interpreter.

HTTP/API and CI/CD cases execute directly and do not pass through a browser.
Only the fixed Playwright renderer produces formal screenshots and
area-weighted RGB SSIM. Rendering uses the recorded Chromium, Playwright, font,
viewport, locale, timezone, reduced-motion, color-scheme and deterministic
Chromium argument contract. Dynamic or sensitive rectangles must be masked
before persisted visual evidence is compared.

The manifest is deterministically divided into eight logical shards and at
most four shards execute concurrently. Each case seed is derived from the trial
seed and case ID. Candidate compilation, startup, timeout or assertion failures
are case failures and remain in the denominator; candidate failures are not
retried. A trusted verifier, browser, broker or sandbox infrastructure failure
is retried once with the identical seed. A second infrastructure failure makes
the entire trial `INVALID_RUN` and no reward is published.

If the candidate cannot be deployed at all, Harbor synthesizes a complete set
of 200 candidate-failure results with zero functional value. This is a valid,
scorable zero run rather than infrastructure invalidity.

## Scoring

For each T2 journey:

```text
F = 1 only when Playwright and Browser Use both pass
V = area-weighted RGB SSIM, or 1 when no visual checkpoint is declared
J = F * V
```

Let `R_L1`, `R_L2`, and `R_L3` be the mean journey values for each level:

```text
Score20 = 4 * R_L1 + 6 * R_L2 + 10 * R_L3
reward  = Score20 / 20
ranking = [Score20, T1 pass rate, T3 pass rate]
```

T1 and T3 therefore serve only as deterministic tie-breaks; they never change
reward. Every result must bind to the exact case-manifest bytes, contain the
exact 200 IDs, retain the derived seed across retry, and declare the appropriate
direct or dual-browser functional fields.

The active score command is:

```bash
websitebench-harbor score-v2 \
  --case-manifest case-manifest.json \
  --case-results case-results.json \
  --out result
```

## Authoring flow

```bash
websitebench-harbor init-site \
  --site-dir harbor/sites/example \
  --site-id example \
  --display-name Example

websitebench-harbor init-instance \
  --instance-dir harbor/instances/example \
  --instance-id example \
  --site-manifest sites/example/site.yaml \
  --author-name "Benchmark Team" \
  --author-email benchmark@example.test

# A new empty scaffold is a valid draft.
websitebench-harbor validate --instance harbor/instances/example

# After its private 200-case data is complete:
websitebench-harbor capture-reference --instance harbor/instances/example
websitebench-harbor materialize \
  --instance harbor/instances/example \
  --out harbor-dist/example
websitebench-harbor validate-bundle --bundle harbor-dist/example
websitebench-harbor calibrate-v2 \
  --bundle harbor-dist/example \
  --out harbor-calibration/example
```

Capture follows the source-evidence access policy. It records structured
terminal observations and fixed-size reference screenshots without persisting
credentials, cookies, authorization headers, payment data or sensitive form
values. Non-GET source actions require both the scenario declaration and the
explicit source-mutation command option. Authenticated storage state and reset
gateway credentials remain runtime-only.

Calibration runs a NOP once and the oracle twice in fresh candidates. For the
active protocol it compares Score20 and the T1/T3 tie-break rates and requires
the two oracle case-results, eval and receipt hashes to be identical. This is an
independent NOP/oracle trust check; it does not consume any of the 200 site
cases.

## Atomic results

`tests/test.sh` only invokes the generic runner and finalizer. A run is first
written beneath a private temporary directory. Every artifact and directory is
flushed, then the directory is atomically published. `receipt.json` is the last
file written and binds the manifest and all published artifact hashes.

A valid run includes:

- `case-results.json`, `eval.json`, `events.jsonl`, and JUnit XML;
- build/runtime logs, capped at 256 MiB;
- failure screenshots, SSIM heatmaps and sanitized failure traces when
  applicable;
- `reward.txt` with one fixed eight-decimal value; and
- a valid `websitebench.harbor.receipt.v1` receipt.

An invalid run includes diagnostic eval/events/log evidence and an invalid
receipt, but never a reward. The finalizer independently verifies every receipt
hash before exposing a fixed Harbor reward file.

Candidate audit logs are generation-specific. A trusted broker TID is attested
before candidate execution; trusted broker syscalls are excluded from candidate
write evidence. The process-group audit rejects undeclared ports, public
destinations, shared IPC and writes outside `DATA_DIR`, and performs complete
group cleanup before a runtime may be reused.

## Compatibility and OpenCLI

Historical v1 manifests still require `--legacy-v1` and retain their immutable
identity. Existing pre-compile v2 sites have no deployment ABI/case manifest
marker and are rejected by default. They can be validated, captured,
materialized, calibrated or scored only with the explicit
`--legacy-deploy-v2` option; their six-suite/result score interface remains
available only behind that option. Compatibility reads normalize only in
memory and do not rewrite historical files.

OpenCLI replay remains an advisory diagnostic against repository-owned clones
on `127.0.0.1`. It does not create cases, affect Score20 or reward, or become a
merge or deployment condition.
