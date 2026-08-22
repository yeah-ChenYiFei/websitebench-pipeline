# Candidate Contract (compile.sh -> executable)

> The benchmark candidate is a **compilable, runnable full-stack application**.
> The contract below is what the verifier builds and boots; it mirrors the
> repository's generic offline-clone candidate ABI.

## 1. Repository layout

```text
/app
  frontend/
  backend/
  README.md
  Dockerfile
  docker-compose.yml
  seed/            # deterministic seed + reset
  .env.example
  compile.sh       # optional build step; must exit 0
```

## 2. Runtime contract

- The service starts with one command and stays in the **foreground**.
- It honours `HOST` (default `127.0.0.1`), `PORT` (default `8080`),
  `DATA_DIR` (writable directory for the database/uploads), `SEED`
  (seed identifier), and `TZ` (timezone).
- `GET /__websitebench/health` returns exactly `{"status":"ok"}` with HTTP 200.
- `GET /healthz` returns `{"ok":true,"site_id":"craigslist"}` (clone identity).
- It handles SIGTERM and exits cleanly.
- Deterministic reset: the reference runner can reset the data directory to
  the exact seeded state (e.g. via a seed/reset script or a token-gated admin
  endpoint), so evaluation always starts from an equivalent initial state.

## 3. Runtime boundaries

- **Offline:** no remote image, font, stylesheet, script, map tile, API, or
  telemetry request may leave the page at runtime.
- **No proxying:** the candidate must not iframe, proxy, or fetch the target
  site; runtime network requests to the target or external origins are a hard
  failure.
- **Real backend:** stateful journeys (accounts, postings, favorites, saved
  searches, replies) must be implemented server-side and persist in the
  candidate's own database; client-only fake state is a hard failure.

## 4. Reference-runner integration

The reference runner boots the reference site and the candidate identically:
same seed, same controllable clock, same host/port conventions. The public
`/account/login`, `/account/register`, `/account/forgot`, `/post/`,
`/toronto/search/housing`, `/search/area/toronto?cat=hhh` routes and the canonical
listing `/view/d/1br-near-annex-furnished-sublet-jul-aug/4c93`
are the primary surfaces the verifier drives.
