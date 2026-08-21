# Coursera WACZ Homepage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an independent, network-closed reconstruction of the single Coursera homepage captured in the supplied WACZ, with two visible promotional cards and user-controlled switching that never autoplays.

**Architecture:** A minimal FastAPI serving seam exposes one static HTML/CSS/JavaScript homepage and local archived visual assets. A small pure JavaScript state module owns promotional selection, while DOM wiring handles controls, notices, FAQ disclosure, and the local-only privacy panel. Pytest and Playwright exercise the real served page; WebsiteBench declarative diagnostics cover route and network closure.

**Tech Stack:** Python 3.14, FastAPI, Uvicorn, HTML5, CSS, browser-native ES modules, pytest, Playwright.

## Global Constraints

- Create only `materials/coursera-wacz-home`; do not modify `materials/33`.
- The only reconstructed source content route is `/`.
- Treat the supplied WACZ as the source of truth; the identical captures are English-language homepage captures.
- Show two promotional cards together at the primary `1191 x 979` viewport.
- Promotional changes happen only after previous, next, indicator, or keyboard input; no autoplay timer is allowed.
- Serve every runtime dependency locally and issue zero remote requests.
- Exclude telemetry, advertising pixels, analytics, request bodies, cookies, headers, session state, and private data.
- Do not implement search results, authentication, accounts, courses, enrollment, checkout, payment, orders, email, or a database.
- Do not deploy or publish the site.
- Do not run `git commit`; leave the complete result uncommitted for manual review.

---

### Task 1: Sanitized WACZ Evidence and Asset Inventory

**Files:**
- Create: `materials/coursera-wacz-home/source-evidence/archive-summary.json`
- Create: `materials/coursera-wacz-home/source-evidence/home-reference.png`
- Create: `materials/coursera-wacz-home/source-assets/manifest.json`
- Create: `materials/coursera-wacz-home/clone/static/assets/*`

**Interfaces:**
- Consumes: `/mnt/c/Users/15332/Downloads/my-archiving-session (1).wacz`, containing `pages/pages.jsonl`, `indexes/index.cdx`, and `archive/data.warc.gz`.
- Produces: a sanitized public-page summary, a local reference screenshot, and presentation-only assets referenced by stable paths under `/static/assets/`.

- [ ] **Step 1: Generate a temporary read-only WARC replay map**

Use a script under `/tmp` to read CDX offsets, decompress WARC members, parse response headers, resolve revisit records by public payload digest, and fulfill Playwright requests from memory. Never write raw request/response headers or bodies to the repository.

- [ ] **Step 2: Capture the archived homepage**

Open `https://www.coursera.org/` through Playwright interception at `1191 x 979`, wait for the archived DOM to settle without live network access, and save only the sanitized public screenshot as `source-evidence/home-reference.png`.

- [ ] **Step 3: Record the sanitized archive summary**

Create `archive-summary.json` with this public schema and no digest, query string, request body, header, cookie, token, or identity data:

```json
{
  "schema_version": "websitebench.wacz-public-summary.v1",
  "archive_title": "My Archiving Session",
  "capture_count": 2,
  "captured_routes": ["https://www.coursera.org/"],
  "page_language": "en",
  "primary_viewport": {"width": 1191, "height": 979},
  "private_or_operational_data_retained": false
}
```

- [ ] **Step 4: Extract presentation assets only**

Copy only visible homepage images/icons from replayed GET responses into `clone/static/assets/`, rename them descriptively, and omit pixels, analytics code, session replay, identity-provider code, and remote fonts.

- [ ] **Step 5: Write the asset manifest and inspect every entry**

Each manifest entry has exactly `id`, `local_path`, `media_type`, `source_host`, and `source_path`; `source_path` contains no query. Verify each file is a valid image and each host/path belongs to a resource actually displayed by the archived homepage.

### Task 2: Static Homepage Contract and Serving Seam

**Files:**
- Create: `materials/coursera-wacz-home/clone/app.py`
- Create: `materials/coursera-wacz-home/clone/requirements.txt`
- Create: `materials/coursera-wacz-home/clone/index.html`
- Create: `materials/coursera-wacz-home/clone/static/styles.css`
- Create: `materials/coursera-wacz-home/clone/tests/conftest.py`
- Create: `materials/coursera-wacz-home/clone/tests/test_app.py`

**Interfaces:**
- Consumes: local assets from Task 1.
- Produces: `app:app`, serving `/`, `/static/*`, `/healthz`, and a branded 404 for every unsupported content route.

- [ ] **Step 1: Write failing route and document tests**

Create FastAPI TestClient tests asserting that `/` returns 200 with the archived title, `lang="en"`, audience navigation, search, two visible promo articles, `New and popular`, careers, categories, learner outcomes, FAQ, footer, and a footer cookie-preference affordance; `/healthz` returns `{"status":"ok"}`; `/login` returns 404 with a homepage recovery link.

- [ ] **Step 2: Run the route tests and verify RED**

Run:

```bash
cd materials/coursera-wacz-home/clone
pytest tests/test_app.py -v
```

Expected: collection fails because `app.py` and the homepage do not exist.

- [ ] **Step 3: Implement the minimal serving seam and semantic HTML**

Create a FastAPI app with `StaticFiles`, `FileResponse`, a JSON health route, and an HTML 404 handler. Build `index.html` with semantic landmarks and source-grounded public copy from the WACZ page text. Use local links or buttons for uncaptured destinations and an `aria-live="polite"` archive-boundary notice.

- [ ] **Step 4: Add the primary layout CSS**

Implement the archived dark audience bar, white main navigation, rounded promo panels, course-card grids, section spacing, career panels, organization strip, category grid, testimonials, FAQ, and multi-column footer. Do not display a fixed privacy banner in the default state. At widths below 760 px, stack navigation, promos, grids, and footer columns without horizontal overflow.

- [ ] **Step 5: Run route tests and verify GREEN**

Run `pytest tests/test_app.py -v`. Expected: all Task 2 tests pass with no warning or error output.

### Task 3: Manual Promotional Switching and Homepage Interactions

**Files:**
- Create: `materials/coursera-wacz-home/clone/static/promo-state.js`
- Create: `materials/coursera-wacz-home/clone/static/home.js`
- Create: `materials/coursera-wacz-home/clone/tests/promo-state.test.mjs`
- Create: `materials/coursera-wacz-home/clone/tests/test_browser.py`
- Modify: `materials/coursera-wacz-home/clone/index.html`
- Modify: `materials/coursera-wacz-home/clone/static/styles.css`

**Interfaces:**
- Consumes: elements marked with `[data-promo-card]`, `[data-promo-prev]`, `[data-promo-next]`, and `[data-promo-dot]`.
- Produces: `createPromoState({itemCount, visibleCount, onChange})` returning `{next, previous, goTo, getIndex}`; `home.js` maps the state to DOM visibility and accessibility attributes.

- [ ] **Step 1: Write failing pure-state tests**

Use Node's built-in test runner to assert literal sequences: for three cards with two visible, initial index is `0`, consecutive `next()` calls produce `1`, `2`, then wrap to `0`; `previous()` from `0` wraps to `2`; and `goTo(9)` normalizes to a valid index. Wait 150 ms without invoking an action and assert the index and callback count remain unchanged.

- [ ] **Step 2: Run the state tests and verify RED**

Run `node --test tests/promo-state.test.mjs`. Expected: FAIL because `promo-state.js` does not exist.

- [ ] **Step 3: Implement the pure promotional state**

Implement the four-method state object with modulo normalization and synchronous `onChange({index, visibleIndexes})`. Do not call `setTimeout`, `setInterval`, `requestAnimationFrame`, or recursively trigger state changes.

- [ ] **Step 4: Run the state tests and verify GREEN**

Run `node --test tests/promo-state.test.mjs`. Expected: all tests pass.

- [ ] **Step 5: Write failing real-browser interaction tests**

Start the actual FastAPI app from a pytest fixture and use Playwright to verify:

- exactly two promo cards are visible initially;
- clicking Next changes the visible card IDs and selected indicator;
- waiting 800 ms does not change them again;
- ArrowRight and ArrowLeft switch in opposite directions while a promo control has focus;
- clicking a position indicator selects its pair;
- the footer cookie-preference button opens and closes a local explanatory dialog without a remote request;
- submitting search or activating an uncaptured destination leaves the page at `/` and announces the archive boundary; and
- the page has no horizontal overflow at 390 px width.

- [ ] **Step 6: Run browser tests and verify RED**

Run `pytest tests/test_browser.py -v`. Expected: interaction assertions fail because `home.js` is not wired.

- [ ] **Step 7: Wire real DOM behavior**

Render state by toggling `hidden`, `aria-hidden`, `aria-current`, and the selected dot class. Handle click and key events, local notices, FAQ disclosure, and privacy dismissal. Never navigate or fetch an uncaptured route.

- [ ] **Step 8: Run browser tests and verify GREEN**

Run `pytest tests/test_browser.py -v`. Expected: all browser interactions pass and observed remote-request count is zero.

### Task 4: WebsiteBench Declarative Scope and Diagnostics

**Files:**
- Create: `materials/coursera-wacz-home/clone.yaml`
- Create: `materials/coursera-wacz-home/scope/purpose.json`
- Create: `materials/coursera-wacz-home/scope/invariants.json`
- Create: `materials/coursera-wacz-home/scope/routes.json`
- Create: `materials/coursera-wacz-home/scope/journeys.json`
- Create: `materials/coursera-wacz-home/scope/checkpoints.json`
- Create: `materials/coursera-wacz-home/scope/claims.jsonl`
- Create: `materials/coursera-wacz-home/scope/coverage.json`
- Create: `materials/coursera-wacz-home/scope/verify.json`
- Create: `materials/coursera-wacz-home/KNOWN_DIFFERENCES.md`

**Interfaces:**
- Consumes: `app:app` and browser selectors from Tasks 2–3.
- Produces: an `offline-clone.manifest.v2` site with one homepage route, loaded/manual-switch/privacy-dismiss states, and diagnostic-only verification.

- [ ] **Step 1: Write the minimal declarative contracts**

Use site ID `coursera-wacz-home`, anonymous `en-US` baseline, viewport `1191 x 979`, GET/HEAD-only source policy, forbidden runtime remote requests, and no backend model. Define exactly one source route (`home`) and three states (`home.loaded`, `home.promo-switched`, `home.privacy-dismissed`).

- [ ] **Step 2: Run static diagnostics**

Run:

```bash
python tools/offline_clone/run.py verify --site materials/coursera-wacz-home --section static
```

Expected: execution completes; inspect and repair every in-scope structural or remote-reference finding.

- [ ] **Step 3: Run live diagnostics**

Run:

```bash
python tools/offline_clone/run.py verify --site materials/coursera-wacz-home --section live
```

Expected: execution completes; inspect and repair route, selector, screenshot-region, and network-closure findings.

- [ ] **Step 4: Record honest known differences**

Document that the reconstruction omits analytics/advertising, does not implement uncaptured routes, uses system fonts where archived webfonts are unnecessary, and provides deterministic manual promo controls with no autoplay. Do not turn diagnostic output into an acceptance gate.

### Task 5: Final Verification and Manual-Review Handoff

**Files:**
- Modify only if a failing verification identifies an in-scope defect.

**Interfaces:**
- Consumes: the full site from Tasks 1–4.
- Produces: fresh verification output, a running local review server, and an uncommitted working tree.

- [ ] **Step 1: Run the full test suite**

Run:

```bash
cd materials/coursera-wacz-home/clone
pytest -v
node --test tests/promo-state.test.mjs
```

Expected: zero failed tests.

- [ ] **Step 2: Capture candidate screenshots**

Capture `/` at `1191 x 979` and `390 x 844`, inspect both images, and compare the primary regions against `source-evidence/home-reference.png`. Repair material page-structure, spacing, overflow, and interaction-state differences, then rerun affected tests.

- [ ] **Step 3: Audit network and secrets**

Run a real browser load with request collection and confirm every request targets the local server. Search the new site for remote runtime URLs, authorization/cookie header names, email addresses, card fields, and embedded request bodies; remove any operational or sensitive material.

- [ ] **Step 4: Review the exact working-tree scope**

Run `git status --short` and `git diff --stat`, verify no pre-existing untracked file or `materials/33` file changed, and leave all new work uncommitted.

- [ ] **Step 5: Start the manual review server**

Run Uvicorn on an available loopback port, confirm `GET /` returns 200, and report the URL plus the desktop/mobile screenshots and known differences to the user. Do not commit, deploy, or publish.
