# Harbor v2 deterministic evaluation

Harbor v2 evaluates an entire offline website reconstruction with no
LLM-as-Judge component. The verifier has three independent deterministic
outputs:

```text
task_score   = passed_tasks / total_tasks * 100
reward       = task_score / 100
visual_score = mean(checkpoint_area_weighted_rgb_ssim) * 100
cicd_score   = passed_trusted_checks / total_trusted_checks * 100
```

`visual_score` and `cicd_score` are report-only. They cannot cap, raise, or
otherwise modify reward. Skipped and flaky CI/CD checks count as zero. A task is
worth one point only when every declared terminal observation matches on its
first execution.

## Contracts

New site and instance scaffolds use `websitebench.harbor.site.v2` and
`websitebench.harbor.instance.v2`. Each site has exactly one same-id instance;
journeys are tasks inside that instance rather than additional instances. The
instance references exactly one hidden suite of each type:

- `websitebench.harbor.task-suite.v1`: versioned Playwright actions and explicit
  terminal observations using exact, normalized-exact, regex, ordered-list,
  set, finite-number tolerance, or SHA-256 comparators;
- `websitebench.harbor.visual-suite.v1`: fixed route, actions, viewport,
  non-overlapping regions, masks, and reference raster paths;
- `websitebench.harbor.cicd-suite.v1`: the exact fixed platform check set plus
  optional verifier-only site checks whose boolean verdict is their exit
  status.

The scorecard is `websitebench.harbor.score.v2`. Historical v1 manifests are
still read explicitly and materialize through their unchanged v1 templates.
They do not satisfy v2 reference-observation or scoring contracts.
Every public legacy read requires `allow_legacy_v1=True`; the equivalent
`validate`, `validate-corpus`, and `materialize` CLI calls require
`--legacy-v1`.
Without that flag, `validate-corpus` validates only current one-to-one v2 pairs
and reports the number of skipped legacy manifests.

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

websitebench-harbor validate \
  --instance harbor/instances/example

websitebench-harbor capture-reference \
  --instance harbor/instances/example

websitebench-harbor materialize \
  --instance harbor/instances/example \
  --out harbor-dist/example

websitebench-harbor validate-bundle \
  --bundle harbor-dist/example

websitebench-harbor calibrate-v2 \
  --bundle harbor-dist/example \
  --out harbor-calibration/example
```

`capture-reference` starts the local reference unless `--reference-url` is
provided. It executes every task and visual checkpoint. It writes structured
terminal observations and fixed-size reference screenshots. Any action,
observation, or screenshot failure leaves the instance `pending`; pending
observations cannot materialize.

Capture must run in the canonical Playwright 1.61.0 / Chromium / Linux font
profile. The artifact records the actual Chromium version, Playwright version
and configured font profile; the formal verifier refuses to compare screenshots
when its render fingerprint differs. Remote reference actions stay on the
configured primary origin plus the comma-separated origins supplied through
`WEBSITEBENCH_REFERENCE_ALLOWED_ORIGINS`. Non-GET source requests are blocked
unless the exact task/checkpoint declares `reference_mutation_authorized: true`
and the author also passes `--allow-source-mutations`; loopback alone is not
authorization. For any explicitly supplied reference, mutation also requires
an allowlisted HTTPS gateway (HTTP is accepted only when both fixture and
gateway are loopback)
named by `WEBSITEBENCH_REFERENCE_RESET_URL` and the runtime-only
`WEBSITEBENCH_REFERENCE_RESET_CREDENTIAL`. The gateway runs before every
scenario so captured facts cannot depend on prior tasks; neither credential nor
reset URL is persisted.
Authenticated references may inject a Playwright storage-state JSON path through
`WEBSITEBENCH_REFERENCE_STORAGE_STATE`. It is loaded into every fresh reference
browser context but is never copied, logged, or included in the observations;
the artifact records only whether authenticated state was used.

`calibrate-v2` copies the public seed into three fresh candidate trees, runs the
NOP once, applies `solution/solve.sh` independently to two oracle copies, and
executes the same four-worker evaluator for all three. Evidence passes
only when NOP task score is at most 5, both oracle task and CI/CD scores are
100, both oracle visual scores are at least 95, and the two oracle discrete
verdict/score projections are exactly equal.

## Candidate runtime

The sole artifact is `/app/repo`. Its root `deploy.sh` must be executable, take
no arguments, remain in the foreground, listen on `$PORT`, return HTTP 200 from
`/healthz`, handle SIGTERM, and write runtime data only beneath
`$WEBSITEBENCH_DATA_DIR`. Runtime dependency downloads and unauthorized network
access are forbidden.

The formal verifier uses four workers. Each task owns a different loopback
port, data directory, mailbox namespace, and browser context. The candidate
process also receives a distinct, phase-independent random unprivileged UID
with no supplementary groups,
and its data directory is mode `0700`. Before candidate `exec`, a Linux Landlock
ruleset makes the candidate tree read-only, grants read/write access only to
that worker's data directory, and permits TCP bind/connect only on declared
ports. A seccomp filter rejects datagram and cross-worker Unix sockets, SysV and
POSIX message/shared-memory IPC, shared inode locks, keyrings, inotify/fanotify,
session/process-group escape, and io_uring. `/proc` and `/sys` are not exposed.
SQLite byte-range locks on regular files beneath the worker data directory are
executed by a trusted seccomp notification broker without continuing the
candidate syscall, so descriptor-swap races cannot redirect them to a shared
inode. These restrictions are inherited by descendants and block shared
`/tmp`, loopback, procfs/sysfs, lock, and IPC side channels before data can
cross workers. A trusted kernel preflight verifies Landlock ABI, seccomp user
notification, architecture and x32 closure before scoring. A candidate deployment failure produces
valid zero task and visual results; a verifier crash produces `INVALID_RUN` and
removes `reward.txt` and `scorecard.json`.

The platform checks run the candidate under a trusted file-syscall audit,
redirect HOME/TMP/XDG state into its task data directory, verify the whole
process group stops on SIGTERM, preserve distinct data sentinels across restart
and concurrent launches, sample process-group RSS and data bytes, enforce CPU
affinity and OS resource limits, and reject any attempted write outside the
assigned data directory. The audit covers every task, visual checkpoint, deploy
probe, and CI process; it also rejects undeclared loopback ports, non-loopback
destinations, and shared IPC attempts. Any such event invalidates both scoring
suites so a sacrificial worker cannot contaminate later work. Chromium smoke
blocks non-loopback subresource attempts.

## Mail and anti-model boundary

`local-sidecar` is the default mailbox. It provides loopback SMTP, a namespaced
Inbox Web/API, and deterministic OTP extraction without sending real mail.
Each worker receives an opaque `WEBSITEBENCH_MAILBOX_CAPABILITY` bound only to
its namespace. SMTP messages must copy the namespace and capability into the
`X-WebsiteBench-Namespace` and `X-WebsiteBench-Capability` headers; Inbox API
requests use the capability as a Bearer token. A worker cannot read or deliver
into another worker's mailbox namespace.
`external-proxy` requires an exact HTTPS hostname allowlist and a runtime-only
credential; evidence redaction removes credentials, OTPs, tokens, cookies, and
sensitive form fields. If the verifier has a default route, formal startup also
requires `WEBSITEBENCH_NETWORK_POLICY_ENFORCED=1` from the platform network
controller. Merely declaring a non-empty hostname allowlist is not accepted as
proof that the policy is enforced.

The local SMTP/Inbox sidecar has fixed message, per-namespace storage,
recipient, command, connection, idle-time and total-lifetime limits. Candidate
traffic therefore cannot allocate unbounded trusted verifier memory or threads.

The external mailbox credential remains in the trusted observer only and is
removed from every candidate process environment. The mailbox runtime evidence
records only mode, allowlist, and a credential-present boolean.

Bundle validation verifies the exact file/hash set and rejects model SDKs,
model service URLs, model credential names, model/prompt/embedding/completion
Judge configuration, public verifier networks, hidden-suite/reference-raster
leaks into the Agent image, and candidate-visible verifier result paths. The
verifier image records its installed dependency manifest and runtime network /
credential evidence.

Those runtime facts are derived from the actual dependency list, importable
modules, credential environment, font files, and sealed network policy. They
are not accepted as candidate- or author-supplied booleans.

## Outputs

A valid run emits `scorecard.json`, `reward.txt`, the three `*-results.json`
files, JSONL mirrors, JUnit XML, sanitized action traces, mask-redacted candidate
screenshots, SSIM heatmaps, hashes, and sanitized logs. Raw browser traces are
not retained because they can contain cookies, headers, credentials, or form
values. `reward.txt` contains only the task completion fraction with exactly
eight decimal places. Visual suite authors must mask every dynamic or sensitive
rectangle; masks are blacked out before reference or candidate rasters persist.
`sandbox-runtime-evidence.json` records the trusted kernel fingerprint and
successful enforcement probe; a missing capability makes the run invalid.

The required `harbor-v2-deterministic` CI job installs the pinned Chromium and
`strace`, runs the suite as root so opaque-UID isolation is exercised, and turns
any unavailable real E2E/calibration prerequisite into a test failure.
