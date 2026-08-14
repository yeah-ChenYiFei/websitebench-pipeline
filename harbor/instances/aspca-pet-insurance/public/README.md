# aspca-pet-insurance — candidate workspace

This is your repository root. Build the offline pet-insurance site described in
`instruction.md` (one directory up in the task materials) and make it
deployable through `deploy.sh`.

## Runtime contract (enforced by the verifier)

- The verifier runs `./deploy.sh` from this repository root with two
  environment variables set: `PORT` and `WEBSITEBENCH_DATA_DIR`.
- `deploy.sh` must start your server as a **foreground** process listening on
  `$PORT` on all interfaces, and keep running until it receives SIGTERM, then
  exit promptly.
- `GET /healthz` must return HTTP 200 once the server is ready. The verifier
  waits on it before running any check.
- All mutable state (databases, uploads, caches) must live only under
  `$WEBSITEBENCH_DATA_DIR`. The repository tree must not change at runtime;
  the verifier snapshots and re-hashes it.
- The site must be fully offline: no request may leave the loopback interface.
  Any external fetch (CDNs, fonts, analytics, embeds) is a failure.
- Clock discipline: render and compute against the frozen time
  `2026-08-13T12:00:00Z` (locale `en-US`, timezone `UTC`); do not let wall
  clock or randomness reach page output, policy dates or ids.
- Restarting `deploy.sh` with the same `WEBSITEBENCH_DATA_DIR` must preserve
  previously created data (persistence survives restart); a fresh data
  directory must boot to a clean, empty state.

The provided `deploy.sh` is a failing placeholder — replace it. A deployment
that fails to boot scores zero on every suite.
