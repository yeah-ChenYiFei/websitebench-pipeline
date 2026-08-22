# Coursera Desktop Fidelity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild site 33 as a Chinese-default, high-fidelity desktop Coursera offline clone while preserving its real local learner and local-sandbox checkout semantics.

**Architecture:** Keep FastAPI route ownership, `learning_db`, `checkout`, and the generated WebsiteBench backend seam. Move source-derived HTML rendering into a focused UI module and split desktop CSS by surface. Route handlers supply deterministic local state; reusable UI helpers render the global chrome, public catalog, course, auth, learner, and checkout views.

**Tech Stack:** Python 3.14, FastAPI, TestClient, SQLite through `websitebench.site_backend`, local-sandbox payments, static CSS/SVG/images, pytest, Playwright and WebsiteBench offline-clone diagnostics.

## Global Constraints

- Default user-facing copy is Simplified Chinese; course/provider names and English query matching remain where source evidence requires them.
- Desktop visual target is `1191 × 979`; no mobile-fidelity work is introduced.
- Preserve site ID `33`, its generated backend runtime, unique database/volume identity, and session cookie boundary.
- Use only local runtime assets and `local-sandbox`; no remote requests, source iframe, source proxy, live payment, real email, or external publication.
- Do not commit SingleFile captures, authenticated screenshots, browser profiles, credentials, cookies, tokens, personal data, or sensitive inputs.
- Use post-redirect-get for mutations and retain existing actor-isolation/idempotency semantics.
- Each production behavior is preceded by a focused failing pytest assertion and a confirmed expected failure.

---

### Task 1: Establish the desktop source contract and tests

**Files:**
- Modify: `materials/33/scope/checkpoints.json`
- Modify: `materials/33/scope/verify.json`
- Modify: `materials/33/clone.yaml`
- Create: `materials/33/clone/tests/test_desktop_contract.py`
- Modify: `materials/33/clone/tests/conftest.py`

**Interfaces:**
- Consumes: current public source captures in local scratch and `scope/human-traces.json`.
- Produces: a `1191 × 979` desktop verification contract and `desktop_client` test fixture that later tasks use.

- [ ] **Step 1: Write the failing desktop contract tests**

```python
def test_desktop_shell_uses_source_observed_language_and_navigation(desktop_client):
    response = desktop_client.get("/")
    assert 'lang="zh-CN"' in response.text
    assert "为个人" in response.text
    assert 'href="/browse"' in response.text
    assert 'action="/search"' in response.text


def test_source_facing_checkout_alias_is_local_and_reachable(desktop_client):
    response = desktop_client.get("/payments/checkout", follow_redirects=False)
    assert response.status_code in {200, 303, 401}
    assert "coursera.org" not in response.headers.get("location", "")
```

- [ ] **Step 2: Run the new tests and verify RED**

Run: `python -m pytest materials/33/clone/tests/test_desktop_contract.py -q`

Expected: the language/navigation and `/payments/checkout` assertions fail because the old clone is English-first and has no source-facing checkout alias.

- [ ] **Step 3: Add only the contract configuration required for the tests**

Set the desktop checkpoint viewport to `1191 × 979`, remove mobile checkpoint entries from the site-specific scope, set `clone.yaml` baseline locale to `zh-CN`, and add `/payments/checkout` to the site verify routes. Do not change repository-wide diagnostic code.

- [ ] **Step 4: Add the local test fixture**

Add a `desktop_client` fixture that uses a temporary `33.sqlite3` database, calls `learning_db.close_services()` before/after the TestClient context, and has no authenticated cookie. Do not use the real source browser state.

- [ ] **Step 5: Run the configuration tests and schema checks**

Run:

```bash
python -m pytest materials/33/clone/tests/test_desktop_contract.py -q
python -m websitebench.offline_clone.cli verify --site materials/33
```

Expected: tests remain RED only for missing presentation behavior; the site configuration is structurally valid or reports only the existing visual-evidence gaps.

- [ ] **Step 6: Commit the contract baseline**

```bash
git add materials/33/scope/checkpoints.json materials/33/scope/verify.json materials/33/clone.yaml materials/33/clone/tests/conftest.py materials/33/clone/tests/test_desktop_contract.py
git commit -m "test(site-33): define Chinese desktop fidelity contract"
```

### Task 2: Build the shared Coursera desktop rendering system

**Files:**
- Create: `materials/33/clone/ui.py`
- Create: `materials/33/clone/static/desktop-base.css`
- Create: `materials/33/clone/static/desktop-chrome.css`
- Modify: `materials/33/clone/app.py`
- Modify: `materials/33/clone/tests/test_desktop_contract.py`

**Interfaces:**
- Consumes: `request`, `authenticated: bool`, `title`, and page-body HTML.
- Produces: `ui.page(...)`, `ui.header(...)`, `ui.footer()`, `ui.escape_text(...)`, and semantic class names used by every route.

- [ ] **Step 1: Write failing shell structure tests**

```python
def test_public_shell_has_observed_desktop_chrome(desktop_client):
    html = desktop_client.get("/").text
    for marker in (
        'class="wb-audience-bar"',
        'class="wb-header"',
        'class="wb-wordmark"',
        'placeholder="您想学习什么？"',
        'class="wb-footer"',
    ):
        assert marker in html


def test_authenticated_shell_replaces_auth_links_with_my_learning(desktop_client):
    # Authenticate with the seeded local learner using the existing helper.
    login_seeded_learner(desktop_client, "progress")
    html = desktop_client.get("/my-learning").text
    assert 'href="/my-learning"' in html
    assert "退出登录" in html
```

- [ ] **Step 2: Run the shell tests and verify RED**

Run: `python -m pytest materials/33/clone/tests/test_desktop_contract.py -q`

Expected: missing `wb-*` component markers and Chinese labels cause failure.

- [ ] **Step 3: Implement focused UI helpers**

Create `ui.py` with HTML escaping, `header`, `footer`, and `page` functions. `page` must emit `lang="zh-CN"`, desktop viewport metadata, local stylesheet links only, and no inline remote URL. Replace `_header`, `_footer`, and `_page` calls in `app.py` with these helpers without changing request/session helpers or route ownership.

- [ ] **Step 4: Implement the base and chrome CSS**

Create CSS tokens for Coursera blue, ink, borders, spacing, text scale, desktop content width, and focus state. Implement the two-tier header, search capsule, account controls, footer columns, and a `@media (max-width: 900px)` safe collapse only; do not add a mobile target.

- [ ] **Step 5: Run GREEN and regression tests**

Run:

```bash
python -m pytest materials/33/clone/tests/test_desktop_contract.py -q
python -m pytest materials/33/clone/tests/test_smoke.py -q
```

Expected: the shell contract passes and existing health/security behavior stays green.

- [ ] **Step 6: Commit shared rendering**

```bash
git add materials/33/clone/ui.py materials/33/clone/static/desktop-base.css materials/33/clone/static/desktop-chrome.css materials/33/clone/app.py materials/33/clone/tests/test_desktop_contract.py
git commit -m "feat(site-33): add Coursera desktop shell"
```

### Task 3: Rebuild public catalog, discovery, and recovery pages

**Files:**
- Create: `materials/33/clone/static/catalog-desktop.css`
- Modify: `materials/33/clone/app.py`
- Modify: `materials/33/clone/catalog.py`
- Modify: `materials/33/clone/tests/test_public_frontend.py`
- Modify: `materials/33/clone/tests/test_catalog.py`
- Modify: `materials/33/clone/tests/test_desktop_contract.py`

**Interfaces:**
- Consumes: `load_catalog_seed()`, `SUBJECTS`, query filters, `ui.page`, and `ui.card`-style rendering helpers.
- Produces: Chinese source-style `/`, `/browse`, `/browse/{subject}`, and `/search` surfaces with stable `data-catalog-record` IDs.

- [ ] **Step 1: Write failing public-page tests**

```python
def test_browse_has_source_style_subject_grid_and_canonical_heading(desktop_client):
    response = desktop_client.get("/browse")
    assert "按主题浏览课程" in response.text
    assert 'href="/browse/data-science"' in response.text
    assert 'class="subject-tile-grid"' in response.text


def test_impossible_query_shows_no_match_and_recovery(desktop_client):
    html = desktop_client.get("/search?q=zzzz-no-match-websitebench").text
    assert "没有找到与“zzzz-no-match-websitebench”匹配的课程" in html
    assert "推荐课程" in html
    assert 'href="/browse"' in html


def test_catalog_filters_preserve_selected_values_and_real_result_ids(desktop_client):
    html = desktop_client.get("/search?q=Deep+Learning&level=Beginner").text
    assert 'name="level"' in html and 'value="Beginner" selected' in html
    assert 'data-catalog-record=' in html
```

- [ ] **Step 2: Run public-page tests and verify RED**

Run: `python -m pytest materials/33/clone/tests/test_public_frontend.py materials/33/clone/tests/test_catalog.py materials/33/clone/tests/test_desktop_contract.py -q`

Expected: Chinese headings, subject-grid markers, and no-match recovery assertions fail.

- [ ] **Step 3: Implement catalog presentation without weakening data semantics**

Keep record IDs, filters, sorting, and pagination behavior. Replace only the page/card rendering with Chinese headings, provider/rating/skill metadata, source-style subject tiles, filter sidebar, result cards, AI-recommendation recovery block, and explicit no-match message. Preserve canonical query parameters and all existing `data-catalog-record` attributes.

- [ ] **Step 4: Update public assets safely**

Use only selected public assets whose origin and secret scan are recorded in `materials/33/source-assets/manifest.json`. If no redistributable public asset is approved, create local geometric illustrations rather than adding an untracked source image. Ensure every stylesheet/image reference is local.

- [ ] **Step 5: Run GREEN plus offline closure checks**

Run:

```bash
python -m pytest materials/33/clone/tests/test_public_frontend.py materials/33/clone/tests/test_catalog.py materials/33/clone/tests/test_desktop_contract.py -q
python -m websitebench.offline_clone.cli verify --site materials/33
```

Expected: public behavior passes; diagnostics report no runtime remote dependency.

- [ ] **Step 6: Commit catalog rebuild**

```bash
git add materials/33/clone/app.py materials/33/clone/catalog.py materials/33/clone/static/catalog-desktop.css materials/33/clone/tests/test_public_frontend.py materials/33/clone/tests/test_catalog.py materials/33/clone/tests/test_desktop_contract.py materials/33/source-assets/manifest.json
git commit -m "feat(site-33): rebuild Chinese public catalog"
```

### Task 4: Rebuild specialization, course, preview, Help, and 404 views

**Files:**
- Create: `materials/33/clone/static/course-desktop.css`
- Modify: `materials/33/clone/app.py`
- Modify: `materials/33/clone/tests/test_public_frontend.py`
- Modify: `materials/33/clone/tests/test_source_grounding.py`
- Modify: `materials/33/clone/tests/test_desktop_contract.py`

**Interfaces:**
- Consumes: seeded Deep Learning course records and `course_outline()`.
- Produces: source-style `specialization`, `course`, `preview`, `help`, and branded 404 pages with local links.

- [ ] **Step 1: Write failing detail and recovery tests**

```python
def test_specialization_shows_observed_trial_and_course_series(desktop_client):
    html = desktop_client.get("/specializations/deep-learning").text
    assert "深度学习专项课程" in html
    assert "5 门课程系列" in html
    assert "7 天免费试用" in html
    assert "¥196/月" in html


def test_course_exposes_modules_instructors_reviews_and_preview(desktop_client):
    html = desktop_client.get("/learn/neural-networks-deep-learning").text
    assert "课程模块" in html
    assert "讲师" in html
    assert "评论" in html
    assert 'href="/learn/neural-networks-deep-learning/preview"' in html


def test_not_found_matches_observed_safe_recovery(desktop_client):
    response = desktop_client.get("/websitebench-not-found-33")
    assert response.status_code == 404
    assert "我们无法找到您要查找的页面" in response.text
    assert 'href="/browse"' in response.text
    assert 'href="/search"' in response.text
```

- [ ] **Step 2: Run detail tests and verify RED**

Run: `python -m pytest materials/33/clone/tests/test_public_frontend.py materials/33/clone/tests/test_source_grounding.py materials/33/clone/tests/test_desktop_contract.py -q`

Expected: old English/synthetic copy fails the new Chinese presentation assertions.

- [ ] **Step 3: Implement detailed course surfaces**

Render the specialization hero, provider, rating, course-series rows, trial callout, facts, FAQ, and enrollment entry. Render course hero, syllabus/module accordion with server-rendered open state, instructors, prerequisites, reviews, pricing/options, and preview CTA. Maintain all existing course IDs and preview route behavior.

- [ ] **Step 4: Implement observed Help and 404 recovery copy**

Make `/help` expose account, reset-password, course, and failed-action guidance. Make the 404 exception handler render the observed “could not find” message with catalog browse and catalog search recovery links while retaining the shared header/footer.

- [ ] **Step 5: Run GREEN**

Run: `python -m pytest materials/33/clone/tests/test_public_frontend.py materials/33/clone/tests/test_source_grounding.py materials/33/clone/tests/test_desktop_contract.py -q`

Expected: all public detail, Help, and 404 behavior remains local and passes.

- [ ] **Step 6: Commit course and recovery rebuild**

```bash
git add materials/33/clone/app.py materials/33/clone/static/course-desktop.css materials/33/clone/tests/test_public_frontend.py materials/33/clone/tests/test_source_grounding.py materials/33/clone/tests/test_desktop_contract.py
git commit -m "feat(site-33): rebuild course and recovery views"
```

### Task 5: Rebuild unified local account and learner presentation

**Files:**
- Create: `materials/33/clone/static/auth-desktop.css`
- Create: `materials/33/clone/static/learning-desktop.css`
- Modify: `materials/33/clone/app.py`
- Modify: `materials/33/clone/tests/test_learning_backend.py`
- Modify: `materials/33/clone/tests/test_desktop_contract.py`

**Interfaces:**
- Consumes: existing local auth store, `learning_state`, `get_lesson`, `submit_quiz`, enrollment/history, and preferences APIs.
- Produces: Chinese unified auth, local recovery, dashboard, lesson, quiz-feedback, history, and preferences surfaces without changing auth/store contracts.

- [ ] **Step 1: Write failing account and learning UI tests**

```python
def test_unified_auth_entry_has_email_identity_choices_and_terms(desktop_client):
    html = desktop_client.get("/login").text
    assert "登录或创建账户" in html
    assert 'type="email"' in html
    assert "继续使用 Google" in html
    assert "使用条款" in html and "隐私声明" in html


def test_recovery_requires_local_address_and_returns_to_login(desktop_client):
    html = desktop_client.get("/account-recovery").text
    assert "重置您的 Coursera 密码" in html
    assert 'type="email"' in html
    assert 'href="/login"' in html


def test_seeded_dashboard_has_resume_progress_and_history_links(desktop_client):
    login_seeded_learner(desktop_client, "progress")
    html = desktop_client.get("/my-learning").text
    assert "我的学习" in html
    assert "继续学习" in html
    assert 'href="/account/history"' in html
```

- [ ] **Step 2: Run account/learning tests and verify RED**

Run: `python -m pytest materials/33/clone/tests/test_learning_backend.py materials/33/clone/tests/test_desktop_contract.py -q`

Expected: source-style Chinese account and dashboard markers fail while existing backend semantics continue to pass.

- [ ] **Step 3: Implement auth and recovery rendering only**

Render the email-first unified card on `/login` and `/signup`, provider boundary links that remain local, terms/privacy/help links, field validation, the local registration verification step, and a password-recovery page with address validation and return link. Do not add real identity provider, mail, or source account integration.

- [ ] **Step 4: Implement learner rendering only**

Render My Learning course cards, resume controls, progress meter, lesson navigation, bookmark state, quiz feedback, review/certificate area, history status/detail/cancel links, and preferences from existing per-subject data. Keep all mutating route methods, validation, user ownership, and restart persistence unchanged.

- [ ] **Step 5: Run GREEN and isolation regression**

Run:

```bash
python -m pytest materials/33/clone/tests/test_learning_backend.py materials/33/clone/tests/test_desktop_contract.py -q
python -m pytest materials/33/clone/tests/test_smoke.py -q
```

Expected: all learner semantics and Chinese UI contracts pass.

- [ ] **Step 6: Commit auth and learner rendering**

```bash
git add materials/33/clone/app.py materials/33/clone/static/auth-desktop.css materials/33/clone/static/learning-desktop.css materials/33/clone/tests/test_learning_backend.py materials/33/clone/tests/test_desktop_contract.py
git commit -m "feat(site-33): rebuild account and learner views"
```

### Task 6: Rebuild trial checkout and add source-facing checkout alias

**Files:**
- Create: `materials/33/clone/static/checkout-desktop.css`
- Modify: `materials/33/clone/app.py`
- Modify: `materials/33/clone/backend/checkout.py`
- Modify: `materials/33/clone/tests/test_checkout_flow.py`
- Modify: `materials/33/clone/tests/test_checkout_backend.py`
- Modify: `materials/33/clone/tests/test_desktop_contract.py`

**Interfaces:**
- Consumes: `checkout.plan()`, `create_draft`, `get_draft`, `attempt`, local-sandbox scenario IDs, and per-subject orders.
- Produces: `/payments/checkout` alias plus Chinese trial plan/payment/review/result pages showing `¥196/月` and `¥0` today.

- [ ] **Step 1: Write failing checkout presentation tests**

```python
def test_checkout_plan_matches_observed_trial_price_and_total(desktop_client):
    login_seeded_learner(desktop_client, "empty")
    html = desktop_client.get("/checkout/deep-learning").text
    assert "7 天免费试用" in html
    assert "之后为 ¥196/月" in html
    assert "今日合计：¥0" in html
    assert "账单信息" in html
    assert "支付方式" in html


def test_checkout_alias_preserves_local_draft_ownership(desktop_client):
    login_seeded_learner(desktop_client, "empty")
    response = desktop_client.post("/payments/checkout", data={"plan_id": "deep-learning-specialization-paid"}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/checkout/checkout_")
```

- [ ] **Step 2: Run checkout tests and verify RED**

Run: `python -m pytest materials/33/clone/tests/test_checkout_flow.py materials/33/clone/tests/test_checkout_backend.py materials/33/clone/tests/test_desktop_contract.py -q`

Expected: old USD 49 text and missing alias behavior fail; existing safe payment-field tests remain meaningful.

- [ ] **Step 3: Update local price data without changing payment safety**

Change the clone-local Deep Learning plan snapshot to CNY `19600` minor units with zero due today and trial metadata. Update checkout totals/order snapshots and test expectations atomically. Do not add a card field `name`, persist card values, or alter the `local-sandbox` adapter.

- [ ] **Step 4: Implement source-style checkout pages and alias**

Render trial-plan callout, billing name/country controls, payment-method panel, terms acknowledgment, item summary, no-contract/cancel notice, `¥0` today total, and final action. Implement `/payments/checkout` GET/POST as a local alias that delegates to the existing authenticated checkout flow. Keep the existing `/checkout/{draft_id}/payment`, `/review`, and attempt routes for diagnostics and idempotency.

- [ ] **Step 5: Run GREEN, semantic, and network tests**

Run:

```bash
python -m pytest materials/33/clone/tests/test_checkout_flow.py materials/33/clone/tests/test_checkout_backend.py materials/33/clone/tests/test_desktop_contract.py -q
python -m websitebench.offline_clone.cli verify --site materials/33
```

Expected: source-style trial rendering passes and local-sandbox approval/decline/retry ownership remains green.

- [ ] **Step 6: Commit checkout fidelity**

```bash
git add materials/33/clone/app.py materials/33/clone/backend/checkout.py materials/33/clone/static/checkout-desktop.css materials/33/clone/tests/test_checkout_flow.py materials/33/clone/tests/test_checkout_backend.py materials/33/clone/tests/test_desktop_contract.py
git commit -m "feat(site-33): rebuild local trial checkout"
```

### Task 7: Create public visual oracles and tune desktop layout

**Files:**
- Create: `materials/33/source-evidence/home.desktop.png`
- Create: `materials/33/source-evidence/search.desktop.png`
- Create: `materials/33/source-evidence/specialization.desktop.png`
- Create: `materials/33/source-evidence/course.desktop.png`
- Create: `materials/33/source-evidence/login.desktop.png`
- Create: `materials/33/source-evidence/help.desktop.png`
- Create: `materials/33/source-evidence/not-found.desktop.png`
- Modify: `materials/33/scope/checkpoints.json`
- Modify: `materials/33/scope/coverage.json`
- Modify: `materials/33/source-assets/manifest.json`
- Create: `materials/33/clone/tests/test_desktop_visual.py`

**Interfaces:**
- Consumes: public sanitized source captures, candidate routes, and the existing `compare-visual` tool schema.
- Produces: public desktop screenshot evidence and region comparisons; never produces or commits authenticated source evidence.

- [ ] **Step 1: Create candidate screenshot assertions that initially fail**

Add Playwright tests that boot the clone at `1191 × 979`, visit `/`, `/browse`, `/search?q=Deep+Learning`, `/specializations/deep-learning`, `/learn/neural-networks-deep-learning`, `/login`, `/help`, and a missing route, and assert the desktop shell plus page-specific stable landmarks. Use screenshot snapshots only after the initial landmarks pass.

- [ ] **Step 2: Run the visual-landmark suite and verify RED**

Run: `python -m pytest materials/33/clone/tests/test_desktop_visual.py -q`

Expected: failures identify missing landmarks or dimensions before visual tuning begins.

- [ ] **Step 3: Produce evidence safely**

Render only public SingleFile captures locally in a clean browser context at `1191 × 979`; take screenshots after confirming no remote URL, Cookie, Authorization, or personal-data markers. Store only the checked public screenshots. Do not create an authenticated checkout screenshot; retain checkout facts in provenance/claims instead.

- [ ] **Step 4: Declare visual regions without turning them into gates**

Add site-specific visual contracts for each public oracle with nonzero thresholds and header/content/footer regions. Mark only directly observed public captures as `current-direct`; keep authentication and checkout as truthful simulations with their evidence limitations. Do not alter generic tool code or make diagnostics a merge condition.

- [ ] **Step 5: Tune CSS using visual diagnostics**

Run `python tools/offline_clone/run.py tools compare-visual --help`, prepare the versioned spec under the existing schema, and iterate layout, typography, spacing, borders, and local assets until the report improves without masks that hide meaningful content.

- [ ] **Step 6: Run GREEN visual-landmark and diagnostics suites**

Run:

```bash
python -m pytest materials/33/clone/tests/test_desktop_visual.py -q
python -m websitebench.offline_clone.cli verify --site materials/33
```

Expected: all source-grounded public landmarks pass; diagnostics are complete/clean or findings are captured honestly.

- [ ] **Step 7: Commit evidence and desktop tuning**

```bash
git add materials/33/source-evidence materials/33/scope/checkpoints.json materials/33/scope/coverage.json materials/33/source-assets/manifest.json materials/33/clone/tests/test_desktop_visual.py materials/33/clone/static
git commit -m "test(site-33): add public desktop visual evidence"
```

### Task 8: Full verification and human handoff

**Files:**
- Modify: `materials/33/scope/claims.jsonl`
- Modify: `materials/33/scope/coverage.json`
- Create: `materials/33/KNOWN_DIFFERENCES.md`

**Interfaces:**
- Consumes: completed routes, tests, visual reports, and the verified source limitations.
- Produces: a truthful handoff that distinguishes observed behavior, local simulation, and unavailable source evidence.

- [ ] **Step 1: Write failing honest-coverage tests**

```python
def test_known_differences_records_authenticated_source_limitations():
    text = (SITE / "KNOWN_DIFFERENCES.md").read_text(encoding="utf-8")
    assert "authenticated source" in text
    assert "not directly verified" in text


def test_scope_does_not_claim_authenticated_source_visuals_are_directly_verified():
    coverage = json.loads((SITE / "scope" / "coverage.json").read_text())
    assert "source-authenticated" not in coverage["satisfied_items"]
```

- [ ] **Step 2: Run the coverage test and verify RED if claims are stale**

Run: `python -m pytest materials/33/clone/tests/test_source_grounding.py -q`

Expected: the absent known-differences document fails first; any stale statement that
claims direct authenticated source validation is also corrected before GREEN.

- [ ] **Step 3: Update claims and known differences**

Record the observed Chinese public pages, anonymous unified auth limitation, AI recommendation behavior for the impossible query, public Help evidence, observed checkout facts without source artifact, and all intentionally local authenticated/payment simulation. Do not state that source login, source enrollment completion, source recovery submit, or source checkout submit was verified.

- [ ] **Step 4: Run required project checks**

Run:

```bash
ruff check src tests websitebench
python -m pytest tests/test_prompt_freshness.py -q
python -m pytest materials/33/clone/tests -q
python -m websitebench.offline_clone.cli verify --site materials/33
```

- [ ] **Step 5: Run optional full regression if time allows**

Run: `python -m pytest tests/project tests/offline_clone tests/harbor tests/viewer -q`

- [ ] **Step 6: Perform manual desktop replay**

At `1191 × 979`, open the source public capture beside the local clone and replay: Browse navigation, Deep Learning search and filters, no-match recovery, specialization/course/preview, unified auth/recovery/help/404, seeded dashboard/lesson/quiz/history/preferences, and checkout plan/review/decline/retry/approval. Confirm refresh and a second seeded user do not leak state.

- [ ] **Step 7: Generate the local handoff report**

Run:

```bash
websitebench-offline-clone contribution report --site materials/33 --out contribution-report.json --bundle-out contribution-handoff.zip
```

Keep the report/ZIP and running database out of Git unless a maintainer asks for a separate handoff.

- [ ] **Step 8: Commit truthful scope and handoff notes**

```bash
git add materials/33/scope/claims.jsonl materials/33/scope/coverage.json materials/33/KNOWN_DIFFERENCES.md
git commit -m "docs(site-33): record Coursera fidelity verification"
```

## Plan Self-Review

- Source-grounded Chinese desktop presentation, all human-trace surface groups, local payment safety, and known source limitations map to Tasks 1–8.
- The only schema/configuration changes are within `materials/33`; no generic hash, gate, diagnostics, deployment, or payment infrastructure changes are planned.
- Each implementation task contains a failing-test command, a minimal implementation boundary, a GREEN command, and a focused commit.
- No task authorizes source mutation beyond the already observed checkout navigation, real email, real payment, push, PR, merge, deployment, or secret persistence.
