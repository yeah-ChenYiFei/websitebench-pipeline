# Coursera Learner Complete Pre-Enrollment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Do not dispatch subagents unless the user explicitly authorizes delegation.

**Goal:** Incrementally extend the existing `materials/33` offline Coursera clone until nearly all ordinary-learner public and authenticated-unenrolled functionality is source-grounded and functional, with Deep Learning stopping safely at an empty payment page.

**Architecture:** Preserve the current FastAPI/Jinja-or-renderer presentation, WebsiteBench account/session/mail seam, SQLite learning state, and local checkout seam. Add a configuration-driven route/state inventory, acquire current English evidence with Playwright, and implement one independently tested product slice at a time without rebuilding accepted pages or creating a second backend.

**Tech Stack:** Python 3.14, FastAPI, existing WebsiteBench site backend, SQLite, existing renderer/templates, vanilla JavaScript/CSS, pytest, Playwright 1.61, `tools/offline_clone/run.py`.

## Global Constraints

- Site root is `materials/33`; preserve `site_id=33` and its independent `backend/runtime.json`, SQLite identity, session cookie, mail branding, and payment profile.
- Runtime language is English; do not add new user-visible Chinese copy.
- Acceptance viewport is exactly `1692 × 979`; desktop fullscreen is the only visual target.
- Frontend target is approximately 90% similarity; core backend behavior is mandatory.
- Continue incrementally from existing `materials/33`; do not create a second site, backend, database, auth store, mail system, or SPA rewrite.
- Current phase includes public and authenticated-unenrolled learner functionality; enrolled-only lesson, quiz, progress, certificate, review, and populated-history pages require later source evidence and must not be newly redesigned now.
- Deep Learning stops at the payment page with empty fields and validation; no payment submission, order, subscription, enrollment, or post-enrollment state transition occurs in this phase.
- Real Coursera mutation, real identity providers, real email, card data, CVV, expiry, wallet credentials, live keys, and live charges are forbidden.
- Use current English Playwright evidence as presentation authority; never invent cards, identities, routes, or interactions outside evidence.
- Scroll and settle every long page so lazy-loaded content and the page end are included before declaring a route complete.
- Keep all implementation changes uncommitted until the user explicitly authorizes a commit.

## File and responsibility map

- `materials/33/scope/learner-coverage.json` — expanded source-route/state inventory and status matrix.
- `materials/33/source-evidence/2026-08-20-learner-expansion/` — compact sanitized Playwright reports and canonical screenshots.
- `materials/33/clone/source_inventory.py` — loader and validation for the coverage inventory.
- `materials/33/clone/app.py` — existing route boundaries and thin composition only; modify only for missing route wiring.
- `materials/33/clone/home_page.py`, `browse_page.py`, `category_page.py`, `search_page.py`, `course_page.py`, `specialization_page.py`, and `data_science_page.py` — existing public renderer modules; extend only with evidence-backed view models.
- `materials/33/clone/templates/` and `materials/33/clone/static/` — route presentation and evidenced client interactions.
- `materials/33/clone/backend/learning_db.py` and existing checkout module — authoritative local state; no parallel persistence layer.
- `materials/33/clone/tests/test_learner_coverage_inventory.py` — inventory integrity and core-blocking checks.
- `materials/33/clone/tests/test_public_frontend.py`, `test_search_page_fidelity.py`, `test_discovery_fidelity.py`, `test_authenticated_empty_surfaces.py`, `test_learning_backend.py`, and `test_checkout_flow.py` — focused regression suites.
- `materials/33/scope/current-accessible-fullscreen-phase.json` — update only when an evidence-backed current/deferred boundary changes.
- `materials/33/KNOWN_DIFFERENCES.md` — record honest evidence gaps and intentionally deferred enrolled-only states.

## Task 1: Establish the expanded coverage inventory

**Files:**
- Create: `materials/33/scope/learner-coverage.json`
- Create: `materials/33/clone/source_inventory.py`
- Create: `materials/33/clone/tests/test_learner_coverage_inventory.py`
- Read: `materials/33/scope/journeys.json`, `materials/33/scope/current-accessible-fullscreen-phase.json`, `docs/superpowers/specs/2026-08-20-coursera-learner-complete-pre-enrollment-design.md`

**Interfaces:**
- `load_inventory(path: Path | None = None) -> dict`
- `iter_entries(inventory: dict) -> tuple[dict, ...]`
- Each entry has `id`, `surface`, `source_route`, `local_route`, `state`, `evidence_status`, `core`, `backend_capability`, `test_modules`, and `status`.
- Valid statuses are exactly `direct-source-complete`, `local-functional-complete`, `implemented-browser-unverified`, `evidence-incomplete`, `deferred-enrolled-source-required`, and `out-of-scope`.

- [ ] **Step 1: Write failing inventory tests.** Assert the file loads, every entry has the required fields, IDs are unique, every local route starts with `/`, all original 23 journey IDs are represented as `baseline:<journey-id>`, core entries have non-empty test modules, and no entry marked `direct-source-complete` lacks an evidence path.
- [ ] **Step 2: Run the tests to verify RED.** Run `pytest materials/33/clone/tests/test_learner_coverage_inventory.py -q`; expected failure is missing inventory/module.
- [ ] **Step 3: Add the inventory and loader.** Populate baseline entries plus discovered learner domains from the approved design. Mark enrolled-only entries `deferred-enrolled-source-required`; do not label inferred pages direct-source complete. Validate statuses and required fields in `load_inventory`.
- [ ] **Step 4: Run the focused tests to verify GREEN.** Run the same command; expected result is all inventory assertions passing.
- [ ] **Step 5: Run existing phase-matrix regression.** Run `pytest materials/33/clone/tests/test_current_phase_matrix.py -q`; expected result is all existing boundary assertions still pass.

## Task 2: Reacquire current English public and authenticated-unenrolled evidence

**Files:**
- Create: `materials/33/source-evidence/2026-08-20-learner-expansion/public-inventory-en.json`
- Create: `materials/33/source-evidence/2026-08-20-learner-expansion/authenticated-unenrolled-en.json`
- Create: `materials/33/source-evidence/2026-08-20-learner-expansion/payment-empty-en.json`
- Create: `materials/33/source-evidence/2026-08-20-learner-expansion/screenshots/`
- Modify: `materials/33/scope/learner-coverage.json`
- Use: repository Playwright/WebsiteBench exploration path and `materials/33/clone/browser_settle.py`

**Interfaces:**
- Evidence records are sanitized JSON and contain no cookies, storage state, headers, credentials, payment values, or personal identifiers.
- Every route/state record contains `requested_path`, `observed_path`, `title`, `headings`, `controls`, `links`, `viewport`, `document_height`, `image_health`, `remote_references`, `interaction_notes`, and `evidence_classification`.

- [ ] **Step 1: Verify the approved-origin capture configuration.** Confirm source origin is Coursera, mutation blocking is enabled, locale is English, viewport is `1692×979`, and output paths are inside the expansion evidence directory.
- [ ] **Step 2: Capture public navigation and full pages.** Start at the current English homepage; inspect Explore, Browse, categories, search, filters, product types, recommendations, Help, Contact, Terms, Privacy, and 404. Scroll each page to a stable document height and retain one compact report per route/state.
- [ ] **Step 3: Ask the user to operate the temporary source session when needed.** The user enters credentials and handles any challenge; the session is used only to inspect authenticated-unenrolled account surfaces and navigate to the empty payment page, then stops before payment submission.
- [ ] **Step 4: Capture safe interactions.** Record source-observed menu, tab, filter, accordion, dialog, manual-switch, validation, and recovery states only when they cause no source mutation.
- [ ] **Step 5: Sanitize and validate evidence.** Run the repository evidence sanitizer and reject any report containing credentials, cookies, tokens, payment-looking values, remote runtime asset dependencies, or unstable document height.
- [ ] **Step 6: Update inventory statuses.** Link each captured route/state to its evidence file and leave missing or enrolled-only routes explicitly deferred.

## Task 3: Protect shared chrome and core navigation

**Files:**
- Modify: `materials/33/clone/ui.py`
- Modify: `materials/33/clone/static/desktop-base.css`, `desktop-chrome.css`, `auth-dialog.js`
- Modify: `materials/33/clone/app.py` only for missing safe route aliases
- Test: `materials/33/clone/tests/test_public_frontend.py`, `test_anonymous_journey_matrix.py`, `test_learner_coverage_inventory.py`

**Interfaces:**
- `ui.header(authenticated: bool, search_value: str = "", language: str = "en") -> str`
- `ui.footer(language: str = "en", variant: str = "default") -> str`
- Existing `[data-login-open]`, `[data-login-dialog]`, and `next` continuation contracts remain stable.

- [ ] **Step 1: Add failing assertions for current English chrome.** Assert shared wordmark, Explore, Degrees, search, authenticated account menu, login dialog same-page behavior, footer recovery links, and no remote asset references at `1692×979`.
- [ ] **Step 2: Run the focused tests to verify RED.** Run `pytest materials/33/clone/tests/test_public_frontend.py materials/33/clone/tests/test_anonymous_journey_matrix.py -q`; isolate any failures attributable to evidence differences rather than Chromium environment.
- [ ] **Step 3: Implement the smallest chrome corrections.** Use current evidence for labels, order, shell width, dialog backdrop, and invoking-page preservation. Do not add animation or change unrelated accepted page markup.
- [ ] **Step 4: Run HTTP and browser checks.** Run the focused route tests and `pytest materials/33/clone/tests/test_anonymous_journey_matrix.py -q`; verify login dialog and enrollment CTA tests with Playwright.
- [ ] **Step 5: Check complete local loading.** At `1692×979`, assert zero broken images, zero failed requests, zero console errors, and no horizontal overflow on Home, Browse, Search, and Login.

## Task 4: Complete public discovery and evidence-backed product surfaces

**Files:**
- Modify: existing public renderer modules under `materials/33/clone/*_page.py`
- Modify: `materials/33/clone/app.py` for only evidence-backed route wiring
- Modify: route-specific CSS/JS under `materials/33/clone/static/`
- Test: `test_discovery_fidelity.py`, `test_search_page_fidelity.py`, `test_learning_public_fidelity.py`, `test_desktop_contract.py`, `test_desktop_visual.py`

**Interfaces:**
- Existing renderers continue returning HTML strings consumed by `_page(...)`.
- Evidence-backed card view models must expose `title`, `provider`, `href`, `image`, and observed metadata; no renderer may synthesize a missing identity.

- [ ] **Step 1: Add failing content and interaction tests from the new evidence.** Cover complete lower sections, all observed product-type cards, saved/recent controls where present, search suggestions, filter families, sorting/pagination, and public preview/sample states.
- [ ] **Step 2: Run focused tests to verify RED.** Run `pytest materials/33/clone/tests/test_discovery_fidelity.py materials/33/clone/tests/test_search_page_fidelity.py materials/33/clone/tests/test_learning_public_fidelity.py -q` and record each missing source-grounded behavior.
- [ ] **Step 3: Implement evidence-backed view models and routes.** Reuse local assets when provenance matches; add missing local assets only from approved evidence. Keep cards, headings, order, links, and complete-page sections aligned with the capture. Add only source-observed client interactions.
- [ ] **Step 4: Implement backend wiring for saved/recent state if evidence requires it.** Use owner-scoped `learning_db` state, anonymous-safe behavior, POST/Redirect/GET, and persistence across refresh; do not add a second store.
- [ ] **Step 5: Run focused tests and complete-load browser checks.** Require full page settling, all lazy sections, zero failed images/requests, and stable document height for each changed route.

## Task 5: Complete authenticated-unenrolled account surfaces

**Files:**
- Modify: `materials/33/clone/app.py`
- Modify: `materials/33/clone/backend/learning_db.py` only for missing owner-scoped pre-enrollment state
- Modify: `materials/33/clone/static/learning-desktop.css` and account-specific assets/templates
- Test: `materials/33/clone/tests/test_authenticated_empty_surfaces.py`, `test_learning_backend.py`, `test_desktop_contract.py`

**Interfaces:**
- Existing routes remain canonical: `/my-learning`, `/my-purchases/transactions`, `/account-settings`, `/account/preferences`, `/updates`, `/onboarding/learning-goal`, `/local-inbox`, `/orders` where visible before enrollment.
- State access continues through `_authenticated_subject(request)` and existing learning/checkout services.

- [ ] **Step 1: Add failing tests for every source-observed unenrolled account section.** Cover account menu routes, Purchases lower sections, Updates, settings/preferences, learning goals, empty states, validation, signed-out permission, and owner isolation.
- [ ] **Step 2: Run focused tests to verify RED.** Run `pytest materials/33/clone/tests/test_authenticated_empty_surfaces.py materials/33/clone/tests/test_learning_backend.py -q -k 'account or purchase or update or preference or goal or local_inbox'`.
- [ ] **Step 3: Implement missing account state and markup.** Render source-observed English content and complete-page sections; persist only local learner-owned values; keep controls outside the current evidence or current phase explicitly disabled or deferred.
- [ ] **Step 4: Implement local validation and failure recovery.** Ensure signed-out access returns a permission prompt, malformed IDs do not disclose other accounts, empty collections have source-grounded copy, and refresh/restart preserve included local state.
- [ ] **Step 5: Run focused tests and Playwright complete-load checks.** Inspect My Learning, Purchases, Settings, Updates, and Goals at `1692×979`, including full scroll and image/request/console health.

## Task 6: Complete identity lifecycle and local mail boundary

**Files:**
- Modify: `materials/33/clone/app.py`
- Modify: existing auth integration only through `websitebench.site_backend`
- Modify: `materials/33/clone/static/auth-dialog.js` and auth CSS/templates
- Test: `materials/33/clone/tests/test_learning_backend.py`, `test_authenticated_empty_surfaces.py`, `test_anonymous_journey_matrix.py`

**Interfaces:**
- Existing handlers remain the only mutation endpoints: `/auth/registration/start`, `/auth/registration/verify`, `/auth/login`, `/auth/logout`, `/auth/recovery/start`, `/auth/recovery/complete`.
- Local verification and reset codes are consumed through `/local-inbox`; no external mail call is introduced.

- [ ] **Step 1: Add failing lifecycle tests.** Cover registration validation, verification, invalid/expired code, login/logout, session continuity, recovery non-enumeration, password change, same-page `next` continuation, provider boundaries, and no secret echo.
- [ ] **Step 2: Run auth tests to verify RED.** Run `pytest materials/33/clone/tests/test_learning_backend.py materials/33/clone/tests/test_anonymous_journey_matrix.py -q -k 'registration or recovery or login or logout or provider or session'`.
- [ ] **Step 3: Implement only missing local lifecycle wiring.** Preserve generated session cookies, local inbox behavior, site isolation, and safe error wording. Keep provider links presentational.
- [ ] **Step 4: Run lifecycle tests and browser flows.** Verify anonymous login dialog, signup, recovery, local inbox, logout, and return-to-invoking-page behavior with Playwright.
- [ ] **Step 5: Scan for sensitive leakage.** Assert no password, verification code, token, cookie, or payment value appears in HTML, logs, evidence, or database rows.

## Task 7: Complete Deep Learning pre-enrollment and payment-page boundary

**Files:**
- Modify: `materials/33/clone/app.py`
- Modify: existing checkout renderer/backend only for missing pre-submission behavior
- Modify: checkout CSS/templates and `ui.py` static revision
- Test: `materials/33/clone/tests/test_checkout_flow.py`, `test_checkout_backend.py`, `test_learning_public_fidelity.py`

**Interfaces:**
- Existing routes: `/specializations/deep-learning`, `/checkout/deep-learning`, `/payments/checkout`, `/checkout/{draft_id}/payment`, `/checkout/{draft_id}/review`.
- Server-owned checkout facts are returned by existing draft/checkout functions; current phase must not call the final attempt endpoint.

- [ ] **Step 1: Add failing payment-boundary tests.** Require signed-out continuation, selected plan preservation, exact observed currency/trial/price/tax/total/renewal facts, empty payment fields, required-field validation, no order creation, and no enrollment after any page interaction.
- [ ] **Step 2: Run checkout tests to verify RED.** Run `pytest materials/33/clone/tests/test_checkout_flow.py materials/33/clone/tests/test_checkout_backend.py -q`.
- [ ] **Step 3: Implement the smallest source-grounded page and validation fixes.** Keep payment-looking inputs unnamed or excluded from mutation payloads, expose only safe local facts, preserve owner and draft checks, and stop before any order/enrollment transition.
- [ ] **Step 4: Run checkout tests and browser settling.** At `1692×979`, verify course-to-login-to-payment navigation, stable totals, empty-field validation, no remote requests, no broken images, and no console errors.
- [ ] **Step 5: Verify no downstream mutation.** Query the isolated test database before and after the payment-page scenario; assert order and enrollment counts are unchanged.

## Task 8: Cross-slice regression and diagnostic evidence

**Files:**
- Modify: `materials/33/scope/learner-coverage.json` with verified statuses only
- Modify: `materials/33/KNOWN_DIFFERENCES.md`
- Create: `materials/33/source-evidence/2026-08-20-learner-expansion/clone-validation.json`
- Test: all `materials/33/clone/tests/` relevant to current phase

**Interfaces:**
- `clone-validation.json` reports route/state, status, viewport, document height, headings, image health, failed requests, console errors, and incomplete reasons without sensitive data.

- [ ] **Step 1: Run the public regression suite.** Run `pytest materials/33/clone/tests/test_public_frontend.py materials/33/clone/tests/test_discovery_fidelity.py materials/33/clone/tests/test_search_page_fidelity.py materials/33/clone/tests/test_fullscreen_geometry_fidelity.py -q`; all failures must be fixed or explicitly reported.
- [ ] **Step 2: Run account and checkout semantic suites.** Run `pytest materials/33/clone/tests/test_authenticated_empty_surfaces.py materials/33/clone/tests/test_learning_backend.py materials/33/clone/tests/test_checkout_flow.py materials/33/clone/tests/test_checkout_backend.py -q` with isolated site-33 state.
- [ ] **Step 3: Replay every included browser route at `1692×979`.** Use Playwright to settle complete pages, exercise included interactions, and record image/request/console/height results in `clone-validation.json`.
- [ ] **Step 4: Run static and live diagnostics.** Run `python tools/offline_clone/run.py verify --site materials/33`; record static findings and Harbor `Errno 95` incompleteness separately.
- [ ] **Step 5: Run a sensitive-data and remote-closure scan.** Confirm zero runtime remote presentation references, no secrets, no payment credential names/values, and no new external side effects.
- [ ] **Step 6: Update truthful coverage and known differences.** Mark only evidence-backed verified routes complete; preserve deferred-enrolled-source-required entries and document any browser or Harbor environment limitations.
- [ ] **Step 7: Leave the preview running for manual review.** Serve `127.0.0.1:8045`, verify HTTP 200 on changed routes, report complete/partial/deferred entries, and do not commit.

## Completion checklist

- [ ] All core capabilities in section 3.4 of the design are complete and verified.
- [ ] Nearly all discovered ordinary-learner public and authenticated-unenrolled routes are complete or have an explicit evidence-incomplete reason.
- [ ] Deep Learning reaches the accurate empty payment page and stops before mutation.
- [ ] No enrolled-only page is newly designed without source evidence.
- [ ] Existing 23-journey regression tests remain green.
- [ ] Full-page lazy content, image health, local network closure, and browser interactions are verified.
- [ ] Account, session, owner isolation, validation, and checkout boundary tests pass.
- [ ] Static/live diagnostics and Harbor limitations are reported honestly.
- [ ] No commit, deploy, real mail, real payment, or source mutation occurred.

