# Shared offline-clone tools

Use the repository-local launcher. It works before installation and when a
Windows non-UTF-8 locale cannot decode an editable-install path:

```text
python tools/offline_clone/run.py tools list
```

After a normal package installation,
`websitebench-offline-clone tools list` is equivalent.

The catalog and every report use canonical `websitebench` schema names. The
shared tools cover:

1. approved-origin browser exploration and interaction;
2. source/clone functional comparison;
3. frozen, region-level visual comparison;
4. actor-isolated black-box backend semantic tests.

Copy a versioned example from `specs/`, keep stable IDs, and write each run to a
fresh output path. Browser storage state and environment-injected values are
consumed only at runtime. Never commit those inputs.

Source scenarios are GET-only by default. A source mutation requires both
`source_mutations_authorized: true` in the exact scenario and the explicit CLI
flag. Backend suites accept loopback targets by default; the non-loopback flag
is only for a separately isolated clone target.

Tool reports deliberately say `diagnostic-only-does-not-satisfy-release-gates`.
Release evidence must still be produced and validated through the configured
site gates.
