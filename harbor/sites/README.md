# Site baselines

Each direct child is one reusable offline-site baseline:

```text
sites/<site-id>/
├── site.yaml
├── public/                 # Agent-visible contracts, never reference source
├── reference/              # private sidecar context; Dockerfile + run.sh
├── verifier/               # trusted site-wide API/Playwright evaluator
│   └── run.py
├── fixtures/hidden/        # reset states and evaluator-only scenario data
└── oracle/                 # private calibration helpers
```

Use `websitebench-harbor init-site` to create this structure, then create the
unique same-id directory under `harbor/instances/`. Add every scoped journey to
that instance's hidden suites; a current site cannot own a second instance.

The generated Agent Dockerfile copies only `environment/seed/`; it never copies
the sibling `environment/reference/` build context. The Compose `reference`
service is reachable by network but the `main` container has neither its files
nor the Docker socket.

`site.yaml` is validated by
`websitebench/schemas/harbor-site.schema.json`. Its visibility roots must be
disjoint and may not contain symbolic links, junctions, reparse points, or hard
links.
