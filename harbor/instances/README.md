# Site instances

Each current direct child is the sole Agent reconstruction task for the
same-id site:

```text
instances/<site-id>/
├── instance.yaml
├── instruction.md
├── public/                 # candidate scaffold; current v2 uses deploy.sh
├── verifier/               # site-wide hidden checks
├── fixtures/hidden/        # site-wide hidden tasks and expected states
└── solution/solve.sh       # private oracle solution
```

Use `websitebench-harbor init-instance` with matching `--instance-id` and site
directory names. `instance.yaml` references the same-id site manifest relative
to the `harbor/` root, for example `sites/example-store/site.yaml`. Add another
journey to the hidden suites of this instance; do not create another instance
for the site. Historical v1 task directories retain their recorded identities
and require explicit legacy reads.

Every full-stack instance must declare exact, globally unique nodes in the
`contract`, `api`, `ui`, `visual`, `journey`, and `robustness` groups. API and
UI each require at least two nodes. The generated verifier rejects missing,
extra, duplicate, skipped, or malformed result sets rather than silently
changing the denominator.
