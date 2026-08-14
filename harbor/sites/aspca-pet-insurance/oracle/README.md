# Oracle-only site support — aspca-pet-insurance

Private calibration payload. Materialize copies this whole directory into the
bundle as `solution/site`; the instance's `solution/solve.sh` then installs it
into the candidate root during calibration. Never expose it to agents.

Contents mirror the verified reference runtime
(`harbor/sites/aspca-pet-insurance/reference/`, minus Dockerfile/run.sh):

- `app.py` — FastAPI/uvicorn application serving the frozen pages, quote and
  portal SPAs, JSON APIs and `/healthz`.
- `backend/`, `websitebench/` — vendored site-backend runtime (VENDOR_MANIFEST
  preserved; do not regenerate).
- `frontend/`, `static/` — captured page shells, SPA view fragments and the
  offline asset mirror.
- `site-config/runtime.json`, `site-config/model.json` — backend runtime
  contract; `deploy.sh` points `WEBSITEBENCH_SITE_BACKEND_RUNTIME` here and
  pins the SQLite database into `$WEBSITEBENCH_DATA_DIR`.
- `deploy.sh` — candidate-contract entrypoint (foreground uvicorn on `$PORT`,
  state only under `$WEBSITEBENCH_DATA_DIR`, SIGTERM-clean).
