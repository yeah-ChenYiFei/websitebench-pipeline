# Coursera WACZ Homepage Fidelity Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the local Coursera homepage visually match the WACZ-rendered homepage, with immediate focus on the three learning-pathway illustrations and four learner-purpose pictograms, then repair material region-level differences across the full page.

**Architecture:** Keep the existing network-closed FastAPI and static HTML/CSS/JavaScript structure. Reconstruct the missing source-visible artwork as inline local SVG so it remains crisp, responsive, and dependency-free; use Playwright assertions for the seven repaired controls and region screenshots for full-page visual convergence.

**Tech Stack:** Python 3.14, FastAPI, HTML5, CSS, inline SVG, pytest, Playwright, WebsiteBench declarative diagnostics.

## Global Constraints

- The supplied WACZ rendering is the sole visual authority.
- Reproduce visible typography, spacing, dimensions, borders, backgrounds, iconography, image crops, and section order from the archived homepage.
- Do not use unrelated text glyphs or independently designed illustrations where the WACZ provides visible evidence.
- Use only local HTML, CSS, JavaScript, fonts, images, and inline SVG; runtime remote requests remain forbidden.
- Preserve the manual-only promotional switching behavior and do not add autoplay.
- Do not add accounts, authentication, checkout, payment, email, database, or routes beyond the archived homepage.
- Do not modify `materials/33`, deploy, publish, or run `git commit`.
- Leave all changes uncommitted for the user's manual review.

---

### Task 1: Seven-Module Visual Regression Contract

**Files:**
- Modify: `materials/coursera-wacz-home/clone/tests/test_browser.py`

**Interfaces:**
- Consumes: the real rendered homepage at `1191 x 979` from the existing `page` fixture.
- Produces: browser assertions for `[data-pathway-card]`, `[data-pathway-art]`, `[data-purpose-choice]`, and `[data-purpose-icon]`.

- [x] **Step 1: Add a failing learning-pathway illustration test**

Add a Playwright test that queries all three `[data-pathway-card]` buttons and asserts the literal count is three. For each button, assert one visible `[data-pathway-art]` SVG exists, its bounding box is at least `88 x 56` CSS pixels at the desktop viewport, and it contains at least three visible vector primitives. Also assert the three accessible names are exactly `Launch a new career`, `Try Coursera for Business`, and `Earn a degree`.

- [x] **Step 2: Add a failing learner-purpose icon test**

Add a Playwright test that queries all four `[data-purpose-choice]` buttons and asserts the literal count is four. For each button, assert one visible `[data-purpose-icon]` exists, its bounding box is square and at least `28 x 28` CSS pixels, its computed background is Coursera blue rather than transparent, and its nested SVG has a non-zero bounding box.

- [x] **Step 3: Run the two new tests and verify RED**

Run:

```bash
cd materials/coursera-wacz-home/clone
LD_LIBRARY_PATH=/tmp/playwright-libs/root/usr/lib/x86_64-linux-gnu \
  PYTHONDONTWRITEBYTECODE=1 \
  pytest -p no:cacheprovider \
  tests/test_browser.py::test_learning_pathways_match_the_archived_illustrated_cards \
  tests/test_browser.py::test_purpose_choices_match_the_archived_blue_icon_tiles -v
```

Expected: both tests fail because the current markup uses plain `▣`, `△`, `♧`, `⇄`, `↗`, and `⌘` glyphs and does not expose the required illustrated elements.

### Task 2: Source-Grounded Pathway Illustrations

**Files:**
- Modify: `materials/coursera-wacz-home/clone/index.html:130-134`
- Modify: `materials/coursera-wacz-home/clone/static/styles.css:105-107`

**Interfaces:**
- Consumes: the three archived pathway-card compositions visible in `source-evidence/home-reference.png`.
- Produces: three buttons marked `[data-pathway-card]`, each containing one inline SVG marked `[data-pathway-art]`.

- [x] **Step 1: Replace the three fallback glyphs with original WACZ art assets**

For `Launch a new career`, draw the archived pale-lilac folded background, blue outlined career/profile tile, and its small circular/rectangular details. For `Try Coursera for Business`, draw the archived angular lilac background and blue connected-team/organization outline. For `Earn a degree`, draw the archived lilac background and blue graduation-cap outline. Give every decorative SVG `aria-hidden="true"`, a stable `viewBox`, and no external references.

- [x] **Step 2: Match archived card geometry in CSS**

Keep the three-column grid, then match the WACZ card height, pale blue background, corner radius, text position, overflow crop, illustration size, and right-edge placement. Ensure SVG strokes use the archived Coursera blue/lilac palette and do not inherit black button text.

- [x] **Step 3: Run the pathway test and verify GREEN**

Run the first test from Task 1. Expected: PASS with three visible, source-grounded illustrations.

### Task 3: Source-Grounded Learner-Purpose Pictograms

**Files:**
- Modify: `materials/coursera-wacz-home/clone/index.html:157-166`
- Modify: `materials/coursera-wacz-home/clone/static/styles.css:114-117`

**Interfaces:**
- Consumes: the four archived blue icon tiles visible in `source-evidence/home-reference.png`.
- Produces: four buttons marked `[data-purpose-choice]`, each containing one blue `[data-purpose-icon]` tile and a local inline SVG.

- [x] **Step 1: Replace the four fallback characters with original WACZ pictograms**

Draw distinct white-on-blue pictograms for starting a career, changing careers, growing in a role, and exploring topics outside work. Preserve the archived left icon tile, two-line label wrapping where needed, and button order.

- [x] **Step 2: Match archived choice geometry in CSS**

Match the WACZ panel background, heading spacing, button height, border color, radius, icon tile size, text weight, and four-column gaps. Keep the icon tile fixed-size so labels align consistently.

- [x] **Step 3: Run the purpose-choice test and verify GREEN**

Run the second test from Task 1. Expected: PASS with four blue, square, visible pictogram tiles.

### Task 4: Full-Page Region Fidelity Convergence

**Files:**
- Modify: `materials/coursera-wacz-home/clone/index.html`
- Modify: `materials/coursera-wacz-home/clone/static/styles.css`
- Update: `materials/coursera-wacz-home/source-evidence/candidate-desktop.png`
- Update: `materials/coursera-wacz-home/source-evidence/candidate-mobile.png`
- Modify only for demonstrable archive/machine limitations: `materials/coursera-wacz-home/KNOWN_DIFFERENCES.md`

**Interfaces:**
- Consumes: `source-evidence/home-reference.png`, `source-evidence/home-reference-viewport.png`, and the repaired homepage.
- Produces: updated desktop/mobile screenshots and a region-by-region visual audit covering the entire archived homepage.

- [x] **Step 1: Capture fresh desktop and mobile screenshots**

Use the existing local Uvicorn server and Playwright capture seam to write `/` at `1191 x 979` full-page and `390 x 844` full-page to the two candidate screenshot paths. Collect request hosts and assert every request resolves to `127.0.0.1`.

- [x] **Step 2: Compare every visible region in order**

Inspect hero/navigation, promotional controls, New and popular, subscription/business cards, organization strip, learning pathways, categories, trending searches, learner-purpose choices, career cards, outcome banner, testimonials, FAQ, and footer. Record each material mismatch in a temporary checklist under `/tmp`, without adding a new repository gate or report format.

- [x] **Step 3: Repair material full-page mismatches one region at a time**

For each checklist item, adjust only source-grounded HTML/CSS or use a presentation asset already present in the WACZ. After each region, recapture that region and compare dimensions, spacing, color, crop, and typography before moving on. Do not mark implementation convenience as a known difference.

- [x] **Step 4: Verify narrow-screen behavior**

At `390 x 844`, confirm the repaired artwork scales or crops cleanly, all labels remain legible, and `document.documentElement.scrollWidth - clientWidth` equals `0`.

### Task 5: Final Regression, Diagnostics, and Handoff

**Files:**
- Modify only if a failing verification identifies an in-scope defect.

**Interfaces:**
- Consumes: the repaired homepage, tests, declarative scope, and candidate screenshots.
- Produces: fresh verification evidence and a running uncommitted review server.

- [x] **Step 1: Run the full Python/Playwright suite**

Run:

```bash
cd materials/coursera-wacz-home/clone
LD_LIBRARY_PATH=/tmp/playwright-libs/root/usr/lib/x86_64-linux-gnu \
  PYTHONDONTWRITEBYTECODE=1 pytest -p no:cacheprovider -v
```

Expected: all tests pass with no errors or warnings.

- [x] **Step 2: Run the manual-promotion state test**

Run `node --test tests/promo-state.test.mjs`. Expected: one test passes and the promotional index remains unchanged without user input.

- [x] **Step 3: Run WebsiteBench diagnostics**

Run `python tools/offline_clone/run.py tools list`, then:

```bash
python tools/offline_clone/run.py verify \
  --site materials/coursera-wacz-home --section static
```

Expected: static execution is complete; inspect any findings rather than treating the diagnostic status as an acceptance gate. Attempt the generic live diagnostic only through its existing command and record the existing host isolation limitation if it recurs.

- [x] **Step 4: Confirm manual-review service and working-tree state**

Confirm `http://127.0.0.1:8041/` returns HTTP `200`, generated cache directories are absent, `materials/33` is unchanged, HEAD remains `d060385`, and every Coursera WACZ homepage file remains uncommitted.
