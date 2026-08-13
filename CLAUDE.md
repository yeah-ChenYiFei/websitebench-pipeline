# CLAUDE.md — execution entry for agents

This repository is the offline-clone production pipeline: prompt → source
evidence → clone → diagnostics → backend → Harbor contract → Harbor instance.
Humans accept the work (see `ACCEPTANCE.md`); you execute it.

## Operating contract

1. Read `AGENTS.md` first — naming, secrets, backend, Harbor and diagnostic
   rules there are binding.
2. For clone production runs, the operating contract is
   `prompts/offline-clone/autonomous-source-to-clone.md` plus its
   `references/*.md` (indexed in the entry prompt). The entry prompt's rules
   take precedence over every reference file.
3. The golden sample is **tripit**: shape every new site's artifacts like
   `materials/tripit/` and `harbor/sites/tripit/`.

## Command cheatsheet

```bash
uv pip install -e '.[dev]'                                   # after entry-point changes
websitebench-offline-clone contribution init --repo . --site-id <id> \
  --display-name "<Name>" --source-url <url>                 # new site scaffold
websitebench-offline-clone status --site materials/<id>
websitebench-offline-clone verify --site materials/<id>      # --section static|live
websitebench-offline-clone backend scaffold --site materials/<id>
python tools/offline_clone/run.py tools list                 # shared diagnostics
websitebench-harbor derive-from-clone ...                    # contract from clone artifacts
websitebench-harbor run-opencli ...                          # advisory replay only
websitebench-harbor init-instance ...                        # instance skeleton
```

Repo gates before handing work back:

```bash
ruff check src tests websitebench
python -m pytest tests/test_prompt_freshness.py -q
python -m pytest tests/offline_clone tests/harbor tests/project -q
python -m pytest materials/<id>/clone/tests -q
```

## Hard boundaries

- Never persist credentials, cookies, authorization headers, session secrets
  or payment data anywhere (repo, logs, screenshots, evidence).
- Diagnostics are diagnostic-only; never present `clean` as an acceptance,
  rights or deployment decision. Never wire OpenCLI replay into scoring or
  merge conditions.
- Do not rename or regenerate historical ClawBench identifiers, schemas or
  vendored runtime trees.
- Everything under `prompts/` must stay English and consistent with the
  codebase — `tests/test_prompt_freshness.py` enforces the binding; run it
  after touching prompts, CLIs or entry points.
- Deployment is out of scope for this repository; do not add deploy workflows
  or publish clones from here.
