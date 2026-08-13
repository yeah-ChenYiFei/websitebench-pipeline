# Harbor full-stack benchmark authoring

This directory is the normalized authoring root for browser-driven, full-stack
offline-site reconstruction tasks. It stores reusable site contracts separately
from their unique same-id instances:

```text
harbor/
├── sites/<site-id>/site.yaml
├── instances/<site-id>/instance.yaml
└── README.md
```

Generated Harbor bundles do **not** belong here or in Git. Materialize them into
the ignored `harbor-dist/` directory. The bundle uses Harbor's native
`environment/docker-compose.yaml`: `main` is the Agent container and
`reference` is a network-only sidecar whose source is never copied into
`main`.

New authoring uses deterministic Harbor v2 by default. The execution split is
strict:

- the Agent uses Browser Use CLI to inspect the browser-only reference and to
  self-check the candidate in `/app/repo`;
- the formal verifier uses trusted Playwright, RGB SSIM, and fixed CI/CD checks;
- a human reviewer may open reference and candidate URLs side by side;
- reference source, hidden fixtures, verifier code, and oracle material never
  enter the Agent image.

Create and review a Harbor-native bundle:

```bash
websitebench-harbor init-site \
  --site-dir harbor/sites/example-store \
  --site-id example-store \
  --display-name "Example Store"

websitebench-harbor init-instance \
  --instance-dir harbor/instances/example-store \
  --instance-id example-store \
  --site-manifest sites/example-store/site.yaml \
  --author-name "Benchmark Team" \
  --author-email benchmark@example.com

websitebench-harbor validate \
  --instance harbor/instances/example-store

websitebench-harbor capture-reference \
  --instance harbor/instances/example-store

websitebench-harbor materialize \
  --instance harbor/instances/example-store \
  --out harbor-dist/example-store

websitebench-harbor validate-bundle \
  --bundle harbor-dist/example-store

websitebench-harbor calibrate-v2 \
  --bundle harbor-dist/example-store \
  --out harbor-calibration/example-store
```

Each site has one reconstruction instruction and one hidden task/visual/CI-CD
suite set; add journeys to those suites instead of creating another instance.
The only reward is equal-weight exact task completion. Visual RGB SSIM and
trusted CI/CD pass rate are independent report-only scores. A v2 bundle cannot
materialize until every reference task and screenshot has been captured. Use
`--legacy-v1` only when explicitly reading compatibility fixtures;
existing v1 records and bundles are not migrated or reinterpreted.

`validate-corpus` validates only current v2 pairs by default and reports how many
legacy manifests it skipped. Pass `--legacy-v1` only for an explicit combined
compatibility audit.

The complete authoring, verifier, scoring, and release standard is in
[`docs/harbor-fullstack-benchmark.md`](../docs/harbor-fullstack-benchmark.md).
The v2 deterministic contract is documented in
[`docs/harbor-deterministic-v2.md`](../docs/harbor-deterministic-v2.md).
