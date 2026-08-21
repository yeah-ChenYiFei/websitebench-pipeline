# Coursera Local Auth, Learning, and Enrollment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Do not dispatch subagents and do not commit.

**Goal:** Implement the remaining local account, learner, history, preference, and Deep Learning enrollment boundary flows while preserving the source-grounded public pages and all 23 journey boundaries.

**Architecture:** Keep FastAPI route handlers thin and use the existing `websitebench.site_backend` integration, `backend.learning_db`, and `backend.checkout` as the only state owners. Add one bounded Playwright settling helper for every lazy/long page, then build the three independently testable slices in order: auth, learner state, and local-sandbox enrollment.

**Tech Stack:** Python 3.14, FastAPI, existing WebsiteBench site backend, SQLite, Jinja/HTML, vanilla CSS/JS, pytest, Playwright, `tools/offline_clone/run.py`.

## Updated acceptance priority (2026-08-20)

- Frontend acceptance targets at least 90% visual similarity at the fixed fullscreen viewport; pixel-identical reconstruction is no longer required.
- Functional behavior and backend state transitions across all 23 journeys are mandatory and take priority over additional visual polishing.
- Finish and regression-test every anonymous/signed-out state before advancing through local authentication, learner state, and local-sandbox enrollment.
- Login must open over the invoking public page without replacing, hiding, shortening, or navigating away from that background.
- Source-inaccessible authenticated/payment visuals may use a clearly local implementation, but the required journey behavior must still be implemented through the generated backend runtime and its safety boundaries.

## Global Constraints

- Acceptance viewport is exactly `1692 x 979` CSS pixels.
- Source acquisition is read-only GET-only; no Coursera account creation, enrollment, email, OAuth, or payment submission.
- `materials/33/backend/runtime.json` and the generated `websitebench.site_backend` seam are immutable runtime contracts.
- `site_id` is `33`; data uses the site-33 SQLite identity and host-only `__Host-websitebench-33-session` cookie.
- Registration and recovery use local `.test` identities and local inbox only; no real email is sent.
- Payment uses `local-sandbox` scenarios only; card-looking fields have no `name` and are never submitted or stored.
- Public pages remain source snapshots/source-backed templates; do not invent catalog cards, sections, preview routes, or source-authenticated claims.
- Every lazy page must settle completely or report `incomplete`; never substitute placeholders or guessed content.
- Do not add animation absent from the observed source.
- Do not commit, deploy, push, merge, or clean unrelated worktree changes.

## Journey Coverage Map

| Slice | Journeys | Required boundary |
|---|---|---|
| Auth | `auth.signup-local`, `auth.login-dashboard`, `auth.login-shell`, `auth.signup-shell`, `auth.recovery-shell` | Local registration/verification/login/recovery; external effects forbidden |
| Learner | `learning.lesson`, `learning.quiz-feedback`, `learning.progress`, `learning.preferences`, `history.seeded` | Seeded local account only; owner and persistence checks required |
| Enrollment | `enrollment.deep-learning-review`, `enrollment.track-selection`, `enrollment.paid-review`, `task265.deep-learning-review`, `validation.required-or-signed-out` | Reach empty payment fields and local review/result; never require real card data |
| Already public | `public.browse`, `catalog.subject`, `catalog.search-filter`, `catalog.course-detail`, `catalog.preview`, `search.no-results`, `support.public`, `recovery.not-found` | Preserve current public behavior; preview stays absent unless source evidence appears |

## File Map

- Create: `materials/33/clone/browser_settle.py` — bounded lazy-load settling and image-health assertions.
- Create: `materials/33/clone/tests/test_browser_settle.py` — unit tests for stable-height and incomplete outcomes.
- Modify: `materials/33/clone/tests/test_learning_backend.py` — auth and learner state contracts.
- Modify: `materials/33/clone/tests/test_checkout_flow.py` and `test_checkout_backend.py` — enrollment boundary contracts.
- Modify: `materials/33/clone/app.py`, `ui.py`, and focused templates/CSS only where a failing contract identifies a missing state.
- Modify: `materials/33/scope/current-accessible-fullscreen-phase.json` and `verify.json` only when a journey boundary changes truthfully.
- Create: focused Playwright scenarios under `materials/33/scope/` for settled auth, learner, and checkout states.

### Task 1: Add the bounded complete-load helper

**Files:**
- Create: `materials/33/clone/browser_settle.py`
- Create: `materials/33/clone/tests/test_browser_settle.py`
- Modify: `materials/33/clone/tests/test_live_home_inline_login_contract.py`
- Modify: `materials/33/clone/tests/test_business_category_fidelity.py`

**Interfaces:**
- `settle_page(page, *, max_rounds: int = 24, timeout_ms: int = 20_000) -> dict[str, object]`
- Returns `complete`, `scroll_height`, `section_count`, `image_count`, `loaded_image_count`, `failed_images`, and `incomplete_reason`.
- Raises no unbounded wait; a timeout returns `complete=False` with a reason.

- [ ] **Step 1: Write failing unit tests for stable and incomplete pages.**

```python
def test_settle_requires_two_unchanged_bottom_observations(fake_page):
    fake_page.metrics = [(5000, 20, 20), (7000, 30, 29), (7000, 30, 30), (7000, 30, 30)]
    result = settle_page(fake_page, max_rounds=4)
    assert result["complete"] is True
    assert result["scroll_height"] == 7000
    assert result["loaded_image_count"] == 30


def test_settle_reports_timeout_instead_of_inventing_completion(fake_page):
    fake_page.metrics = [(5000, 20, 0)] * 4
    result = settle_page(fake_page, max_rounds=3)
    assert result["complete"] is False
    assert "image" in result["incomplete_reason"]
```

- [ ] **Step 2: Run the tests and verify RED.**

Run: `pytest materials/33/clone/tests/test_browser_settle.py -q`

Expected: FAIL because `browser_settle.settle_page` does not exist.

- [ ] **Step 3: Implement the bounded browser evaluation.**

Use one `page.evaluate` call per round to scroll by `innerHeight`, collect `documentElement.scrollHeight`, stable section/card counts, and each image's `complete`, `naturalWidth`, `src`, and `currentSrc`. Require two consecutive unchanged observations at the bottom; return `complete=False` when the round limit or deadline is reached.

- [ ] **Step 4: Run unit tests and retrofit one existing scenario.**

Run: `pytest materials/33/clone/tests/test_browser_settle.py materials/33/clone/tests/test_business_category_fidelity.py -q`

Expected: PASS; Business must still report its complete `8990px` page and 90 healthy images.

### Task 2: Finish local auth and onboarding presentation

**Files:**
- Modify: `materials/33/clone/app.py`, `ui.py`, existing auth templates/CSS only as required.
- Modify: `materials/33/clone/tests/test_learning_backend.py`
- Modify: `materials/33/clone/tests/test_anonymous_journey_matrix.py`
- Create: `materials/33/scope/clone-auth-local-settled.json`

**Interfaces:**
- Existing routes: `/signup`, `/local-inbox`, `/auth/registration/start`, `/auth/registration/verify`, `/onboarding`, `/login`, `/auth/login`, `/auth/logout`, `/account-recovery`, `/auth/recovery/start`, `/auth/recovery/complete`.
- All mutating handlers continue to call the existing auth service; no new account store is introduced.

- [ ] **Step 1: Add failing route assertions for complete local auth states.**

Assert synthetic `.test` validation, local inbox verification guidance, invalid-code inline errors, same-origin `next` continuation, logout, non-enumerating recovery, and provider boundary copy. Assert no password/card value is echoed.

- [ ] **Step 2: Run the focused auth tests and verify RED for any missing UI state.**

Run: `pytest materials/33/clone/tests/test_learning_backend.py -q -k 'registration or recovery or login or provider or shared_header'`

- [ ] **Step 3: Implement only the missing presentation/state wiring.**

Keep the generated session cookie and backend methods unchanged. Render validation errors with the existing learner/public chrome and preserve the same-document login modal where the current public evidence requires it.

- [ ] **Step 4: Run auth tests and the settled Playwright scenario.**

Run: `pytest materials/33/clone/tests/test_learning_backend.py materials/33/clone/tests/test_anonymous_journey_matrix.py -q -k 'registration or recovery or login or provider or auth'`.

Then run the clone scenario with `settle_page`; require `complete=true`, zero failed images, zero remote requests, and stable URL transitions.

### Task 3: Verify and complete learner dashboard, lessons, progress, quizzes, preferences, and history

**Files:**
- Modify: `materials/33/clone/app.py`, `backend/learning_db.py`, and learner templates/CSS only for failing contracts.
- Modify: `materials/33/clone/tests/test_learning_backend.py`
- Modify: `materials/33/clone/tests/test_desktop_contract.py`
- Create: `materials/33/scope/clone-learning-local-settled.json`

**Interfaces:**
- Existing local routes: `/my-learning`, `/learn/.../lesson/...`, `/learning/bookmarks`, `/learning/progress`, `/learning/quizzes/...`, `/account/preferences`, `/account/history`, and safe not-found/cross-owner boundaries.
- State transitions remain subject-owned and persisted through `backend.learning_db`.

- [ ] **Step 1: Add failing browser/HTTP assertions for each 23-journey state.**

Cover resume target, lesson-to-unit navigation, bookmark toggle, progress replay, quiz result/feedback, preference update, newest history status/detail/cancel, refresh persistence, and second-user isolation. Include exact empty/loading/error states where no seeded record exists.

- [ ] **Step 2: Run the learner subset and verify RED.**

Run: `pytest materials/33/clone/tests/test_learning_backend.py materials/33/clone/tests/test_desktop_contract.py -q -k 'learning or lesson or quiz or progress or bookmark or preference or history or enrollment'`.

- [ ] **Step 3: Repair only backend/UI gaps exposed by those tests.**

Do not alter catalog source data. Validate lesson IDs, quiz IDs, enrollment ownership, cancellation idempotency, and persistence after service reopen. Ensure all long learner pages use `settle_page` before screenshot or completion claims.

- [ ] **Step 4: Run learner tests and the complete-load scenario.**

Expected: all selected tests pass; scenario reports stable document height, all local images loaded, no failed requests, and no console errors.

### Task 4: Verify Deep Learning enrollment and local-sandbox review boundary

**Files:**
- Modify: `materials/33/clone/app.py`, `backend/checkout.py`, and checkout templates/CSS only for failing contracts.
- Modify: `materials/33/clone/tests/test_checkout_flow.py`
- Modify: `materials/33/clone/tests/test_checkout_backend.py`
- Create: `materials/33/scope/clone-checkout-local-settled.json`

**Interfaces:**
- Existing routes: `/specializations/deep-learning`, `/checkout/deep-learning`, `/payments/checkout`, `/checkout/{draft_id}/payment`, `/checkout/{draft_id}/review`, `/checkout/{draft_id}/attempt`, and local order detail/history routes.
- Existing `checkout.create_draft`, `get_draft`, `attempt`, `list_orders`, and `cancel_order` remain the state API.

- [ ] **Step 1: Add failing boundary tests for signed-out, empty-payment, review, decline, retry, and approval.**

Require signed-out permission prompt, exact CNY trial totals, required-field validation, payment-looking inputs without `name`, review choices limited to the three local sandbox scenarios, idempotency, owner isolation, and no card value in request/response/database.

- [ ] **Step 2: Run checkout tests and verify RED for missing presentation or validation.**

Run: `pytest materials/33/clone/tests/test_checkout_flow.py materials/33/clone/tests/test_checkout_backend.py -q`

- [ ] **Step 3: Implement only local presentation/contract gaps.**

Never add live Stripe keys or a real card field. Keep `local-sandbox` as the only enabled adapter and preserve the empty-payment stopping boundary in `current-accessible-fullscreen-phase.json`.

- [ ] **Step 4: Run checkout tests and settled browser scenario.**

Require `complete=true` for every checkout view, no remote requests, no sensitive values, and visible totals/selected scenario on review/result.

### Task 5: Cross-phase regression, 23-journey audit, and handoff

**Files:**
- Modify: `materials/33/clone/tests/test_current_phase_matrix.py` only if an evidence-backed boundary changes.
- Modify: `materials/33/scope/current-accessible-fullscreen-phase.json` and `materials/33/scope/verify.json` only to record truthful current/deferred states.
- Create: `materials/33/source-evidence/2026-08-20-accessible-fullscreen/clone-local-auth-learning-check.json`

**Interfaces:**
- Consumes all route tests, settled Playwright reports, and the existing diagnostic contract.
- Produces an explicit 23-row coverage report with no deferred state mislabeled as source-complete.

- [ ] **Step 1: Run the public regression suite first.**

Run: `pytest materials/33/clone/tests/test_business_category_fidelity.py materials/33/clone/tests/test_public_frontend.py materials/33/clone/tests/test_search_page_fidelity.py materials/33/clone/tests/test_fullscreen_geometry_fidelity.py -q`.

Expected: existing public pages remain unchanged.

- [ ] **Step 2: Run auth, learner, and checkout suites with isolated databases.**

Run: `pytest materials/33/clone/tests/test_learning_backend.py materials/33/clone/tests/test_checkout_flow.py materials/33/clone/tests/test_checkout_backend.py -q`.

Expected: no cross-test account/order leakage; warnings may be reported but failures are not ignored.

- [ ] **Step 3: Run all settled Playwright scenarios at `1692 x 979`.**

For every scenario, record final height, headings, cards, image health, failed requests, console errors, and incomplete reasons. Any incomplete scenario is reported as incomplete and blocks a completion claim for that surface.

- [ ] **Step 4: Run repository diagnostics.**

Run: `python tools/offline_clone/run.py verify --site materials/33`

Record static findings and any Harbor `Errno 95` live incompleteness separately; do not convert diagnostics into a hard gate.

- [ ] **Step 5: Keep the preview service running and stop for manual review.**

Serve on `127.0.0.1:8045`, verify HTTP 200 for the reviewed routes, report completed/deferred journeys, and do not commit or deploy.

## Completion Criteria

- All selected slice tests pass with isolated site-33 state.
- All selected browser scenarios report `complete=true`, no failed images, no remote requests, and no console errors.
- Public Business snapshot remains `8990px` with 34 cards and 90 images.
- Every deferred source state remains explicitly deferred in the phase matrix.
- No real credential, email, payment, or external side effect is introduced.

## Authenticated implementation progress (2026-08-20)

- The public login dialog now retains both local review identities: `Continue with local learner` opens the source-observed empty-account surface, while `Continue with learning demo` opens the seeded enrolled learner through the same generated site-33 auth/session seam.
- The seeded learner exposes My Learning, resume, lesson/unit navigation, bookmark, progress, local quiz feedback, local review, preferences, enrollment history, and order history without contacting Coursera.
- My Learning's In Progress, Completed, and Certificates tabs are server-backed filters. Empty completed/certificate collections are explicit; certificate-bearing enrollments appear only after the deterministic completion contract is satisfied.
- Paid enrollment remains limited to `local-sandbox`. Payment-looking fields have no submitted names, no payment credentials are accepted, and source-side enrollment, trial, quiz, review, cancellation, recovery mail, and payment submission remain forbidden.
- Focused authenticated/backend verification after these changes: 77 tests passed. Browser verification at `1692 x 979` reached the enrolled dashboard, completed empty state, resume lesson, bookmark control, and local quiz control.
- A subsequent strict 23-journey audit closed four reachability/state gaps: the course detail now links to its deterministic anonymous first-lesson preview; Learning Goal choices submit to and persist through the owner profile; Saved Lessons and Course Progress have authenticated collection routes with counts and resume state; and Enrollment History records link to owner-bound details with status, track, cancellation/order management, and collection recovery.
- `scope/current-accessible-fullscreen-phase.json` now distinguishes source-evidence deferral from clone implementation. The source remains read-only and several source states remain unobserved, while all 23 frozen journey IDs are explicitly mapped to local implementation with external effects forbidden.
