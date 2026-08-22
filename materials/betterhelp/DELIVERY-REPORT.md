# BetterHelp offline clone delivery report

Assignment `18` / site `betterhelp` / category `health-medical` / source `https://betterhelp.com`.

This remains an internal loopback-only technical delivery. The formal trace is preserved verbatim: `[35] Sign up on BetterHelp, book a counseling session, and complete the initial questionnaire`. All exercised identities use `@example.test`, all health answers and support/review text come from fixed safe fixtures, and payment/mail are local simulations. No source mutation, real email, real payment, push, PR, deployment, or remote side effect was performed.

## Formal task source

- Main task and assignment metadata: `C:/Users/25777/Downloads/WebsiteBench.xlsx`, sheet `All`, assignment row `18`.
- Expanded tasks: the same workbook, sheet `Expanded Task Inventory`, `WB018-T01..T23`.
- Repository scope and implementation contracts: `scope/`, `clone.yaml`, `backend/runtime.json`, `clone/tests/`, and the same-id Harbor site/instance.
- The workbook is an input artifact outside the repository and was read only.

## Expanded task coverage

| ID | Implemented clone behavior | Primary executable evidence |
|---|---|---|
| T01 | Public home, primary navigation, canonical local routes and headings | public-route test, Edge E2E |
| T02 | Full signup → intake → provider → booking → confirmation with choices and total | booking integration test, Edge E2E |
| T03 | Validated and persistent eight-step matching questionnaire | intake test, Edge E2E |
| T04 | Search, specialty filtering, name ascending/descending and soonest-availability sorting | provider search/filter test |
| T05 | Provider detail, specialties, membership guidance and video/phone/live-chat options | provider and authenticated-next tests |
| T06 | Future availability selection, occupied/past-slot exclusion, comparison and reschedule | availability and booking tests |
| T07 | Save/favorite therapist with account ownership and persistence | provider save test |
| T08 | Account registration, profile name, verification and persistent session | registration tests, Edge E2E |
| T09 | Login and upcoming/past booking history | login persistence and history tests |
| T10 | Package, attendee name, session format, request option and validation | booking-details validation test |
| T11 | Local-sandbox approval, decline, retry and final review | payment tests, Edge E2E |
| T12 | Confirmation with therapist, time, online location, package, format, request, total and intake snapshot | confirmation test |
| T13 | Confirmed booking reschedule and cancellation | management test, Edge E2E |
| T14 | Past-session review, support contact and route to book again | review/contact/history test |
| T15 | Exact no-match search and recovery route to available therapists | no-results test, Edge E2E |
| T16 | Sign-in entry with email/password and recovery route | authentication tests |
| T17 | Registration entry with identity fields and verification guidance | registration tests |
| T18 | Password recovery field, uniform response, verification and password rotation | password-reset test |
| T19 | Booking history with status, confirmation, edit/cancel/review controls and collection route | history/management test |
| T20 | Signed-out prompts, incomplete-intake guards and required/invalid-field validation | permission and validation tests |
| T21 | FAQ, help and contact recovery paths without exposing another account | help/contact ownership tests |
| T22 | Branded 404 with navigation and safe recovery route | not-found test |
| T23 | Browser-level end-to-end task 35 with final choices and total | Edge E2E |

All 23 expanded task behaviors are implemented in the clone and covered by focused executable tests. This is a statement about candidate behavior, not a claim that unobserved authenticated source semantics were reproduced exactly.

## Functional and backend result

- Registration, verification, login, logout, password recovery, questionnaire persistence, provider discovery/save, booking details, local payment outcomes, confirmation mail outbox, history, reschedule, cancellation, review and contact persistence are implemented in SQLite.
- Matching and booking are denied until the questionnaire is complete. Past and occupied slots cannot be booked.
- Availability is generated relative to the runtime date, and application startup replaces expired fixture slots.
- Booking confirmation stores an immutable questionnaire snapshot. v4 migration backfills legacy bookings where a completed intake exists and displays an explicit unavailable state otherwise.
- A v3 declined/retryable payment flow keeps its exact legacy fingerprint after v4 snapshot backfill, so payment retry remains possible without weakening other immutable-fact checks.
- Anonymous support ownership is derived without persisting the raw session token. Contact success state is accepted only for a request owned by the current session/account.
- User-visible development labels such as `Synthetic ...`, `simulated payment`, `local fixture`, and `local member` were removed; synthetic-data enforcement remains active.

## Visual, state, role and viewport coverage

- Anonymous public source evidence includes desktop `1440×900`, tablet `768×1024`, and mobile `390×844` home captures plus AX/DOM evidence for primary public routes.
- Candidate Edge E2E covers home navigation, signup/verification, eight questionnaire steps, authenticated `/next/`, search/sort/no-results, provider details, booking details, payment, confirmation, history, reschedule and cancellation.
- Focused tests cover declined/retry payment, password recovery, permissions, error/empty states, review/contact persistence, old-database migration and concurrency conflict.
- Authenticated source `/next/` structure is available, but authenticated source booking/payment/history states were not mutated or captured. Exact visual equivalence for those continuation pages is unavailable.
- Independent review drove fixes for FAQ mobile state, Advice mobile ordering and Login desktop. Login now uses the frozen Maya Angelou state, the directly localized `q015-work.jpg`, the source image/flat-color geometry, an interactive reviews carousel and the login-specific footer. Formal three-frame source stability calibration remains unavailable, so the clone is not claimed to be source-indistinguishable outside frozen checkpoints.

## Asset and network closure

- Runtime assets are under `clone/static/`; observed source assets and hashes are recorded in `source-assets/manifest.json`.
- Edge E2E asserts `external_requests == []`.
- WSL report `verify-live-2026-08-22-r14-non-harbor.json` reports `diagnostic_status: clean`: static and live execution complete, `14/14` assets verified, `remote_references: 0`, `secrets: 0`, `blocked_external_references: 0`, and no findings.
- Frozen visual checkpoints passed their declared threshold: advice desktop `0.9138`, FAQ desktop `0.9677`, home desktop `0.9085`, home mobile `0.8959`, and login desktop `0.9391` (threshold `0.7`; diagnostic-only).
- Rights/redistribution status remains `unknown`; this report does not authorize publication or redistribution.

## Runtime and isolation

- Runtime contract: `materials/betterhelp/backend/runtime.json`.
- Migration hook: `backend.business:migrate_v4`.
- Database filename: `betterhelp.sqlite3`.
- Correct isolated override: `WEBSITEBENCH_SITE_BACKEND_DATABASE=<unique-directory>/betterhelp.sqlite3`.
- Registration mail uses a session-bound verification inbox. Password reset additionally requires a recovery-device binding previously established by successful registration or login; a new unrelated browser session cannot obtain a reset code for a known account. Payment uses `local-sandbox`; browser card, expiry, CVV and token fields are rejected.
- Health contract: `GET /__websitebench/health` returns `{"status":"ok"}`.

## Harbor status

- Harbor was explicitly excluded from the final completion pass and was not rerun or used for the recommendation below.
- Existing same-id site/instance files remain under `harbor/sites/betterhelp/` and `harbor/instances/betterhelp/`; this report makes no new claim about Harbor validation, scoring, reward, calibration or OpenCLI status.

## Latest commands and exits

| Command | Exit | Result |
|---|---:|---|
| `D:\\Python\\python.exe -m pytest tests/test_app.py -q -p no:cacheprovider` from `materials/betterhelp/clone` with an isolated database | 0 | `30 passed` |
| `D:\\Python\\python.exe -m pytest tests/test_browser_e2e.py -q -p no:cacheprovider` from `materials/betterhelp/clone` with `WEBSITEBENCH_TEST_BASE_URL=http://127.0.0.1:8458` | 0 | all 23 task records, registration inbox, full booking journey and visual geometry; `3 passed in 35.18s` |
| WSL `/tmp/websitebench-verify-venv-8463/bin/ruff check materials/betterhelp/clone/app.py materials/betterhelp/clone/backend materials/betterhelp/clone/tests` | 0 | `All checks passed!` |
| WSL `PYTHONPATH=src ... -m pytest tests/test_prompt_freshness.py -q -p no:cacheprovider` | 0 | `15 passed` |
| WSL `PYTHONPATH=src ... -m pytest tests --ignore=tests/harbor -q -p no:cacheprovider` | 1 | `342 passed, 19 skipped, 6 failed`; failures are environment prerequisites (isolated editable launcher and missing `jq`/Browserbase launcher), not BetterHelp assertions |
| Windows `D:\\Python\\python.exe -m pytest tests -q -p no:cacheprovider` | 1 | collection blocked by expected Linux-only `fcntl`/`resource` modules; WSL run above is the authoritative repository-level result |
| WSL current-source `PYTHONPATH=src ... -m websitebench.offline_clone.diagnostics --site materials/betterhelp --out materials/betterhelp/artifacts/offline-clone/verify-live-2026-08-22-r14-non-harbor.json` | 0 | `diagnostic_status: clean`; static/live complete; 27 checkpoints; 5 visual contracts; 0 findings |

The original Windows `resource`/`fcntl` and WSL FastAPI blockers are avoided for non-Harbor verification by running the current repository source through the existing Linux venv at `/tmp/websitebench-verify-venv-8463`.

## Modified implementation paths

- `materials/betterhelp/clone/app.py`
- `materials/betterhelp/clone/backend/business.py`
- `materials/betterhelp/clone/backend/runtime.json`
- `materials/betterhelp/backend/runtime.json`
- `materials/betterhelp/clone/static/site.css`
- `materials/betterhelp/clone/static/site.js`
- `materials/betterhelp/clone/static/assets/login-work.jpg`
- `materials/betterhelp/source-assets/localized/login-work.jpg`
- `materials/betterhelp/source-assets/manifest.json`
- `materials/betterhelp/clone/tests/test_app.py`
- `materials/betterhelp/clone/tests/test_browser_e2e.py`
- `materials/betterhelp/scope/checkpoints.json`
- `materials/betterhelp/scope/coverage.json`
- `materials/betterhelp/scope/verify.json`
- `materials/betterhelp/artifacts/e2e-non-harbor-final-2026-08-22-r14/`
- `materials/betterhelp/artifacts/offline-clone/verify-live-2026-08-22-r14-non-harbor.json`
- `materials/betterhelp/DELIVERY-REPORT.md`

## Known differences and recommendation

- Authenticated source booking/payment/history/review states remain unavailable under the no-source-mutation boundary; those routes are a safe continuation using fixed data.
- Exact typography, dynamic copy, A/B allocation and long-page visual rhythm can differ outside captured public anchors.
- Known visual differences remain outside the five frozen visual contracts: long-page copy, typography, dynamic source allocation, home/advice texture and some cookie wrapping. Authenticated source booking/payment/history/review screens remain unavailable under the no-source-mutation boundary.
- Harbor is out of scope for this recommendation and remains an independent pending acceptance dimension.
Recommendation: excluding Harbor, submit `MAIN_TASK` and `WB018-T01..T23` for local acceptance. The candidate journeys, persistence, recovery, isolation, offline asset closure and frozen visual checkpoints are supported by passing executable evidence. Do not label it source-authenticated-equivalent, formally three-frame calibrated, publicly deployable or redistribution-cleared.
