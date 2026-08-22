# Coursera Accessible Fullscreen Phase Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task in the current workspace. Execution is inline, uses review checkpoints, preserves unrelated dirty work, makes no commits, and does not dispatch subagents.

**Goal:** Reconstruct every source-accessible Coursera surface covered by the 23 original journeys in `materials/33`, at the user's actual fullscreen CSS viewport of exactly `1692 × 979`, while truthfully deferring states that require enrollment, payment credentials, or populated learning history.

**Architecture:** Keep the generated site-33 backend runtime and its `websitebench.site_backend` integration seam. Add a current-phase scope overlay instead of modifying frozen journey identity, acquire source evidence in route-family batches, then render source-backed route view models through focused Jinja templates and a shared fullscreen shell. Verify literal source geometry, content identity, route behavior, local asset closure, and allowed local interactions with route-family Playwright tests and the repository's WebsiteBench diagnostics.

**Tech Stack:** Python 3, FastAPI, Jinja2, generated WebsiteBench site backend, pytest, Playwright/WebsiteBench offline-clone tools, HTML/CSS/vanilla JavaScript, SQLite only through the generated backend runtime.

## Global Constraints

- Canonical site and sole runtime: `materials/33`.
- Runtime presentation language: English.
- Primary and only acceptance viewport: actual CSS viewport `1692 × 979`.
- Do not optimize for split-screen, reduced windows, mobile, `1191 × 979`, or the historical `1440 × 900` capture plan.
- Do not commit. Preserve all unrelated dirty and untracked work.
- Do not mutate, normalize, or reinterpret `materials/33/scope/journeys.json`, historical evidence, hashes, or frozen records.
- Add no new hash, quality-gate, approval, auth, mail, payment, or database infrastructure.
- Source exploration is GET-only except for the user-authorized navigation that reaches the empty payment page; never submit enrollment, trial, payment, quiz, review, cancellation, recovery mail, or another source mutation.
- The user enters source credentials personally in a temporary interactive browser. Never request, observe, log, screenshot, persist, or store credentials, cookies, tokens, payment data, or personal identifiers.
- Stop at empty payment fields. Do not enter a card number, billing credential, wallet credential, or payment scenario on the source.
- Runtime presentation assets must be local. Do not add live Coursera image, font, CSS, script, API, or proxy dependencies.
- Reproduce only observed source content and states. Do not invent cards, lessons, previews, history, orders, certificates, or learning states.
- User screenshots override unstable source A/B states when the user has selected the screenshot state.
- No animation where the source has none. Observed source animation is optional when it is useful and economical.
- Measure width and geometry numerically before iterating on card styling. Header, route shell, sections, grids, cards, and footer may have different source containers.
- Reuse retained evidence when it is current and decisive; revisit the source only for a recorded evidence gap.
- Ask the user immediately if an A/B state, authenticated route, or source authority remains genuinely ambiguous after safe inspection.

## File and Responsibility Map

- `materials/33/scope/current-accessible-fullscreen-phase.json`: non-historical overlay mapping all 23 journeys to current, partial, conditional, or deferred coverage.
- `materials/33/scope/source-accessible-fullscreen-explore.json`: approved-origin, `1692 × 979`, public route-family acquisition specification.
- `materials/33/scope/verify.json`: current local diagnostic checkpoints and route aliases only; no historical evidence identity.
- `materials/33/source-evidence/2026-08-19-accessible-fullscreen/`: sanitized current-phase source observations, downloaded local media, geometry tables, and route-family screenshots.
- `materials/33/clone/ui.py`: shared English header, navigation, footer, buttons, notices, page shell, and common card primitives.
- `materials/33/clone/app.py`: FastAPI routing, query/form parsing, backend integration, permission boundaries, and route view-model selection.
- `materials/33/clone/{home_page,browse_page,data_science_page,search_page,specialization_page,course_page}.py`: explicit source-backed view models for existing public route families.
- `materials/33/clone/account_page.py`: source-backed view models for sign-in, sign-up, recovery, empty account, preferences, history, payment, help/contact, and not-found states.
- `materials/33/clone/templates/pages/*.html`: route-scoped accessible markup without embedded source network dependencies.
- `materials/33/clone/static/desktop-chrome.css`: shared `1692 × 979` shell geometry and common typography/control tokens.
- `materials/33/clone/static/*.css`: genuine route-specific geometry and presentation.
- `materials/33/clone/tests/test_current_phase_matrix.py`: 23-journey overlay validity and deferred-boundary assertions.
- `materials/33/clone/tests/test_*_fidelity.py`: source-backed content, geometry, route, and interaction contracts by route family.

## Current 23-Journey Mapping

| # | Journey ID | Current-phase boundary | Required evidence/result |
|---:|---|---|---|
| 1 | `public.browse` | Current, complete | Public entry → primary navigation → Browse; heading and canonical local path visible. |
| 2 | `enrollment.deep-learning-review` | Partial | Deep Learning choice and source empty payment page only; enrollment completion and post-payment review deferred. |
| 3 | `catalog.subject` | Current, complete | Browse and every reachable source category required by the original scope, with literal source records. |
| 4 | `catalog.search-filter` | Current, complete | Search plus observed level/topic/duration/rating/language/schedule filters and deterministic local results. |
| 5 | `catalog.course-detail` | Current, complete where visible | Syllabus, instructor, prerequisites, reviews, pricing, and enrollment options exactly as source-accessible. |
| 6 | `catalog.preview` | Conditional | Build only if a real anonymous public preview/sample lesson is observed; otherwise record `not-source-accessible` and add no page. |
| 7 | `auth.signup-local` | Partial | Registration entry; onboarding only if directly observable without creating a new source account. Account creation completion deferred. |
| 8 | `auth.login-dashboard` | Partial | Empty signed-in dashboard reached through user-assisted temporary session; populated enrolled courses deferred. |
| 9 | `enrollment.track-selection` | Partial | Source-observed enrollment/track options and navigation to empty payment only; selection completion deferred. |
| 10 | `enrollment.paid-review` | Partial | Paid option and empty payment page only; payment input, order review, confirmation, and outcomes deferred. |
| 11 | `learning.lesson` | Deferred | Requires an enrolled source account. No synthetic lesson page is presented as source fidelity. |
| 12 | `learning.quiz-feedback` | Deferred | Requires an enrolled source account and source mutation. |
| 13 | `learning.progress` | Deferred | Resume, bookmark, progress, and completion require enrolled source state. |
| 14 | `learning.preferences` | Partial | Directly observed empty-account learning preferences only; certificates and review/rating submission deferred. |
| 15 | `search.no-results` | Current, complete | `zzzz-no-match-websitebench`, visible no-results recovery, route back to Browse. |
| 16 | `auth.login-shell` | Current, complete | Email/username field, password/identity-provider choices, and safe return without submission. |
| 17 | `auth.signup-shell` | Current, complete | Visible identity fields, terms links, and verification guidance without account creation. |
| 18 | `auth.recovery-shell` | Current, complete | Reset-address field, validation guidance, return link; never send recovery mail. |
| 19 | `history.seeded` | Partial | Directly observed empty history only; newest populated record, edit, and cancellation deferred. |
| 20 | `validation.required-or-signed-out` | Current, complete | Inline required-field or signed-out permission prompt with no mutation. |
| 21 | `support.public` | Current, complete | Public help/contact guidance for discovery, access, and failed actions without private data. |
| 22 | `recovery.not-found` | Current, complete | Branded 404 with preserved primary navigation and safe route to Browse. |
| 23 | `task265.deep-learning-review` | Partial | Public entry → Deep Learning Specialization → source empty payment page; final review/confirmation and totals after payment credentials deferred. |

---

### Task 1: Freeze the Current-Phase Matrix and Evidence Contract

**Files:**
- Create: `materials/33/scope/current-accessible-fullscreen-phase.json`
- Create: `materials/33/scope/source-accessible-fullscreen-explore.json`
- Create: `materials/33/clone/tests/test_current_phase_matrix.py`
- Read only: `materials/33/scope/journeys.json`
- Read only: `materials/33/scope/source-capture-plan.json`

**Interfaces:**
- Consumes: immutable journey objects keyed by `journeys[].id`.
- Produces: `current-accessible-fullscreen-phase.v1` with `viewport`, `source_mutation_policy`, and exactly 23 `coverage` records containing `journey_id`, `phase_status`, `current_boundary`, `deferred_boundary`, and `evidence_refs`.

- [ ] **Step 1: Add a failing matrix contract test.** Assert the viewport equals `{"width": 1692, "height": 979}`, the journey ID set exactly equals the frozen set, every record has a non-empty current/deferred boundary, journeys 11–13 are `deferred`, journeys 2/10/23 stop at `empty-payment-fields`, and journey 6 is `conditional-source-observation`.
- [ ] **Step 2: Run the focused test and confirm failure because the overlay does not exist.**

  Run: `python -m pytest materials/33/clone/tests/test_current_phase_matrix.py -q`

- [ ] **Step 3: Create the overlay and public exploration spec.** Keep old files byte-for-byte unchanged; declare only `GET`, configured Coursera origins, `1692 × 979`, route-family action lists, sanitized output directory, and explicit forbidden source submissions.
- [ ] **Step 4: Run the matrix test and a secret-pattern scan.**

  Run: `python -m pytest materials/33/clone/tests/test_current_phase_matrix.py -q`

  Run: `rg -n -i "(password|card.?number|authorization:|cookie:|storage_state|sessionid)" materials/33/scope/current-accessible-fullscreen-phase.json materials/33/scope/source-accessible-fullscreen-explore.json`

  Expected: pytest passes; scan finds only policy field names, never a value resembling a credential, cookie, card number, or token.

### Task 2: Acquire Public Evidence in Route-Family Batches

**Files:**
- Create: `materials/33/source-evidence/2026-08-19-accessible-fullscreen/public-index.json`
- Create: `materials/33/source-evidence/2026-08-19-accessible-fullscreen/{home,browse,categories,search,learning,access-support}/`
- Modify: `materials/33/scope/current-accessible-fullscreen-phase.json`

**Interfaces:**
- Consumes: `source-accessible-fullscreen-explore.json` and retained source evidence already under `materials/33/source-evidence/`.
- Produces: one sanitized observation per distinct route/state with `url`, `canonical_path`, `headings`, ordered `sections`, controls, destinations, asset provenance, and literal `DOMRect` geometry at `1692 × 979`.

- [ ] **Step 1: Discover the repository-supported exploration syntax once.**

  Run: `python tools/offline_clone/run.py tools list`

  Run: `python tools/offline_clone/run.py tools explore --help`

- [ ] **Step 2: Reuse retained evidence and write an explicit gap list.** Mark a route/state reusable only when its route, selected A/B state, content identity, and relevant geometry are decisive for `1692 × 979`; do not reacquire merely because an older screenshot has a different height if numeric horizontal geometry is already authoritative.
- [ ] **Step 3: Run one public walk per route family.** Capture homepage/shared chrome/manual promo states; Explore/Browse/all reachable categories; search/base filters/no-results; specialization/course and any real public preview; login/signup/recovery/help/contact/404; required validation/signed-out prompts. Each walk records all text, links, images, `getBoundingClientRect()` values, and materially different interaction states together.
- [ ] **Step 4: Download only in-scope presentation media through the approved acquisition path.** Store local filenames and first-party/observed third-party provenance in `public-index.json`; never copy scripts, trackers, cookies, or authorization headers.
- [ ] **Step 5: Classify every gap.** Use only `captured`, `reused-current-evidence`, `not-source-accessible`, or `blocked-needs-user-clarification`; never fill a gap with inferred card identity or invented copy.

### Task 3: Capture Temporary Empty-Account and Empty-Payment Evidence

**Files:**
- Create: `materials/33/source-evidence/2026-08-19-accessible-fullscreen/authenticated-sanitized.json`
- Modify: `materials/33/scope/current-accessible-fullscreen-phase.json`

**Interfaces:**
- Consumes: an interactive temporary Playwright session at `1692 × 979` in which the user personally enters credentials and personally navigates to the authorized payment page.
- Produces: sanitized structural observations only for directly reachable empty dashboard/profile/preferences/history and the payment page stopped before sensitive input.

- [ ] **Step 1: Verify that the supported browser path permits an interactive local handoff without recording storage state.** If it does not, stop this task and tell the user; do not switch silently to SingleFile, cloud credential entry, copied cookies, or chat credentials.
- [ ] **Step 2: Open the temporary session and yield control for user login.** Do not inspect keyboard input, request bodies, cookies, local storage, or identity values.
- [ ] **Step 3: After the user confirms login, batch-record only non-personal layout, headings, empty states, navigation, controls, paths, and geometry for directly reachable account surfaces.** Mask any visible name/email in screenshots and omit them from JSON.
- [ ] **Step 4: Yield control while the user personally reaches the payment page and stops before payment input.** Record plan/choice labels, visible totals, empty field labels, validation guidance, return route, and geometry; do not focus, fill, submit, or continue a sensitive field.
- [ ] **Step 5: Close the temporary context and verify no profile, storage-state file, cookies, tokens, payment data, or personal identifiers were retained.** Mark inaccessible surfaces deferred rather than simulating source facts.

### Task 4: Establish the Shared Fullscreen Shell and Literal Geometry Contracts

**Files:**
- Modify: `materials/33/clone/ui.py`
- Modify: `materials/33/clone/static/desktop-chrome.css`
- Modify: `materials/33/clone/app.py`
- Modify: `materials/33/clone/tests/test_desktop_contract.py`
- Modify: `materials/33/clone/tests/test_desktop_visual.py`
- Create: `materials/33/clone/tests/test_fullscreen_geometry_fidelity.py`

**Interfaces:**
- Consumes: public evidence geometry table with route-specific header/main/section/grid/footer bounds.
- Produces: `render_page_shell(*, title: str, body: str, route_class: str, authenticated: bool = False) -> str`, shared source-backed header/footer fragments, and literal geometry assertions at `1692 × 979`.

- [ ] **Step 1: Write failing browser geometry tests.** Launch at viewport `1692 × 979`; assert the browser reports that exact `document.documentElement.clientWidth/clientHeight`, then compare each major region to source literals with per-property tolerances recorded from capture noise. Do not derive expected values from clone elements.
- [ ] **Step 2: Run only the new shell tests and preserve the failure output as the repair list.**

  Run: `python -m pytest materials/33/clone/tests/test_fullscreen_geometry_fidelity.py materials/33/clone/tests/test_desktop_contract.py -q`

- [ ] **Step 3: Implement shared header, Explore control, search/navigation, authentication actions, footer, focus states, typography, and page shell.** Keep route container widths independent where source measurements differ.
- [ ] **Step 4: Re-run shell and existing desktop tests.** Update historical viewport assertions only where they incorrectly claim to be current acceptance; retain historical artifacts as historical evidence.

  Run: `python -m pytest materials/33/clone/tests/test_fullscreen_geometry_fidelity.py materials/33/clone/tests/test_desktop_contract.py materials/33/clone/tests/test_desktop_visual.py -q`

### Task 5: Complete Homepage, Browse, Explore, and All Reachable Categories

**Files:**
- Modify: `materials/33/clone/home_page.py`
- Modify: `materials/33/clone/browse_page.py`
- Modify: `materials/33/clone/data_science_page.py`
- Modify: `materials/33/clone/app.py`
- Modify: `materials/33/clone/templates/pages/home.html`
- Modify: `materials/33/clone/templates/pages/browse.html`
- Modify: `materials/33/clone/templates/pages/data_science.html`
- Modify: `materials/33/clone/static/home-prototype.css`
- Modify: `materials/33/clone/static/browse-prototype.css`
- Modify: `materials/33/clone/static/data-science-category.css`
- Modify: `materials/33/clone/tests/test_public_frontend.py`
- Modify: `materials/33/clone/tests/test_data_science_category.py`
- Create: `materials/33/clone/tests/test_discovery_fidelity.py`

**Interfaces:**
- Consumes: exact ordered source section/card inventory, local asset map, canonical category destinations, and section-specific geometry.
- Produces: explicit view models for homepage and discovery routes; primary navigation reaches `/browse`; each observed category path renders its own source-backed content instead of title-derived generic cards.

- [ ] **Step 1: Add failing content-identity tests.** Assert exact ordered homepage sections, manual promo choices, Explore items, Browse headings, category names, provider/title/image/link identity, image heights, and the absence of the unobserved AI sidebar. Include the user-selected `What brings you to Coursera today?` block geometry and its four source labels.
- [ ] **Step 2: Run the discovery tests and inspect failures by route, not screenshot iteration.**

  Run: `python -m pytest materials/33/clone/tests/test_discovery_fidelity.py materials/33/clone/tests/test_data_science_category.py -q`

- [ ] **Step 3: Implement exact explicit route data and local assets.** Preserve the already-corrected four-button block: source-relative narrow buttons, `84px` button height, `24px` gaps, single-line labels, and the taller panel selected from the user's screenshot. Do not manufacture a card for any missing source record.
- [ ] **Step 4: Implement manual promo switching and source-observed Explore navigation.** Switching must be user-controlled; do not auto-rotate a non-rotating source state.
- [ ] **Step 5: Pass discovery content and geometry tests at `1692 × 979`.**

  Run: `python -m pytest materials/33/clone/tests/test_public_frontend.py materials/33/clone/tests/test_discovery_fidelity.py materials/33/clone/tests/test_data_science_category.py materials/33/clone/tests/test_desktop_visual.py -q`

### Task 6: Complete Search, Filters, and No-Results Recovery

**Files:**
- Modify: `materials/33/clone/search_page.py`
- Modify: `materials/33/clone/app.py`
- Modify: `materials/33/clone/templates/pages/search.html`
- Modify: `materials/33/clone/static/search-page.css`
- Modify: `materials/33/clone/tests/test_search_page_fidelity.py`
- Create: `materials/33/clone/tests/test_search_interactions_fidelity.py`

**Interfaces:**
- Consumes: source search/filter/no-results observations and the existing deterministic local catalog filter function.
- Produces: query-param-driven search with observed filters, exact source result identities for observed queries, visible active-filter state, empty result recovery, and return to `/browse`.

- [ ] **Step 1: Add failing route and interaction tests.** Cover the source-observed course query, every observed filter family, combined filter query preservation, clear/remove behavior, `zzzz-no-match-websitebench`, exact no-results copy, and Browse recovery link.
- [ ] **Step 2: Run focused tests and confirm failures identify behavior/content gaps.**

  Run: `python -m pytest materials/33/clone/tests/test_search_page_fidelity.py materials/33/clone/tests/test_search_interactions_fidelity.py -q`

- [ ] **Step 3: Implement source-backed search markup and same-origin query interactions.** Reuse the existing local catalog semantics only where source behavior is observable; label deterministic offline behavior honestly when the source semantics are unavailable.
- [ ] **Step 4: Preserve the corrected top personalization block and repair only measured geometry.** Do not widen its four controls to fill the panel.
- [ ] **Step 5: Run search tests and a runtime remote-URL scan.**

  Run: `python -m pytest materials/33/clone/tests/test_search_page_fidelity.py materials/33/clone/tests/test_search_interactions_fidelity.py materials/33/clone/tests/test_desktop_visual.py -q`

  Run: `rg -n "https?://" materials/33/clone/templates materials/33/clone/static materials/33/clone/search_page.py`

  Expected: only inert/legal text references explicitly allowed by scope, never runtime presentation dependencies.

### Task 7: Complete Specialization, Course Detail, and Conditional Public Preview

**Files:**
- Modify: `materials/33/clone/specialization_page.py`
- Modify: `materials/33/clone/course_page.py`
- Modify: `materials/33/clone/app.py`
- Modify: `materials/33/clone/templates/pages/specialization.html`
- Modify: `materials/33/clone/templates/pages/course_detail.html`
- Modify: `materials/33/clone/static/specialization-prototype.css`
- Modify: `materials/33/clone/static/course-detail-prototype.css`
- Modify: `materials/33/clone/tests/test_specialization_prototype.py`
- Modify: `materials/33/clone/tests/test_course_detail_prototype.py`
- Create: `materials/33/clone/tests/test_learning_public_fidelity.py`

**Interfaces:**
- Consumes: exact Deep Learning Specialization and reachable course evidence, including complete section inventories and conditional preview classification.
- Produces: source-backed specialization/course routes and either a verified anonymous preview route or an explicit absence assertion with no clone-only preview navigation.

- [ ] **Step 1: Add failing tests for complete visible content.** Assert hero, provider, metadata, skills, course sequence, instructor, syllabus, prerequisites, reviews, pricing/enrollment controls, `Enhance your deep learning skills with neural networks`, and every observed lower section/card identity in source order.
- [ ] **Step 2: Add the preview boundary test.** If evidence says `captured`, assert its exact route/content/navigation; if `not-source-accessible`, assert no preview CTA or synthetic preview route is exposed as source fidelity.
- [ ] **Step 3: Run focused tests.**

  Run: `python -m pytest materials/33/clone/tests/test_specialization_prototype.py materials/33/clone/tests/test_course_detail_prototype.py materials/33/clone/tests/test_learning_public_fidelity.py -q`

- [ ] **Step 4: Implement missing content and geometry with local assets.** Keep course and specialization width caps separate from search/category widths; match source image ratios and complete lower sections before typography micro-tuning.
- [ ] **Step 5: Pass learning-public tests and geometry comparisons.**

  Run: `python -m pytest materials/33/clone/tests/test_specialization_prototype.py materials/33/clone/tests/test_course_detail_prototype.py materials/33/clone/tests/test_learning_public_fidelity.py materials/33/clone/tests/test_fullscreen_geometry_fidelity.py -q`

### Task 8: Complete Anonymous Account, Recovery, Support, and 404 Surfaces

**Files:**
- Create: `materials/33/clone/account_page.py`
- Modify: `materials/33/clone/app.py`
- Create: `materials/33/clone/templates/pages/login.html`
- Create: `materials/33/clone/templates/pages/signup.html`
- Create: `materials/33/clone/templates/pages/recovery.html`
- Create: `materials/33/clone/templates/pages/help.html`
- Create: `materials/33/clone/templates/pages/contact.html`
- Create: `materials/33/clone/templates/pages/not_found.html`
- Create: `materials/33/clone/static/account-access.css`
- Create: `materials/33/clone/tests/test_account_access_fidelity.py`
- Create: `materials/33/clone/tests/test_support_recovery_fidelity.py`

**Interfaces:**
- Consumes: public access/support/404 evidence.
- Produces: English source-backed GET surfaces; client/server required-field feedback; safe return links; no source submission and no private data exposure.

- [ ] **Step 1: Add failing tests for exact visible fields and links.** Cover login email/password/provider choices, signup identity/terms/verification guidance, recovery address/validation/return-to-sign-in, help topics, contact route, branded 404 navigation, and Browse recovery.
- [ ] **Step 2: Add mutation-boundary assertions.** Anonymous GET visits and empty validation must create no backend actor, mail, order, enrollment, or recovery delivery.
- [ ] **Step 3: Run focused tests.**

  Run: `python -m pytest materials/33/clone/tests/test_account_access_fidelity.py materials/33/clone/tests/test_support_recovery_fidelity.py -q`

- [ ] **Step 4: Implement explicit view models/templates and route-safe validation.** Render only observed identity providers and terms links. Keep the generated backend seam intact; do not create a second auth or mail implementation.
- [ ] **Step 5: Pass account-access/support tests.**

  Run: `python -m pytest materials/33/clone/tests/test_account_access_fidelity.py materials/33/clone/tests/test_support_recovery_fidelity.py materials/33/clone/tests/test_public_frontend.py -q`

### Task 9: Implement Observed Empty-Account and Empty-Payment States

**Files:**
- Read first: `docs/websitebench-site-backend-mandate.md`
- Preserve: `materials/33/backend/runtime.json`
- Preserve: `materials/33/backend/model.json`
- Modify: `materials/33/clone/account_page.py`
- Modify: `materials/33/clone/app.py`
- Create: `materials/33/clone/templates/pages/dashboard_empty.html`
- Create: `materials/33/clone/templates/pages/profile_empty.html`
- Create: `materials/33/clone/templates/pages/preferences_empty.html`
- Create: `materials/33/clone/templates/pages/history_empty.html`
- Create: `materials/33/clone/templates/pages/payment_empty.html`
- Create: `materials/33/clone/static/account-empty.css`
- Modify: `materials/33/clone/tests/test_checkout_backend.py`
- Create: `materials/33/clone/tests/test_empty_account_fidelity.py`
- Create: `materials/33/clone/tests/test_empty_payment_fidelity.py`

**Interfaces:**
- Consumes: sanitized authenticated evidence and the existing generated backend/session seam.
- Produces: authenticated local empty-state GET routes and a non-sensitive payment presentation that stops before payment continuation.

- [ ] **Step 1: Read the backend mandate and record the existing runtime identities in the test report.** Do not rerun scaffold unless the mandate and current files prove the required generated runtime is missing or invalid.
- [ ] **Step 2: Add failing empty-state tests.** Use generated test actors, never source credentials. Assert exact empty dashboard/profile/preferences/history copy and controls, no fabricated records, and safe navigation back to relevant collections.
- [ ] **Step 3: Add failing payment-boundary tests.** Assert source-observed plan/amount/empty field labels, visible totals only when they exist before sensitive input, no card fixture values, no automatic attempt/order/enrollment, and no path to a falsely source-backed final confirmation.
- [ ] **Step 4: Run focused tests.**

  Run: `python -m pytest materials/33/clone/tests/test_empty_account_fidelity.py materials/33/clone/tests/test_empty_payment_fidelity.py materials/33/clone/tests/test_checkout_backend.py -q`

- [ ] **Step 5: Implement the observed empty states through the existing session/backend integration.** Remove or hide any current post-enrollment simulation from public navigation for this phase without deleting historical data or backend compatibility behavior.
- [ ] **Step 6: Pass empty-state and backend isolation tests.**

  Run: `python -m pytest materials/33/clone/tests/test_empty_account_fidelity.py materials/33/clone/tests/test_empty_payment_fidelity.py materials/33/clone/tests/test_checkout_backend.py materials/33/clone/tests/test_learning_backend.py -q`

### Task 10: Connect Allowed Interactions and Enforce Deferred Boundaries

**Files:**
- Modify: `materials/33/clone/app.py`
- Modify: `materials/33/clone/ui.py`
- Modify: `materials/33/clone/tests/test_checkout_flow.py`
- Modify: `materials/33/clone/tests/test_learning_backend.py`
- Create: `materials/33/clone/tests/test_current_phase_boundaries.py`

**Interfaces:**
- Consumes: current-phase matrix and generated backend routes.
- Produces: working manual promo, Explore, search/filter, recovery navigation, permission prompts, empty account navigation, and empty payment presentation; deferred actions are absent, disabled with truthful explanation, or retained only as non-advertised compatibility endpoints.

- [ ] **Step 1: Write failing boundary tests for journeys 2, 6–14, 19, and 23.** Assert allowed transitions work and blocked transitions create no enrollment, order, payment attempt, mail, progress, bookmark, quiz, certificate, or review side effect.
- [ ] **Step 2: Run the boundary tests before implementation.**

  Run: `python -m pytest materials/33/clone/tests/test_current_phase_boundaries.py materials/33/clone/tests/test_checkout_flow.py materials/33/clone/tests/test_learning_backend.py -q`

- [ ] **Step 3: Implement only the accessible interaction edges.** Preserve backend compatibility endpoints but remove misleading source-fidelity links to deferred states. Required-field and signed-out failures must identify exactly what is needed before continuation.
- [ ] **Step 4: Re-run boundary/backend tests and inspect the database/mail fixtures for zero unintended writes.**

  Run: `python -m pytest materials/33/clone/tests/test_current_phase_boundaries.py materials/33/clone/tests/test_checkout_flow.py materials/33/clone/tests/test_learning_backend.py -q`

### Task 11: Verify Each Route Family at `1692 × 979`

**Files:**
- Create: `materials/33/clone/tests/test_current_phase_playwright.py`
- Modify: `materials/33/scope/verify.json`
- Create: `materials/33/source-evidence/2026-08-19-accessible-fullscreen/candidate-route-family-report.json`

**Interfaces:**
- Consumes: current-phase overlay, completed local routes, source geometry/content evidence.
- Produces: one browser verification record per current/partial/conditional route state and explicit skip reasons for deferred states.

- [ ] **Step 1: Add one parameterized Playwright test matrix.** For each accessible route/state, assert exact viewport, canonical local path, heading/section order, decisive identities, allowed interaction result, no console error, no failed local asset request, and no remote presentation request.
- [ ] **Step 2: Run the parameterized test by route family and repair failures from structured assertions before visual inspection.**

  Run: `python -m pytest materials/33/clone/tests/test_current_phase_playwright.py -q`

- [ ] **Step 3: Run region visual comparisons for major route families.** Compare header, route main, decisive grids/cards, and footer independently; use the current source bounds, never the clone's own boxes as expected values.
- [ ] **Step 4: Update `scope/verify.json` with current reachable checkpoints, recipes, aliases, and honest anonymous exclusions.** Do not encode acceptance decisions or site-specific scripts.
- [ ] **Step 5: Re-run focused frontend tests after all repairs.**

  Run: `python -m pytest materials/33/clone/tests/test_public_frontend.py materials/33/clone/tests/test_desktop_contract.py materials/33/clone/tests/test_desktop_visual.py materials/33/clone/tests/test_*_fidelity.py materials/33/clone/tests/test_current_phase_playwright.py -q`

### Task 12: Full Verification, Diagnostics, and Manual Handoff

**Files:**
- Modify: `materials/33/scope/current-accessible-fullscreen-phase.json`
- Create: `materials/33/source-evidence/2026-08-19-accessible-fullscreen/final-current-phase-report.json`

**Interfaces:**
- Consumes: all route tests, backend tests, current source/candidate evidence, and the 23-journey overlay.
- Produces: reproducible final-phase report with `implemented`, `conditional-not-exposed`, `deferred`, evidence references, machine findings, and manual-review URLs.

- [ ] **Step 1: Run the complete site-33 test suite.**

  Run: `python -m pytest materials/33/clone/tests -q`

- [ ] **Step 2: Run secret/payment-data and runtime-network closure scans.** Scan source/evidence/templates/static/reports for credentials, cookies, authorization headers, card-like fixtures, remote presentation URLs, and accidentally retained browser state; remove sensitive artifacts immediately if found.
- [ ] **Step 3: Run backend capability/isolation checks required by the mandate.** Record `backend/runtime.json`, unique `site_id`, database/volume identity, enabled mail purposes, payment profile, deployment profile, and every failed machine check without exposing secrets.
- [ ] **Step 4: Run current WebsiteBench diagnostics.**

  Run: `python tools/offline_clone/run.py verify --site materials/33`

  If the repository-local launcher exposes verification only through the installed equivalent, run: `websitebench-offline-clone verify --site materials/33`.

- [ ] **Step 5: Reconcile all 23 journeys.** Every row must name its current result and evidence; 11–13 and inaccessible post-enrollment portions remain deferred; journey 6 has either real preview evidence or no exposed preview page; 2/10/23 stop at empty payment.
- [ ] **Step 6: Start the local site for one consolidated user review at `1692 × 979`.** Provide the loopback URL, route checklist, directly observed limitations, test totals, diagnostic status/findings, and exact deferred list. Do not claim that a clean diagnostic replaces human judgment.

## Execution Checkpoints

1. After Tasks 1–3: evidence matrix complete; pause only if interactive handoff is unavailable or a source A/B authority is unresolved.
2. After Tasks 4–7: all public discovery/search/learning-detail route families implemented and focused tests passing.
3. After Tasks 8–10: account/access/empty-payment boundaries implemented with zero unintended source or local side effects.
4. After Tasks 11–12: current-phase tests and diagnostics complete; local server remains available for the user's single consolidated manual review.

## Completion Criteria

- All source-accessible portions of the 23 journeys are faithfully reachable in English at `1692 × 979`.
- Public route content, card identity, local images, section order, and literal region geometry trace to current or explicitly reused evidence.
- No clone page is invented for an inaccessible source surface.
- Empty payment visibly reflects only the observed pre-sensitive-input choices/totals and cannot masquerade as final payment review or confirmation.
- Credentials, cookies, tokens, payment data, and personal identifiers are absent from repository files, reports, screenshots, and retained browser state.
- No runtime presentation dependency reaches Coursera or another remote origin.
- Generated backend runtime and per-site isolation remain intact.
- All applicable tests and diagnostics have been run and their actual results reported honestly.
- No commit has been created.
