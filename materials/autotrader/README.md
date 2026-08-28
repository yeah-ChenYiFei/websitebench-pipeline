# AutoTrader offline clone

This site was normalized from PR #60 archive `autotrader-runnable-site.tar.gz`. The
archive supplied one anonymous home-page SingleFile capture plus semantic search,
listing, account, and vehicle-selling routes implemented by a local FastAPI app.
Scope files keep routes without source evidence diagnostic-only.

## Start

```bash
cd materials/autotrader/clone
./compile.sh
HOST=127.0.0.1 PORT=8767 DATA_DIR="$(mktemp -d)" \
  PYTHON=/absolute/path/to/repository/.venv/bin/python ./executable
```

Open <http://127.0.0.1:8767/>. Stop with `Ctrl-C`.

The package is offline at runtime and uses synthetic local data only. It does
not include credentials, browser state, cookies, or the runtime SQLite file.
Authentication, saved items, addresses, and adverts use the generated local
runtime and site-owned SQLite tables. Registration verification is delivered
only through the local outbox; password recovery is guidance-only and never
sends a message.

The local catalog contains exactly 200 deterministic, searchable vehicle
records with openable detail routes. This catalog count is independent from the
Harbor v2 draft corpus, which remains unscorable with zero materialized cases.
Additional frozen visual pages mentioned by the submitter were not included in
PR #60. They remain a documented evidence gap and must not be inferred or fetched
from the live source as a substitute for the submission.
