# Coursera Deep Learning Search Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:executing-plans` to implement this plan task-by-task in the
> current workspace. The user selected inline execution. Do not dispatch
> subagents and do not commit.

**Goal:** Reproduce the source-observed English Coursera Deep Learning search,
filter drawer and impossible-query recovery at the `1191 × 979` viewport.

**Architecture:** Move search presentation out of `app.py` into a dedicated
source-data module and Jinja template. Retain the existing pure catalog filter
function for local GET semantics while using a fixed evidence-backed result set
for the selected Deep Learning query. Route-scoped CSS provides the source
layout and a `:target` filter drawer without weakening `script-src 'none'`.

**Tech Stack:** FastAPI, Jinja2, HTML/CSS, pytest,
WebsiteBench Playwright diagnostics.

## Global Constraints

- Primary viewport is exactly `1191 × 979`.
- All visible copy on this route is English.
- The AI Overview remains in its directly observed loading state; never add a
  generated summary.
- The twelve cards, order, identities, metadata, covers and links follow
  `docs/superpowers/specs/2026-08-18-coursera-search-page-design.md`.
- All runtime assets are local; no remote requests, iframe or source proxy.
- Preserve unrelated dirty work, do not commit, and do not add unsupported
  animations.
- Do not change authentication, account, learning, checkout, payment, email,
  database or backend runtime behavior.

---

### Task 1: Lock the search-page source identity contract

**Files:**

- Create: `materials/33/clone/tests/test_search_page_fidelity.py`
- Modify: `materials/33/clone/tests/test_public_frontend.py`
- Modify: `materials/33/clone/tests/test_desktop_contract.py`

**Interfaces:**

- Consumes: FastAPI `app` and the existing `/search` route.
- Produces: exact HTML contracts for `render_search_body()` and the route's
  English no-results behavior.

- [ ] **Step 1: Write the exact failing identity test**

Add a test that requests `/search?query=Deep%20Learning`, extracts every
`data-search-result` card and asserts this exact ordered tuple:

```python
EXPECTED_RESULTS = (
    ("Deep Learning", "DeepLearning.AI", "/specializations/deep-learning"),
    ("Neural Networks and Deep Learning", "DeepLearning.AI", "/learn/neural-networks-deep-learning"),
    ("IBM Deep Learning with PyTorch, Keras and Tensorflow", "IBM", "/professional-certificates/ibm-deep-learning-with-pytorch-keras-tensorflow"),
    ("PyTorch for Deep Learning", "DeepLearning.AI", "/professional-certificates/pytorch-for-deep-learning"),
    ("Machine Learning", "Multiple educators", "/specializations/machine-learning-introduction"),
    ("Introduction to Deep Learning & Neural Networks with Keras", "IBM", "/learn/introduction-to-deep-learning-with-keras"),
    ("Deep Learning with PyTorch", "IBM", "/search?query=Deep%20Learning%20with%20PyTorch"),
    ("IBM AI Engineering", "IBM", "/professional-certificates/ai-engineer"),
    ("Deep Learning Engineering", "Coursera", "/specializations/deep-learning-engineering"),
    ("Deep Learning with Python: CNN, ANN & RNN", "EDUCBA", "/specializations/deep-learning-python-cnn-ann-rnn"),
    ("Learning Deep Learning", "Pearson", "/specializations/pearson-learning-deep-learning-from-perception-to-large-language-models"),
    ("Deep Learning", "Illinois Tech", "/search?query=Illinois%20Tech%20Deep%20Learning"),
)
```

Assert `<html lang="en">`, `AI Overview`, `Top courses to get started:`, the
four prompt chips, `All Results`, the interstitial after card six and the six
filter chips. Assert the old strings `AI 概览`, `You are looking for`,
`This specialization covers`, `您的隐私与本次聊天` and `所有结果` are absent.

- [ ] **Step 2: Write the failing no-results and query-alias test**

Request both `/search?q=Deep+Learning` and
`/search?query=Deep%20Learning`; assert equal card order and the corresponding
header input value. Request the impossible query and assert:

```python
assert 'data-result-count="0"' in html
assert "No results for zzzz-no-match-websitebench" in html
assert 'href="/search?query=Deep%20Learning"' in html
assert 'href="/browse"' in html
```

- [ ] **Step 3: Update superseded Chinese expectations**

Replace only the search-specific Chinese expectations in
`test_public_frontend.py` and `test_desktop_contract.py` with the selected
English source state. Keep the existing combined-filter result-ID assertions.

- [ ] **Step 4: Run the focused tests and confirm RED**

Run from `materials/33/clone`:

```bash
pytest -q tests/test_search_page_fidelity.py tests/test_public_frontend.py tests/test_desktop_contract.py
```

Expected: failures identify the old inline Chinese search markup, invented AI
summary and missing exact result cards.

- [ ] **Step 5: Review checkpoint**

Inspect the diff to ensure this task changes contracts only. Do not commit.

### Task 2: Add the source-backed search data and renderer

**Files:**

- Create: `materials/33/clone/search_page.py`
- Create: `materials/33/clone/templates/pages/search.html`
- Modify: `materials/33/clone/app.py`

**Interfaces:**

- Consumes: `filtered_records: list[dict[str, object]]`, `query: str`, and
  `filters: dict[str, str]` from the existing route.
- Produces:
  `render_search_body(*, query: str, filtered_records: list[dict[str, object]], filters: dict[str, str]) -> str`.

- [ ] **Step 1: Define immutable source-card data**

In `search_page.py`, define `SEARCH_RESULTS` as twelve dictionaries in the
exact order from Task 1. Each entry contains `title`, `provider`, `href`,
`image`, `badges`, `skills`, `rating`, `reviews`, `meta`, and `credential`.
Transcribe card metadata from the retained full-page screenshot, including:

```python
{
    "title": "Deep Learning",
    "provider": "DeepLearning.AI",
    "href": "/specializations/deep-learning",
    "image": "/static/search/deep-learning.png",
    "badges": ("Free Trial",),
    "skills": "Convolutional Neural Networks, Recurrent Neural Networks (RNNs),…",
    "rating": "4.8",
    "reviews": "147K reviews",
    "meta": "Intermediate · Specialization · 3 - 6 Months",
    "credential": True,
}
```

Use the same explicit structure for all twelve cards; do not derive provider,
rating or product type from title heuristics.

- [ ] **Step 2: Render the evidence-ordered page**

Configure a local Jinja environment following `data_science_page.py`. Render:
the loading AI bars, three loading starter cards, four prompt chips, filter
chips, first six cards, the four-choice interstitial, final six cards and the
assistant rail. Add `data-search-result`, `data-result-title`,
`data-result-provider` and `data-result-href` attributes for exact tests.

- [ ] **Step 3: Render the impossible-query recovery state**

When `filtered_records` is empty, replace the grid with an English no-results
panel and source-safe recovery links. Do not render arbitrary cards as query
matches. Preserve `data-result-count="0"`.

- [ ] **Step 4: Replace only the inline search body in `app.py`**

Import `render_search_body`, keep `_filter_catalog()` and query parameter
parsing, and call the new renderer. Set `language="en"`,
`body_class="source-search-page"`, the observed document title and
`search_value=q or query`. Remove `_related_search_card()` if no remaining
caller exists.

- [ ] **Step 5: Run the focused tests**

Run the Task 1 pytest command. Expected: identity/copy tests pass; visual
drawer or asset assertions may remain red until Task 3.

- [ ] **Step 6: Review checkpoint**

Confirm the route no longer contains invented AI or assistant text. Do not
commit.

### Task 3: Add exact card media, geometry and filter interaction

**Files:**

- Create: `materials/33/clone/static/search-page.css`
- Create: `materials/33/clone/static/search/*`
- Modify: `materials/33/clone/ui.py`
- Modify: `materials/33/clone/tests/test_search_page_fidelity.py`

**Interfaces:**

- Consumes: classes and IDs emitted by `templates/pages/search.html`.
- Produces: a local modal drawer controlled by
  `#search-filter-open`, `#search-filter-drawer:target` and
  `[data-search-filter-close]`.

- [ ] **Step 1: Add a failing asset and drawer contract**

Assert all twelve image URLs start with `/static/`, resolve with status `200`,
and contain no `http://` or `https://`. Assert the drawer contains the exact
section labels, `Best Match` selected, `Newest`, `View`, and disabled
`Clear all`.

- [ ] **Step 2: Acquire or reuse exact observed covers**

Reuse already verified local copies for Deep Learning, Neural Networks and
Machine Learning. Download exact media only from URLs already recorded in
`source-search-deep-learning-playwright.json`; record source URL-to-local-path
mapping in `materials/33/source-evidence/search-card-assets.json`. If one
experiment-only asset cannot be recovered, use a lossless source screenshot
crop and record its rectangle and softness limitation.

- [ ] **Step 3: Implement route-scoped layout CSS**

Reproduce the `787px / 404px` split, `48px` main inset, three-column cards,
source card border/radius, image ratio, badges, clipped skills text,
interstitial placement and assistant composer. Scope every selector under
`.source-search-page`; do not change Data Science or Browse card geometry.

- [ ] **Step 4: Implement the filter drawer without animation**

Use an accessible `:target` layer so the existing CSP remains unchanged. The
open control targets `#search-filter-drawer`; the close control and overlay
return to `#search-results`; `View` submits the GET form and therefore closes
the drawer on navigation. Do not add transitions. `Clear all` starts disabled,
matching the source screenshot.

- [ ] **Step 5: Include route-specific CSS**

Include `/static/search-page.css` through the existing page shell and scope
every rule under `.source-search-page` so unrelated routes are unchanged. Do
not add a script file or weaken the global content-security policy.

- [ ] **Step 6: Run focused tests**

Run:

```bash
pytest -q tests/test_search_page_fidelity.py tests/test_public_frontend.py tests/test_desktop_contract.py tests/test_desktop_visual.py
```

Expected: all search and desktop landmark contracts pass.

- [ ] **Step 7: Review checkpoint**

Check for remote runtime URLs and route-global CSS leakage. Do not commit.

### Task 4: Browser verification and proportional repair

**Files:**

- Create: `materials/33/scope/clone-search-deep-learning.json`
- Create: `materials/33/scope/clone-search-filter-panel.json`
- Create: `materials/33/scope/clone-search-no-results.json`
- Create: `materials/33/source-evidence/clone-search-deep-learning-playwright.json`
- Create: `materials/33/source-evidence/clone-search-filter-panel-playwright.json`
- Create: `materials/33/source-evidence/clone-search-no-results-playwright.json`
- Modify as findings require: search files from Tasks 2 and 3 only.

**Interfaces:**

- Consumes: running clone on loopback and WebsiteBench browser exploration.
- Produces: current diagnostic reports and screenshots for the three selected
  states.

- [ ] **Step 1: Write three declarative clone scenarios**

Default state: open `/search?query=Deep%20Learning`, assert route, English
landmarks, twelve cards and take a full-page screenshot. Drawer state: click
`Filter & Sort`, assert the exact drawer labels/buttons and take a viewport
screenshot. No-results state: open the impossible query, assert the message and
both recovery routes.

- [ ] **Step 2: Run the focused unit suite**

Run the Task 3 pytest command and retain its exact pass/fail count.

- [ ] **Step 3: Run the three Playwright clone scenarios**

Use the repository launcher and the temporary Playwright library path because
this environment lacks Chromium's NSS and ALSA libraries:

```bash
env LD_LIBRARY_PATH=/tmp/websitebench-playwright-libs/usr/lib/x86_64-linux-gnu \
  python tools/offline_clone/run.py tools explore \
  --spec materials/33/scope/clone-search-deep-learning.json \
  --base-url http://127.0.0.1:8044 --environment clone \
  --out materials/33/source-evidence/clone-search-deep-learning-playwright.json \
  --artifacts-dir materials/33/source-evidence/clone-search-deep-learning-playwright

env LD_LIBRARY_PATH=/tmp/websitebench-playwright-libs/usr/lib/x86_64-linux-gnu \
  python tools/offline_clone/run.py tools explore \
  --spec materials/33/scope/clone-search-filter-panel.json \
  --base-url http://127.0.0.1:8044 --environment clone \
  --out materials/33/source-evidence/clone-search-filter-panel-playwright.json \
  --artifacts-dir materials/33/source-evidence/clone-search-filter-panel-playwright

env LD_LIBRARY_PATH=/tmp/websitebench-playwright-libs/usr/lib/x86_64-linux-gnu \
  python tools/offline_clone/run.py tools explore \
  --spec materials/33/scope/clone-search-no-results.json \
  --base-url http://127.0.0.1:8044 --environment clone \
  --out materials/33/source-evidence/clone-search-no-results-playwright.json \
  --artifacts-dir materials/33/source-evidence/clone-search-no-results-playwright
```

Expected for every report: `status: passed`, zero console errors, zero failed
requests, zero blocked requests, twelve loaded images on the default state and
no remote runtime resources.

- [ ] **Step 4: Compare the source and candidate viewport regions**

Run the existing `compare-visual` tool using non-zero diagnostic thresholds for
header, AI skeleton, result grid and assistant rail. Inspect the images
side-by-side; do not treat the diagnostic status as an acceptance gate.

- [ ] **Step 5: Repair only machine-supported differences**

Adjust route-scoped widths, spacing, typography, card height and image fit in
small increments. Re-run the affected scenario after each repair batch. Never
replace source identities or add unsupported content to improve a pixel score.

- [ ] **Step 6: Run the site diagnostic and report known limitations**

Run:

```bash
python tools/offline_clone/run.py verify --site materials/33
```

Report static/live status, relevant test counts, Playwright reports, accepted
cover softness, the loading AI limitation and any unrelated pre-existing
failures. Do not commit.
