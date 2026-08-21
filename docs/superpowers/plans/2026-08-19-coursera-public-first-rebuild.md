# Coursera Public-First Rebuild Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Do not dispatch subagents and do not commit.

**Goal:** Rebuild the Coursera public experience from one frozen current-live anonymous capture, with exact homepage card identities and the already-scoped public discovery journeys, while deferring authenticated and payment-dependent states.

**Architecture:** Acquire one sanitized Playwright evidence set at `1692 x 979`, convert it into an explicit typed homepage inventory, and render each source section with its own template data instead of a shared inferred card list. Keep existing route modules and generated backend seams intact; this plan changes only public source-backed presentation and its evidence/tests.

**Tech Stack:** Python 3, FastAPI, Jinja2, vanilla HTML/CSS/JavaScript, pytest, Playwright through `tools/offline_clone/run.py`.

## Global Constraints

- Homepage authority is the current live Coursera capture, not the August WACZ.
- Capture language is English, state is logged out, and the acceptance viewport is exactly `1692 x 979` CSS pixels.
- Source acquisition is read-only GET-only; do not use `--allow-source-mutations`, create accounts, enroll, submit forms, enter payment data, or persist browser storage.
- Never persist credentials, cookies, authorization headers, personal identifiers, payment data, raw sensitive network bodies, or browser profiles.
- Do not invent a homepage card, title, provider, badge, destination, image, section, ordering, or copy. An unresolved source record remains unresolved.
- Use only local assets in the clone; no runtime request to Coursera or another remote origin.
- Do not add animation unless the current source visibly has it. Preserve explicit manual controls where the source has them.
- Use the real fullscreen geometry: at `1692 x 979`, the principal source shell is approximately `1344px` wide with its measured left edge near `174px`.
- Do not change `materials/33/backend/runtime.json` or the generated `websitebench.site_backend` integration seam.
- Login, registration, recovery, enrolled learning, seeded history, and checkout/payment are later plans; do not expand this public-first plan into those states.
- Do not commit, push, merge, or clean unrelated dirty work.

## File Map

- Create `materials/33/scope/source-home-current-loaded.json`: declarative read-only scenario for a fully loaded current homepage.
- Create `materials/33/source-evidence/2026-08-19-accessible-fullscreen/source-home-current-loaded.json` and its asset/screenshot directory: sanitized source observations and provenance.
- Create `materials/33/clone/home_inventory.py`: typed source-backed section/card records consumed only by the homepage.
- Modify `materials/33/clone/home_page.py`: load and validate the frozen inventory and pass section-specific view data to Jinja.
- Modify `materials/33/clone/templates/pages/home.html`: render the captured source order and section-specific structures.
- Modify `materials/33/clone/static/home-prototype.css`: implement measured source geometry and section-specific card dimensions.
- Modify `materials/33/clone/tests/test_discovery_fidelity.py`: ordered section and decisive identity contracts.
- Modify `materials/33/clone/tests/test_fullscreen_geometry_fidelity.py`: shell and purpose-panel geometry contracts.
- Modify `materials/33/clone/tests/test_public_frontend.py`: public route and asset/network closure contracts.
- Modify `materials/33/clone/tests/test_source_grounding.py`: ensure homepage records point only to current-home evidence.

### Task 1: Freeze the current anonymous homepage evidence

**Files:**
- Create: `materials/33/scope/source-home-current-loaded.json`
- Create: `materials/33/source-evidence/2026-08-19-accessible-fullscreen/source-home-current-loaded.json`
- Create: `materials/33/source-evidence/2026-08-19-accessible-fullscreen/source-home-current-loaded/`

**Interfaces:**
- Consumes: the configured Coursera public origin and the existing source-evidence tool contract.
- Produces: one sanitized report with the final screenshot, ordered section headings, card links, image URLs/mappings, visible labels, and DOM rectangles.

- [ ] **Step 1: Define the bounded source scenario.**

  Start from the existing public-home scenario and add only GET navigation, bounded PageDown scrolling, and waits for lazy content. The scenario must record the viewport, URL, heading sequence, all visible anchor destinations, image `src`/`alt`, and rectangles for each homepage section/card. Do not add login, signup, enrollment, or form submission steps.

- [ ] **Step 2: Run the source acquisition read-only.**

  Run:

  ```bash
  PLAYWRIGHT_NODEJS_PATH=/usr/bin/node \
    python tools/offline_clone/run.py tools explore \
    --site materials/33 \
    --scenario materials/33/scope/source-home-current-loaded.json
  ```

  Expected result: a sanitized evidence report and local screenshot/assets with no source mutation and no persisted browser state. If a collection remains loading after the bounded waits, record it as unresolved in the report.

- [ ] **Step 3: Review the evidence inventory before coding.**

  Confirm that each section has one stable source identifier and that every captured card has `section_id`, zero-based `position`, exact `title`, exact `provider`, visible badges/metadata, source `href`, local asset path, source image dimensions, and viewport rectangle. Remove any record whose only provenance is a different route or the old WACZ.

- [ ] **Step 4: Run evidence schema checks.**

  Run:

  ```bash
  python -m pytest materials/33/clone/tests/test_source_grounding.py -q
  ```

  Expected result: the new evidence file is readable, has no sensitive fields, and reports unresolved records explicitly rather than silently filling them.

### Task 2: Add an explicit homepage inventory model and failing identity tests

**Files:**
- Create: `materials/33/clone/home_inventory.py`
- Modify: `materials/33/clone/tests/test_discovery_fidelity.py`
- Modify: `materials/33/clone/tests/test_source_grounding.py`

**Interfaces:**
- `HomeCard(section_id: str, position: int, title: str, provider: str, href: str, image: str, badges: tuple[str, ...], metadata: tuple[str, ...])`.
- `HomeSection(section_id: str, heading: str, kind: str, cards: tuple[HomeCard, ...], source_order: int)`.
- `load_home_inventory() -> tuple[HomeSection, ...]` returns sections in source order and raises `ValueError` when a card has missing identity, duplicate position, remote asset, or non-home evidence provenance.

- [ ] **Step 1: Write identity tests against the frozen evidence.**

  Add tests that assert the exact ordered section IDs from the captured report, each section's card count, and decisive cards as `(section_id, position, title, provider, href, image)`. Assert that no homepage card uses `/static/browse/`, `/static/data-science/`, `/static/categories/`, or another route-owned asset unless the current-home evidence explicitly maps that exact asset.

- [ ] **Step 2: Run the focused tests and verify the old model fails.**

  Run:

  ```bash
  python -m pytest \
    materials/33/clone/tests/test_discovery_fidelity.py \
    materials/33/clone/tests/test_source_grounding.py -q
  ```

  Expected result: FAIL on at least one old inferred title/provider/order/image assertion. This confirms the tests protect content identity rather than only visual plausibility.

- [ ] **Step 3: Implement the inventory loader.**

  Define immutable dataclasses, load only the sanitized current-home evidence, normalize every local asset to a `/static/...` URL, preserve source order, and reject unresolved cards instead of substituting records. Keep route links exactly as observed; do not synthesize a search URL from a title.

- [ ] **Step 4: Re-run identity tests.**

  Run the same focused command. Expected result: PASS for schema, uniqueness, provenance, and exact identities from the captured snapshot.

### Task 3: Replace the homepage view model and template with source sections

**Files:**
- Modify: `materials/33/clone/home_page.py`
- Modify: `materials/33/clone/templates/pages/home.html`

**Interfaces:**
- `render_home_body() -> str` remains the public function used by the existing app.
- It consumes `load_home_inventory()` and passes `sections: tuple[HomeSection, ...]` plus non-card source regions to the template.

- [ ] **Step 1: Remove inferred homepage tuples.**

  Delete the old `_POPULAR_COLUMNS`, `_CAREER_CARDS`, `_GOOGLE_CARDS`, `_SEARCH_COLUMNS`, `_AI_CARDS`, and `_RECOMMENDED_CARDS` data from `home_page.py`. Do not delete route-specific catalog data used by Browse, search, category, or course pages.

- [ ] **Step 2: Implement section-specific template branches.**

  Render `HomeSection.kind` through explicit Jinja branches for the captured promotional rail, list columns, learning-card grids, pathway/logo groups, purpose panel, outcomes, testimonials, FAQ, and footer. Each card must use its inventory `title`, `provider`, `badges`, `metadata`, `href`, and `image` without fallback text or fallback image values.

- [ ] **Step 3: Preserve user-controlled source controls.**

  Keep promotional switching as explicit radio/label or button controls. Do not introduce autoplay, timers, or transitions unless the evidence report records them.

- [ ] **Step 4: Run public rendering and identity tests.**

  Run:

  ```bash
  python -m pytest \
    materials/33/clone/tests/test_discovery_fidelity.py \
    materials/33/clone/tests/test_public_frontend.py -q
  ```

  Expected result: all current public heading, card identity, link, and local-asset assertions pass.

### Task 4: Match fullscreen geometry after content identity is green

**Files:**
- Modify: `materials/33/clone/static/home-prototype.css`
- Modify: `materials/33/clone/tests/test_fullscreen_geometry_fidelity.py`

**Interfaces:**
- The homepage shell resolves to the measured source rectangle at `1692 x 979`.
- The purpose panel exposes a stable measured height and four compact controls.
- Every card template has stable image dimensions so card content cannot resize the grid.

- [ ] **Step 1: Add failing geometry assertions.**

  At the configured viewport, assert the main shell width is within `1344 ± 4px`, its left edge is within `174 ± 4px`, the purpose panel width matches the shell, and each purpose control's width/height is within the captured source bounds. Assert card image rectangles are stable within each section.

- [ ] **Step 2: Run geometry tests against the existing CSS.**

  Run:

  ```bash
  python -m pytest materials/33/clone/tests/test_fullscreen_geometry_fidelity.py -q
  ```

  Expected result: FAIL if the old shared width cap or stretched purpose controls remain.

- [ ] **Step 3: Implement measured CSS.**

  Use a source shell rule equivalent to `min(calc(100% - 40px), 1344px)` at the acceptance viewport, retain independent overflow rails, set explicit `aspect-ratio` or height/width for each section's image format, and give the purpose panel the captured height and compact control widths. Keep text wrapping inside its parent and avoid viewport-scaled font sizes.

- [ ] **Step 4: Re-run geometry and visual smoke tests.**

  Run the focused geometry test and the existing desktop visual smoke test. Expected result: PASS without changing public route behavior.

### Task 5: Verify all public journeys without expanding authentication scope

**Files:**
- Modify: `materials/33/clone/tests/test_public_frontend.py`
- Modify: `materials/33/clone/tests/test_search_interactions_fidelity.py`
- Modify: `materials/33/clone/tests/test_current_phase_matrix.py`

**Interfaces:**
- Existing public routes and local navigation remain stable.
- Login, signup, recovery, dashboard, lesson, quiz, history, and checkout tests remain separate and are not weakened.

- [ ] **Step 1: Add route-level public assertions.**

  Cover `/`, `/browse`, all configured subject routes, a captured course detail route, the impossible query `zzzz-no-match-websitebench`, public support, and a non-existent path. Assert heading, canonical local path, safe recovery link, and local network closure for each route.

- [ ] **Step 2: Add signed-out validation assertions.**

  From a public course page, activate the enrollment action while signed out and assert the precise local permission/required-field prompt appears with no mutation or remote request.

- [ ] **Step 3: Run the public phase matrix.**

  Run:

  ```bash
  python -m pytest \
    materials/33/clone/tests/test_public_frontend.py \
    materials/33/clone/tests/test_discovery_fidelity.py \
    materials/33/clone/tests/test_search_interactions_fidelity.py \
    materials/33/clone/tests/test_current_phase_matrix.py -q
  ```

  Expected result: all Stage 1 journeys pass; deferred authenticated/payment journeys remain reported as deferred rather than falsely marked source-complete.

### Task 6: Source/candidate comparison and diagnostic handoff

**Files:**
- Modify only files owned by Tasks 1–5 when a measured mismatch is found.
- Create: `materials/33/source-evidence/2026-08-19-accessible-fullscreen/home-public-comparison.json`

**Interfaces:**
- Consumes the frozen current-home evidence and the local clone at `http://127.0.0.1:8044/`.
- Produces a diagnostic comparison of route, heading sequence, card identities, image load status, rectangles, and region screenshots.

- [ ] **Step 1: Run source and clone at the same viewport.**

  Use the same Playwright scenario for both targets and compare only sanitized observations. Check the full page after all lazy sections are loaded; do not compare a partially loaded source against a complete clone.

- [ ] **Step 2: Repair only evidence-backed mismatches.**

  For each difference, identify the owning section and update its source record or CSS rectangle. If the source evidence is insufficient, leave the record unresolved and report it instead of inventing content.

- [ ] **Step 3: Run complete verification.**

  Run:

  ```bash
  python -m pytest materials/33/clone/tests -q
  python tools/offline_clone/run.py verify --site materials/33
  ```

  Also run the repository sensitive-data and local-network closure checks. Record diagnostic status and any deferred authenticated/payment coverage; do not treat diagnostic output as an acceptance gate.

- [ ] **Step 4: Stop for manual review without committing.**

  Restart the local service on `127.0.0.1:8044`, verify HTTP 200 for `/`, and hand the current public-first build to the user for visual review. Do not commit or modify unrelated dirty files.

## Deferred follow-up plans

After the public-first build is accepted, create separate plans for:

1. Local login, registration, password recovery, and dashboard shell behavior.
2. Seeded learning, history, progress, quiz, and preference states.
3. Deep Learning enrollment and local-sandbox checkout review without card entry.

Those plans must preserve the public snapshot and must not use real credentials,
payment data, external enrollment, email, or production side effects.
