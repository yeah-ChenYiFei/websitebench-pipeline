# Browser trajectory recorder

`websitebench-browser-trajectory` extracts the reusable part of human browser
capture: it attaches to an already-running Chrome DevTools Protocol (CDP)
endpoint, observes DOM interactions, and writes a structural interaction ledger.
It neither launches a browser nor owns its profile, and it has no dependency on
task definitions, agents, evaluation, request interception, or publication
workflows.

Launch Chrome with remote debugging enabled, then record only explicitly
approved origins:

```bash
websitebench-browser-trajectory record \
  --cdp-url http://127.0.0.1:9222 \
  --allowed-origin http://127.0.0.1:3000 \
  --output artifacts/browser-trajectory/demo
```

Stop with `Ctrl-C`, or provide `--duration-seconds`. The output directory must
be empty and contains:

| Path | Content |
| --- | --- |
| `actions.jsonl` | Redacted click, keyboard, input, scroll, submission, and navigation events. |
| `session.json` | Capture bounds, artifact layout, privacy contract, and final counters. |
| `screenshots/` | Optional event-triggered PNGs, enabled only by `--screenshots`. |

The recorder removes URL queries and fragments; omits element text, form values,
browser credentials, and network traffic; and collapses printable keystrokes to
`"character"`. It ignores events outside `--allowed-origin`. Screenshots can
still expose what is visibly rendered, so use `--screenshots` only for declared
non-sensitive surfaces and never retain sensitive data.

Same-origin frames are instrumented individually, so one navigation can emit a
`pageLoad` per frame. Cross-origin frames are skipped silently: interactions
inside an embedded consent banner, payment widget, or third-party login box do
not appear in the ledger, and their absence is not evidence that the control
does not exist.

## Comparing two recordings

`diff` aligns a source-side and a candidate-side ledger to show where an offline
clone's interaction structure departs from the site it reproduces:

```bash
websitebench-browser-trajectory diff \
  --source artifacts/trajectory/tr-001 \
  --candidate artifacts/trajectory/tr-001.clone \
  --output artifacts/trajectory/tr-001.diff.json
```

Comparison runs over a normalized projection — event type, route path, and
element identity (`tag`, `id`, `name`, `input_type`, `role`). Everything that
differs between two human demonstrations for reasons the site does not control
is dropped: wall-clock timestamps, pointer coordinates, scroll offsets, the
throttled `scroll`/`input` streams, and the origin (a source origin and a
loopback candidate origin never match). Consecutive duplicate `pageLoad` steps
collapse, because per-frame injection produces them.

| Flag | Effect |
| --- | --- |
| `--strict` | also compare `class_name` and `xpath`; both diverge on styling and nesting a user cannot perceive, so this over-reports |
| `--include-input` | also compare throttled `input` events (values stay omitted) |
| `--collapse-repeats` | collapse consecutive identical steps of every type; hides genuine repeats such as a double submit |

Findings are `missing-in-candidate` and `extra-in-candidate`, each carrying the
step that diverged. Read a divergence as "these two runs differ", not as "the
clone is broken" — a human demonstrating the same journey twice rarely repeats
it exactly, so rule that out before treating a finding as a defect.

The report declares `"authority": "diagnostic"`. It compares structure and
order only, and establishes nothing about pixels, copy, network closure, or
anything inside a cross-origin frame. There is deliberately no
fail-on-divergence mode: `diff` exits `0` whether or not it found anything, so
it cannot be wired up as a gate, and a clean report is not evidence that a
candidate is faithful.
