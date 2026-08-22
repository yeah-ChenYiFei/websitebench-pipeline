# Coursera Learner Experience Expansion Design

**Date:** 2026-08-20  
**Site:** `materials/33`  
**Language:** English  
**Acceptance viewport:** `1692 × 979`

## 1. Purpose and authority

The product goal is no longer limited to the original 23 WebsiteBench journeys. The long-term goal is to reproduce nearly all important Coursera functionality available to an ordinary learner, with the most important learner workflows receiving priority.

The implementation remains an offline clone. It must not contact Coursera for mutations, perform a real enrollment, send real mail, use a real identity provider, accept real payment credentials, or create a real charge.

This design expands the active product scope without rewriting immutable historical evidence, trajectory records, hashes, or compatibility data. The original 23 journeys remain a regression baseline, not the upper limit of the product.

## 2. Agreed implementation strategy

Continue incrementally from the existing `materials/33` application.

- Do not rebuild the site from scratch.
- Do not create a second Coursera application or backend.
- Preserve already reviewed pages and working backend behavior unless current source evidence or a failing contract requires a correction.
- Extend the existing FastAPI, SQLite, `websitebench.site_backend`, `backend.learning_db`, and checkout integration seams.
- Avoid broad refactors. Extract new rendering modules or templates only when a touched unit is too large to change safely.
- Develop the frontend and backend behavior of each product slice together.
- Keep changes uncommitted until the user explicitly authorizes a commit.

The rejected alternatives are a frontend-wide refactor before feature work and a full rewrite. Both would unnecessarily destabilize already accepted work.

## 3. Product boundaries

### 3.1 Included ordinary-learner product domains

#### Discovery and browsing

- Home and all principal learner navigation.
- Explore menus, subjects, categories, and collections.
- Search, suggestions, filters, sorting, pagination, no-results handling, and recovery.
- Trending, popular, new-release, skill, career-role, and personalized recommendation collections when present in current source evidence.
- Recently viewed products and saved catalog items.
- Course, Specialization, Professional Certificate, Guided Project, and Degree discovery and detail surfaces.
- Provider, instructor, syllabus, prerequisites, reviews, duration, level, schedule, language, pricing, and enrollment-option information exposed before enrollment.
- Public previews, samples, and publicly accessible course materials.
- Source-observed, non-mutating actions such as sharing or copying a product link.

#### Identity and account lifecycle

- Registration, local verification code, and Local Inbox.
- Login, logout, session continuity, and safe same-page identity dialogs where observed.
- Presentational Google, Apple, and Facebook boundaries without contacting those providers.
- Password recovery and local password reset.
- Onboarding, learning goals, interests, and profile setup.
- Profile display and editing, including a safe local profile image flow where supported.
- Language, timezone, appearance, accessibility, privacy, and cookie preferences.
- Password change, two-factor-authentication presentation, connected devices, and linked-account presentation.
- Communication preferences, learner data export, and local account deletion semantics.

#### Learner account surfaces before enrollment

- Empty My Learning and its source-observed navigation.
- Purchases and Payment History, including complete recommendation sections.
- Updates and notifications.
- Saved products, recently viewed products, recommendations, and learning/career goals where source-observed.
- Coursera Plus, subscriptions, and order entry points visible before enrollment.
- Empty, permission, validation, failure, and recovery states for all included account surfaces.

#### Enrollment and commerce

- Free, audit, trial, paid, and financial-aid choices when current source evidence exposes them.
- Authentication transitions that preserve the invoking public page.
- Deep Learning Specialization as the representative end-to-end product.
- Server-owned product, provider, plan, trial, currency, price, tax, total, renewal, and terms facts.
- Checkout/payment presentation and empty-field validation.
- A future local-sandbox implementation for approval, decline, retry, orders, subscriptions, cancellation, and refund-like local outcomes.

#### Support and recovery

- Public help, contact, learner guidance, and relevant frequently asked questions.
- Guidance for login, enrollment, and payment failures.
- Branded not-found, no-results, permission, empty, loading, and service-error recovery.
- Safe navigation back to Home, Browse, the relevant account collection, or the invoking product.

### 3.2 Long-term learner scope that is deferred now

The following learner capabilities remain part of the long-term goal, but must not be newly implemented or visually redesigned until corresponding enrolled-source evidence is available:

- Populated enrolled My Learning and study plans.
- Video, text, transcripts, captions, downloads, and course-unit navigation.
- Quizzes, assignments, exercises, labs, peer review, and feedback.
- Notes, highlights, lesson bookmarks, discussions, deadlines, calendar, and reminders.
- Progress, grades, completion, certificates, certificate sharing, ratings, and reviews.
- Course withdrawal, enrolled-course cancellation, and populated enrollment history.

Existing clone-local code for these states may remain, but this phase must not claim new source fidelity for it or spend effort expanding it. When the user later supplies authenticated enrolled evidence, this product domain receives a separate evidence-backed design and plan.

### 3.3 Explicit exclusions

- Enterprise, university, government, instructor, partner, and internal Coursera administration portals.
- Real Google, Apple, Facebook, or Coursera authentication.
- Real email delivery.
- Real payment processing, live payment keys, card numbers, CVV, expiry dates, bank credentials, or wallet credentials.
- Copying the complete Coursera course catalog or every course's learning materials.
- Invented pages, cards, identities, content, or interactions without corresponding source evidence.

### 3.4 Core-function priority

The following current-phase capabilities are core and block a completion claim if any is missing or non-functional:

1. Shared navigation and same-page authentication entry.
2. Registration, login, logout, recovery, and authenticated session continuity.
3. Browse, category discovery, search, filtering, sorting, no-results handling, and safe recovery.
4. Accurate product cards and representative Course, Specialization, Professional Certificate, Guided Project, and Degree detail surfaces when present in the current learner navigation.
5. Deep Learning product detail, enrollment/plan entry, authenticated continuation, and payment-page stopping boundary.
6. Empty My Learning plus the complete authenticated-unenrolled account navigation and account settings.
7. Purchases, Updates, saved/recently-viewed state, Help, Contact, and not-found recovery.
8. Required-field, permission, ownership, and service-failure handling for every included core flow.

Peripheral source-observed actions are still tracked and implemented where practical, but completing many peripheral actions cannot compensate for an incomplete core capability.

## 4. Current delivery boundary

The current phase covers all ordinary-learner public functionality and all authenticated functionality available before enrollment.

The Deep Learning flow ends at the payment page:

1. Open the public product.
2. Choose an available plan or enrollment entry.
3. Authenticate locally if required without losing the invoking page.
4. Reach the payment page.
5. Show accurate server-owned product, plan, trial, currency, price, tax, total, renewal, and terms.
6. Keep payment-looking fields empty.
7. Demonstrate required-field validation safely.
8. Do not submit payment, create an order, activate a subscription, complete enrollment, or create a post-enrollment learning record.

The already configured `local-sandbox` remains the approved future payment mechanism, but its final submission and downstream enrollment behavior are outside this current phase.

## 5. Content scale

Functionality is generalized; course content is representative.

- Deep Learning Specialization is the complete representative product for the current public-to-payment flow.
- Other catalog products reuse generalized discovery, detail, saving, recent-view, and enrollment-entry behavior.
- Every catalog item does not require a complete set of proprietary learning materials.
- Card identity, title, provider, route, and imagery must still be grounded in captured source evidence.

## 6. Source evidence acquisition

Current English Coursera is the presentation authority. The existing homepage WACZ and retained evidence remain useful historical evidence, but do not override a newer direct capture for changing content.

### 6.1 Exploration method

- Use the repository WebsiteBench/Playwright evidence path.
- Capture public and authenticated-but-unenrolled learner surfaces.
- The user personally enters credentials and handles CAPTCHA or other identity challenges.
- The user personally navigates through any sensitive source transition required to reach the empty payment page.
- Stop with payment fields empty.
- Never retain browser profiles, storage state, cookies, passwords, tokens, payment information, or personal identifiers.
- Source requests remain read-only except for user-controlled navigation already authorized by the source-evidence policy.

### 6.2 Complete-page acquisition

For every page:

- Use the fixed `1692 × 979` viewport.
- Wait for network and document stability using condition-based settling.
- Scroll through the complete page.
- Trigger source-observed lazy loading without causing a mutation.
- Verify the final document height is stable.
- Record all major sections, headings, controls, links, card identities, and image health.
- Exercise safe menus, tabs, accordions, filters, dialogs, and manual switches.
- Capture only canonical screenshots and materially different interaction states.

### 6.3 Compact retained evidence

Retain one compact evidence record per route/state containing:

- requested and canonical path;
- title and principal headings;
- stable visible copy and control labels;
- important links and actions;
- key geometry and computed presentation facts;
- card/product identities in observed order;
- localizable asset references;
- animation and interaction observations;
- necessary screenshot references;
- evidence classification and any inaccessible continuation.

Do not repeatedly recapture a page with sufficient current evidence. Recapture only when evidence is incomplete, the current site materially changed, or clone validation identifies a concrete mismatch.

## 7. Coverage inventory

Before feature implementation, create a configuration-driven inventory that maps:

`source route/state → retained evidence → local route/state → renderer → backend capability → automated test → current status`

The inventory must include discovered functionality beyond the original 23 journeys. Valid statuses are:

- `direct-source-complete`
- `local-functional-complete`
- `implemented-browser-unverified`
- `evidence-incomplete`
- `deferred-enrolled-source-required`
- `out-of-scope`

No inaccessible or inferred page may be labeled as direct-source complete.

## 8. Application architecture

### 8.1 Presentation

- Continue with server-rendered FastAPI/Jinja or the existing bounded renderer modules.
- Preserve shared public, authenticated, and checkout chrome.
- Reuse source-grounded components for navigation, cards, filters, dialogs, forms, tabs, empty states, and errors.
- Use local fonts and local presentation assets only.
- Use JavaScript only for source-observed interactions.
- Do not add autoplay where the source does not autoplay.
- Do not add animation where the source has none; source animation may be reproduced when important and economical.
- Respect reduced-motion preferences.

### 8.2 State and backend

- `backend/runtime.json` remains the only account, session, mail, payment, database, and deployment contract.
- `websitebench.site_backend` remains the account/session/mail/payment integration seam.
- `backend.learning_db` and the site-specific checkout layer remain the owners of learner and checkout state.
- Do not add a second database, custom authentication store, custom mail system, or live-payment integration.
- Server state is authoritative for identity, pricing, totals, ownership, and mutation results.
- Use server validation and POST/Redirect/GET for mutations.
- Persist included local state through refresh and service restart.
- Enforce owner isolation and safe signed-out behavior.

### 8.3 External-effect safety

- Registration and password recovery use the Local Inbox.
- Identity-provider entries never contact external providers.
- The current payment page accepts no payment credentials and creates no order.
- Future payments use only configured opaque `local-sandbox` scenarios.
- Never log or persist passwords, verification codes, session tokens, source cookies, or payment values.

## 9. Implementation order

1. Run the current test and diagnostic baseline.
2. Build the expanded ordinary-learner source route/state inventory.
3. Correct shared navigation, login dialog, authenticated account menu, and footer once.
4. Complete public discovery: Home, Browse, categories, search, filters, product types, recommendations, saving, and public details.
5. Complete identity and authenticated-unenrolled account surfaces.
6. Complete Deep Learning plan selection and the payment page stopping boundary.
7. Replay every included public and authenticated-unenrolled interaction.
8. Report deferred enrolled-only functionality separately.

Each product slice includes source evidence, a failing test, implementation, backend wiring, focused verification, and regression checks before moving to the next slice.

## 10. Error and recovery behavior

Every included mutation or navigation must define:

- anonymous behavior;
- authenticated-unenrolled behavior;
- required-field validation;
- invalid or stale identifier handling;
- empty data behavior;
- safe ownership failure;
- retry/recovery navigation;
- refresh behavior;
- local service failure presentation where applicable.

Errors must not expose internal paths, stack traces, secrets, private account data, or whether another account exists.

## 11. Completion and verification

A page or feature is complete only when all applicable conditions are satisfied:

- Current English source evidence or an explicit local-functional contract exists.
- Route, headings, copy, card identity/order, controls, and interactions match the evidence.
- At the acceptance viewport, key regions achieve the agreed approximately 90% or better visual similarity.
- Full scrolling produces every expected lazy-loaded section.
- Images load successfully and the page has no unintended remote dependencies.
- Required backend behavior is real, owner-scoped, persistent, and safe.
- Anonymous, authenticated, empty, validation, error, and recovery states are covered.
- Current-scope buttons perform their function rather than acting as decoration.
- Automated checks exercise real behavior, not implementation text or mocks.

Verification has four layers:

1. Route/content tests for paths, landmarks, links, forms, and visible states.
2. Backend semantic tests for account isolation, sessions, validation, persistence, idempotency, and ownership.
3. Playwright tests for real clicks, dialogs, filters, scrolling, lazy loading, and navigation.
4. Visual checks for key regions, shell width, card geometry, image height, and page completeness at `1692 × 979`.

Run focused tests after each slice and the full suite at major phase boundaries. WebsiteBench static/live reports and comparison tools remain diagnostic aids; environment failures must be reported separately from product failures.

Completion reporting must distinguish:

- complete and verified;
- implemented but browser-unverified;
- missing source evidence;
- deferred until enrolled evidence exists;
- out of scope.

## 12. Environment

- Local preview remains on `127.0.0.1:8045` during review.
- Playwright Chromium system dependencies were installed and verified on 2026-08-20.
- Chromium successfully loaded the local homepage at `1692 × 979` with zero broken images, failed requests, or console errors during the environment smoke check.
- The prior Harbor `Errno 95` may still make WebsiteBench Live diagnostics incomplete; this is reported as an environment limitation rather than a page failure.

## 13. Current-phase acceptance statement

The current phase is accepted only when every core capability in section 3.4 and nearly all other ordinary-learner public and authenticated-unenrolled functions discovered from the current English source are present and functional in the existing offline clone. The expanded coverage inventory must contain no unresolved core entry. The Deep Learning flow must reach an accurate, safe payment page with empty-field validation but no submission, order, subscription, enrollment, or post-enrollment state transition.
