# Coursera Anonymous Journeys Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Do not dispatch subagents and do not commit.

**Goal:** Complete the source-backed signed-out surfaces required by the 23 frozen Coursera journeys, beginning with a faithful Business category page, while leaving authenticated and payment-dependent redesigns deferred.

**Architecture:** Reuse the frozen `public-spine` evidence instead of acquiring another rotating Coursera session. Give `/browse/business` a route-owned immutable inventory and template, retain existing generic subject routes for navigation, and verify every required anonymous route/state through a single local journey matrix.

**Tech Stack:** Python 3, FastAPI, Jinja2, vanilla HTML/CSS, pytest, Playwright through `tools/offline_clone/run.py`.

## Global Constraints

- The new Business-only source capture `source-business-category-current` is authoritative for `/browse/business`.
- Acceptance is English, signed out, at exactly `1692 x 979` CSS pixels.
- Acquire only the bounded GET-only Business route before implementation; do not revisit other source routes.
- Never use `clone-spine-baseline`, `clone-public-sample`, or another clone screenshot as source authority.
- Do not invent, substitute, or reorder titles, providers, labels, links, images, statistics, FAQ copy, or sections.
- Do not submit login, registration, recovery, enrollment, review, quiz, or payment actions.
- Do not redesign dashboard, history, enrolled learning, preferences, or checkout pages.
- Keep all runtime presentation assets local and preserve the generated backend integration.
- Add no animation that is absent from the frozen source.
- Preserve unrelated dirty work. Do not commit, push, merge, deploy, or clean the worktree.

## File Map

- Create `materials/33/clone/business_category.py`: immutable Business-only source inventory and renderer.
- Create `materials/33/clone/templates/pages/business_category.html`: exact Business category structure.
- Modify `materials/33/clone/app.py`: route `/browse/business` through the Business renderer before the generic category renderer.
- Modify `materials/33/clone/static/category-page.css`: Business-scoped source geometry; generic categories remain unchanged.
- Create `materials/33/clone/tests/test_business_category_fidelity.py`: identity, structure, asset, geometry, and interaction contracts.
- Create `materials/33/clone/tests/test_anonymous_journey_matrix.py`: signed-out coverage of the relevant frozen journeys.
- Create `materials/33/scope/source-business-category-current.json`: read-only source scenario for the current Business page.
- Create `materials/33/source-evidence/2026-08-19-accessible-fullscreen/source-business-category-current.json` and screenshot directory: current source authority.
- Create `materials/33/scope/clone-business-category-current.json`: local-only candidate capture scenario on the first available loopback port.
- Create `materials/33/source-evidence/2026-08-19-accessible-fullscreen/clone-business-category-current.json` and screenshot directory: sanitized local candidate evidence.

---

### Task 0: Recapture the current Business source page

**Files:**
- Create: `materials/33/scope/source-business-category-current.json`
- Create: `materials/33/source-evidence/2026-08-19-accessible-fullscreen/source-business-category-current.json`
- Create: `materials/33/source-evidence/2026-08-19-accessible-fullscreen/source-business-category-current/`

**Interfaces:**
- Consumes: anonymous `https://www.coursera.org/browse/business` at `1692 x 979`.
- Produces: one sanitized GET-only report with exact visible Business copy, card destinations, counts, and a settled full-page screenshot.

- [x] **Step 1: Define the bounded source scenario.**

  Use one `goto`, bounded waits/PageDown actions for lazy presentation, and a final full-page snapshot. Record `url_path`, `title`, `main` text, exact card hrefs, heading/status counts, main link/image counts, and no form input or click.

- [x] **Step 2: Run the source acquisition without mutation opt-in.**

  Run:

  ```bash
  LD_LIBRARY_PATH=/tmp/coursera-browser-libs.ysKdlZ/root/usr/lib/x86_64-linux-gnu \
  PLAYWRIGHT_NODEJS_PATH=/usr/bin/node \
  python tools/offline_clone/run.py tools explore \
    --spec materials/33/scope/source-business-category-current.json \
    --base-url https://www.coursera.org \
    --environment source \
    --out materials/33/source-evidence/2026-08-19-accessible-fullscreen/source-business-category-current.json \
    --artifacts-dir materials/33/source-evidence/2026-08-19-accessible-fullscreen/source-business-category-current
  ```

  Do not pass `--allow-source-mutations`. Background POSTs remain blocked.

- [x] **Step 3: Validate source authority before implementation.**

  Confirmed: `environment` is `source`, `base_origin` is `https://www.coursera.org`, the route is `/browse/business`, the viewport is `1692 x 979`, all four card destinations resolve, and the `1692 x 3474` final screenshot is non-empty. The current settled source shows an Explore roles no-results state and a blue Join for free band; these replace the older loading-card state.

---

### Task 1: Lock the frozen Business identity in failing tests

**Files:**
- Create: `materials/33/clone/tests/test_business_category_fidelity.py`
- Read only: `materials/33/source-evidence/2026-08-19-accessible-fullscreen/source-business-category-current.json`
- Read only: `materials/33/source-evidence/2026-08-19-accessible-fullscreen/source-business-category-current/coursera-business-current-capture-settled.png`

**Interfaces:**
- Consumes: the new Business-only source report and its full-page screenshot.
- Produces: exact source contracts for `load_business_category()` and `render_business_category_body()`.

- [x] **Step 1: Add the exact inventory contract.**

  The test imports `load_business_category` and requires this immutable identity:

  ```python
  expected_cards = (
      (0, "Google Project Management", "Google", ("Free Trial", "AI skills"), True, "/professional-certificates/google-project-management", "/static/categories/business/card-1.png"),
      (1, "Foundations of Project Management", "Google", ("Free Trial",), False, "/learn/project-management-foundations", "/static/categories/business/card-2.png"),
      (2, "AI For Everyone", "DeepLearning.AI", ("Preview",), False, "/learn/ai-for-everyone", "/static/categories/business/card-3.png"),
      (3, "Key Technologies for Business", "IBM", ("Free Trial",), False, "/specializations/key-technologies-for-business", "/static/categories/business/card-4.png"),
  )
  assert page.title == "Business"
  assert page.stats == (("1062", "credentials"), ("14", "online degrees"), ("5998", "courses"))
  assert tuple((card.position, card.title, card.provider, card.badges, card.builds_toward_degree, card.href, card.image) for card in page.cards) == expected_cards
  ```

- [x] **Step 2: Add rendered structure contracts.**

  Assert four ordered `data-business-position` cards; exact ratings/reviews and metadata; the four badge sets; the degree line only on position 0; `Show 8 more`; the current `No results found for "proficiencyLevel filterName"` role state and `Change your filters.` guidance; the three captured Business questions; the More questions panel; the Lightcast footnote; the blue `Join for free and get personalized recommendations, updates and offers.` band; and the shared source footer.

- [x] **Step 3: Add local asset closure assertions.**

  Resolve every `/static/categories/business/card-N.png` through `materials/33/clone/static`, assert each file is non-empty, and reject `http://` or `https://` presentation references in the rendered Business body.

- [x] **Step 4: Run the tests and confirm the old generic renderer fails for the intended reason.**

  Run:

  ```bash
  python -m pytest materials/33/clone/tests/test_business_category_fidelity.py -q
  ```

  Expected: FAIL because `business_category.py`, the position attributes, badges, and degree line do not yet exist. Fix import errors only enough for pytest to collect; do not weaken the identity assertions.

---

### Task 2: Implement the route-owned Business page

**Files:**
- Create: `materials/33/clone/business_category.py`
- Create: `materials/33/clone/templates/pages/business_category.html`
- Modify: `materials/33/clone/app.py:741-779`
- Modify: `materials/33/clone/static/category-page.css`
- Test: `materials/33/clone/tests/test_business_category_fidelity.py`

**Interfaces:**
- `BusinessCard(position: int, title: str, provider: str, rating: str, reviews: str, metadata: str, badges: tuple[str, ...], builds_toward_degree: bool, href: str, image: str)`
- `BusinessCategory(title: str, description: str, stats: tuple[tuple[str, str], ...], cards: tuple[BusinessCard, ...], questions: tuple[str, ...])`
- `load_business_category() -> BusinessCategory`
- `render_business_category_body() -> str`

- [x] **Step 1: Add immutable source records.**

  Define frozen dataclasses and the four exact cards. Reject duplicate positions, non-contiguous positions, remote image URLs, missing identity fields, and image paths outside `/static/categories/business/`:

  ```python
  @dataclass(frozen=True)
  class BusinessCard:
      position: int
      title: str
      provider: str
      rating: str
      reviews: str
      metadata: str
      badges: tuple[str, ...]
      builds_toward_degree: bool
      href: str
      image: str
  ```

- [x] **Step 2: Render the captured Business structure.**

  Build a dedicated template with breadcrumb, title/description/stats, `Most popular`, level pills, four cards, badges over each image, provider row, optional `Build toward a degree`, rating/metadata, Show 8 more, the captured Explore roles no-results state, FAQ, More questions, footnote, and blue anonymous Join for free band. Use semantic anchors and `details/summary`; do not add invented role identities or loading cards from the older source run.

- [x] **Step 3: Route only Business through the new renderer.**

  In `browse_category`, add the Business branch before the generic renderer:

  ```python
  if category == "business":
      return _page(
          request,
          "Business Online Courses",
          render_business_category_body(),
          body_class="source-category-page source-business-category-page",
          document_title="Business Online Courses | Coursera",
          language="en",
          footer_variant="source-browse",
      )
  ```

  Keep Data Science and the other subject routes unchanged.

- [x] **Step 4: Add Business-scoped styling.**

  Under `.source-business-category-page`, retain the `1344px` shell, create a four-column grid with equal media rectangles, place badges over images, and match the captured white cards, pale no-results role band, FAQ two-column layout, blue signup band, and full-width light footer. Do not use viewport-scaled fonts or modify generic category selectors unless required by shared header/footer fidelity.

- [x] **Step 5: Run the identity tests to green.**

  Run:

  ```bash
  python -m pytest \
    materials/33/clone/tests/test_business_category_fidelity.py \
    materials/33/clone/tests/test_public_frontend.py \
    materials/33/clone/tests/test_discovery_fidelity.py -q
  ```

  Expected: all tests pass and every non-Business subject retains its existing route behavior.

---

### Task 3: Match Business fullscreen geometry and capture the candidate

**Files:**
- Modify: `materials/33/clone/tests/test_business_category_fidelity.py`
- Modify: `materials/33/clone/static/category-page.css`
- Create: `materials/33/scope/clone-business-category-current.json`
- Create: `materials/33/source-evidence/2026-08-19-accessible-fullscreen/clone-business-category-current.json`
- Create: `materials/33/source-evidence/2026-08-19-accessible-fullscreen/clone-business-category-current/`

**Interfaces:**
- Consumes: the rendered Business route and frozen source PNG.
- Produces: a same-viewport local report with full-page screenshot, rectangles, loaded-image state, and network/console observations.

- [x] **Step 1: Add browser geometry assertions.**

  At `1692 x 979`, assert the shell is `1344 +/- 4px` wide at `x=174 +/- 4px`; four cards occupy one row; card/image heights differ by at most 1px within their groups; the first card starts at the shell left edge; the fourth card ends at the shell right edge; Explore roles, FAQ, footnote, signup band, and footer remain in source order without overlap; and all four card images have positive natural dimensions. Treat the fixed header's position inside Playwright's stitched full-page PNG as a capture artifact, not as a route section to reproduce.

- [x] **Step 2: Run the geometry test and record the first evidence-backed mismatch.**

  Run:

  ```bash
  LD_LIBRARY_PATH=/tmp/coursera-browser-libs.ysKdlZ/root/usr/lib/x86_64-linux-gnu \
  python -m pytest materials/33/clone/tests/test_business_category_fidelity.py -q
  ```

  Expected: FAIL on a literal rectangle if Task 2 styling still differs. Change one owning CSS rule at a time; do not compensate by loosening identity tests.

- [x] **Step 3: Repair only measured geometry.**

  Adjust Business-scoped shell spacing, grid tracks, card padding, image height, no-results role band height, FAQ tracks, signup band, and section margins until the browser assertions pass. Preserve text wrapping and do not copy the source screenshot's blurred app-store evidence or stitched sticky-header position into unrelated sections.

- [x] **Step 4: Add the local capture scenario.**

  Define a clone-only GET scenario for `/browse/business` with route, title, `main` text, four card counts, image counts/load state, key section identities, console errors, failed requests, and one full-page screenshot. Its only allowed origin is the current clone's loopback origin (`http://127.0.0.1:8045` because 8044 already hosts the preserved earlier process).

- [x] **Step 5: Capture and inspect the candidate.**

  Run:

  ```bash
  LD_LIBRARY_PATH=/tmp/coursera-browser-libs.ysKdlZ/root/usr/lib/x86_64-linux-gnu \
  PLAYWRIGHT_NODEJS_PATH=/usr/bin/node \
  python tools/offline_clone/run.py tools explore \
    --spec materials/33/scope/clone-business-category-current.json \
    --base-url http://127.0.0.1:8045 \
    --environment clone \
    --out materials/33/source-evidence/2026-08-19-accessible-fullscreen/clone-business-category-current.json \
    --artifacts-dir materials/33/source-evidence/2026-08-19-accessible-fullscreen/clone-business-category-current
  ```

  Expected: every step passes, every request remains loopback-local, four images load, and the full-page result matches the source section order without overlap.

---

### Task 4: Reconcile the signed-out portions of all 23 journeys

**Files:**
- Create: `materials/33/clone/tests/test_anonymous_journey_matrix.py`
- Modify only on a failing evidence-backed contract: route-owned public templates or styles already listed in `docs/superpowers/specs/2026-08-19-coursera-anonymous-journeys-design.md`
- Do not modify: authenticated, enrolled-learning, history, preference, or checkout templates.

**Interfaces:**
- Consumes: `materials/33/scope/journeys.json`, `materials/33/scope/current-accessible-fullscreen-phase.json`, and existing public route renderers.
- Produces: one explicit anonymous-route/state matrix with no source or local mutation.

- [x] **Step 1: Add a route matrix for anonymous success and recovery states.**

  Cover these exact paths and landmarks:

  ```python
  PUBLIC_STATES = (
      ("/", "New and popular"),
      ("/browse", "Explore Categories"),
      ("/browse/business", "Business"),
      ("/search?q=Deep+Learning", "All Results"),
      ("/search?q=zzzz-no-match-websitebench", "No results for zzzz-no-match-websitebench"),
      ("/specializations/deep-learning", "Deep Learning Specialization"),
      ("/learn/neural-networks-deep-learning", "Neural Networks and Deep Learning"),
      ("/login", "Log in or create account"),
      ("/signup", "Log in or create an account"),
      ("/account-recovery", "Reset your Coursera password"),
      ("/help", "Troubleshooting login and account issues"),
      ("/about/contact", "Contact Us"),
  )
  ```

  Assert canonical local paths, English headings, primary recovery links, and no remote presentation URL.

- [x] **Step 2: Add boundary-state assertions.**

  Verify the homepage Log In control opens a same-document dialog; login/signup/recovery expose fields and terms/return guidance without submission; impossible search returns to Browse; unknown route returns branded 404; course enrollment while signed out exposes the observed permission prompt without creating an enrollment; and no anonymous course page advertises a preview route absent from source evidence.

- [x] **Step 3: Assert authenticated journey honesty.**

  Read `current-accessible-fullscreen-phase.json` and assert dashboard, lesson, quiz, progress, preference, history, and payment-review redesigns remain deferred/current-partial. The matrix must not log in, seed a session, submit a form, or relabel those states as current source fidelity.

- [x] **Step 4: Run the anonymous matrix and existing public contracts.**

  Run:

  ```bash
  LD_LIBRARY_PATH=/tmp/coursera-browser-libs.ysKdlZ/root/usr/lib/x86_64-linux-gnu \
  python -m pytest \
    materials/33/clone/tests/test_anonymous_journey_matrix.py \
    materials/33/clone/tests/test_current_phase_matrix.py \
    materials/33/clone/tests/test_public_frontend.py \
    materials/33/clone/tests/test_search_interactions_fidelity.py \
    materials/33/clone/tests/test_learning_public_fidelity.py -q
  ```

  Expected: all signed-out states pass; no authenticated or payment-dependent journey is falsely promoted to complete.

---

### Task 5: Full verification and manual handoff

**Files:**
- Modify only files from Tasks 1-4 when verification demonstrates a scoped regression.
- Do not commit.

**Interfaces:**
- Consumes: the complete site-33 clone and current local service.
- Produces: fresh test/diagnostic evidence and a loopback URL for human review.

- [x] **Step 1: Run the complete clone test suite.**

  Run:

  ```bash
  LD_LIBRARY_PATH=/tmp/coursera-browser-libs.ysKdlZ/root/usr/lib/x86_64-linux-gnu \
  python -m pytest materials/33/clone/tests -q
  ```

  Expected: all tests pass. Treat warnings separately from failures.

- [x] **Step 2: Run repository diagnostics and closure checks.**

  Run:

  ```bash
  LD_LIBRARY_PATH=/tmp/coursera-browser-libs.ysKdlZ/root/usr/lib/x86_64-linux-gnu \
  PLAYWRIGHT_NODEJS_PATH=/usr/bin/node \
  python tools/offline_clone/run.py verify --site materials/33
  ```

  Report the actual static/live status. Confirm the Business candidate report has zero failed/blocked remote requests and that no credential, card, cookie, authorization, storage-state, or browser-profile artifact was added.

- [x] **Step 3: Keep the manual-review service available.**

  Ensure `http://127.0.0.1:8045/` and `http://127.0.0.1:8045/browse/business` return HTTP 200. Port 8044 remains untouched because it was already occupied by the preserved earlier process.

- [x] **Step 4: Hand off without integration actions.**

  Report the Business screenshot path, public test totals, full-suite totals, diagnostic findings, and the exact authenticated/payment states still deferred. Do not commit, push, merge, deploy, or imply that machine diagnostics replace human acceptance.
