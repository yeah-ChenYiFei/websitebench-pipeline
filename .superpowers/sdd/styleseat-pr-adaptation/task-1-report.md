# StyleSeat PR adaptation report

## Changes

- Preserved the homepage HTML/CSS/JS interaction repair and its browser tests.
- Removed the city/service result-template substitution.  Only captured result
  documents are served; every uncaptured search shape reaches the explicit local
  `Beyond captured scope` boundary.
- Restored the generated backend integration seam and removed the handwritten
  SMTP configuration, transport, reservation and delivery behavior.  Login,
  logout, registration and recovery use the generated site-bound services.
- Derived the session cookie name and options from `backend/runtime.json` via
  `SiteBackend.session_cookie`; it is the required Host-only Secure cookie.
- Added `clone.yaml`, `backend/model.json`, `source-assets/manifest.json`, the
  generated `backend/runtime.json`, current source evidence, and the required
  StyleSeat diagnostic workflow.

## Commands and results

| Command | Result |
| --- | --- |
| `python tools/offline_clone/run.py tools list` | passed; shared diagnostic tool catalog discovered |
| `python -m websitebench.offline_clone.cli backend scaffold --site materials/styleseat` | expected non-overwrite refusal; existing generated runtime confirmed |
| `python -m pytest materials/styleseat/clone/tests -q` | passed: 25 tests |
| `ruff check materials/styleseat/clone` | passed |
| `node --check materials/styleseat/clone/static/home-actions.js` and `local-auth.js` | passed |
| `git diff --check` | passed |
| clean virtual environment: `pip install -r clone/requirements.txt` | passed; FastAPI 0.141.1 and Uvicorn 0.52.4 installed |
| clean-start smoke: Uvicorn + `GET /healthz` | passed: `{"ok":true,"site_id":"styleseat"}` |
| `python -m pytest tests/offline_clone/test_backend_scaffold.py tests/site_backend/test_auth_mail.py tests/site_backend/test_stdio_bridge.py tests/harbor/test_derive_from_clone.py -q` | passed: 21; skipped: 5 missing-site fixtures |
| `python -m websitebench.offline_clone.cli verify --site materials/styleseat --section static --out /tmp/styleseat-static.json` | did not complete after more than seven CPU-minutes scanning the large captured candidate; terminated without a report |
| `python -m websitebench.offline_clone.cli verify --site materials/styleseat --section live --out /tmp/styleseat-live.json` | passed: `clean` |

## Remaining findings / concerns

- `source-assets/manifest.json` accurately records asset closure as `pending`:
  the candidate contains the existing locally closed captured asset tree but
  does not yet carry distinct source/runtime copies for a full closure ledger.
  Static diagnostics therefore retain the asset-closure finding until that
  evidence is supplied.
- The combined standard diagnostic remains incomplete because its static section
  did not finish in the available execution window; the live section passed.
- `backend/model.json` is the supported complete model scaffold and remains
  `draft`; it does not claim unperformed backend proof obligations as verified.
- The generated contract requires a Secure `__Host-websitebench-styleseat-session`
  cookie. Chromium correctly withholds it on the diagnostic runner's plain
  `http://127.0.0.1` origin, so a browser login there does not retain an
  authenticated state. HTTPS loopback support (or a separately authorized
  diagnostic-runner change) is needed before that live authenticated checkpoint
  can pass without weakening the backend contract.
