# Coursera Live Homepage and Inline Login Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task inline. Do not dispatch subagents and do not commit.

**Goal:** Replace the rejected first-version Coursera homepage with the current `1692 × 979` source state and make login an inline same-document dialog.

**Architecture:** Retain the existing FastAPI/Jinja/backend structure, but replace the homepage view model/template/CSS with current source-backed data and add one shared, local login-dialog component to the public page shell. A small local script controls open, close, and the synthetic local second password step while the generated backend continues to own authentication.

**Tech Stack:** Python 3, FastAPI, Jinja2, generated WebsiteBench site backend, pytest, Playwright/WebsiteBench browser tools, HTML/CSS/vanilla JavaScript.

## Global Constraints

- Canonical runtime: `materials/33`.
- Sole acceptance viewport: CSS `1692 × 979`.
- Latest live Coursera homepage evidence overrides the rejected old homepage/WACZ state for `/`.
- Source exploration is GET-only and read-only.
- All runtime presentation resources are local.
- Do not invent cards, copy, links, images, or states.
- Do not commit, push, merge, or clean unrelated dirty work.
- Keep the generated backend runtime and integration seam unchanged.

---

### Task 1: Complete the current homepage evidence set

**Files:**
- Modify: `materials/33/scope/source-home-login-current-state.json`
- Create: `materials/33/source-evidence/2026-08-19-accessible-fullscreen/source-home-current-loaded.json`
- Create: `materials/33/source-evidence/2026-08-19-accessible-fullscreen/source-home-current-loaded/`

**Interfaces:**
- Consumes: the approved Coursera origins and `1692 × 979` viewport.
- Produces: one sanitized, read-only source report with every lazy homepage region visited before a final full-page screenshot.

- [ ] Add bounded `PageDown` and wait steps to the source scenario, followed by snapshots of decisive headings, card links, image sources, and the final full page.
- [ ] Run `python tools/offline_clone/run.py tools explore` with `PLAYWRIGHT_NODEJS_PATH=/usr/bin/node` and no source-mutation opt-in.
- [ ] Classify every visible record as captured, retained-current-evidence, or unresolved; do not infer missing records.

### Task 2: Lock the rejected-width regression with failing tests

**Files:**
- Modify: `materials/33/clone/tests/test_fullscreen_geometry_fidelity.py`
- Modify: `materials/33/clone/tests/test_discovery_fidelity.py`

**Interfaces:**
- Consumes: source literal shell bounds from Task 1.
- Produces: browser contracts for the `1344px` shell, compact purpose controls, and current ordered homepage sections.

- [ ] Add a browser test that launches `/` at `1692 × 979` and asserts the main homepage shell has `x≈174` and `width≈1344`, not `1151px`.
- [ ] Add content tests for the exact current section order and decisive source card/provider/image/link identities.
- [ ] Run only these tests and confirm they fail on the old `--home-shell: ...1151px` implementation and old section model.

### Task 3: Replace the old homepage with the current source-backed structure

**Files:**
- Modify: `materials/33/clone/home_page.py`
- Modify: `materials/33/clone/templates/pages/home.html`
- Modify: `materials/33/clone/static/home-prototype.css`
- Reuse/add only source-captured assets under: `materials/33/clone/static/home/`

**Interfaces:**
- Consumes: Task 1 source records and Task 2 tests.
- Produces: `render_home_body()` with the current section order and local asset paths.

- [ ] Replace the old homepage data with explicit current source records.
- [ ] Replace the old template sections with the current source order and manual carousel controls.
- [ ] Set the main source shell to `min(calc(100% - 40px), 1344px)` so it resolves to the measured `1344px` width and `174px` left edge at `1692px`, while keeping source-specific overflow regions independent.
- [ ] Implement the purpose panel as one full-width panel containing four compact, source-sized controls.
- [ ] Run Task 2 tests and repair only source-measured differences until green.

### Task 4: Lock inline-login behavior with failing tests

**Files:**
- Modify: `materials/33/clone/tests/test_desktop_contract.py`
- Modify: `materials/33/clone/tests/test_desktop_visual.py`
- Modify: `materials/33/clone/tests/test_public_frontend.py`

**Interfaces:**
- Consumes: the source report `source-home-login-current-state-v2.json`.
- Produces: contracts for same-URL opening, `role=dialog`, initial email-only state, provider choices, close, direct `/login`, and second local password step.

- [ ] Add a Playwright test that clicks header `Log In` from `/`, asserts the URL remains `/`, the homepage remains visible, one dialog is visible, one email input exists, and no password input exists.
- [ ] Add tests that close preserves `/`, direct `/login` opens the same dialog over the homepage, and continuing a valid `.test` email reveals the password step without any remote request.
- [ ] Run the focused tests and confirm they fail because the current header navigates to `/login`, the fake Neural Networks backdrop is rendered, and Password is initially present.

### Task 5: Implement the shared inline login dialog

**Files:**
- Modify: `materials/33/clone/ui.py`
- Modify: `materials/33/clone/app.py`
- Modify: `materials/33/clone/static/auth-desktop.css`
- Create: `materials/33/clone/static/auth-dialog.js`

**Interfaces:**
- Produces: `login_dialog(next_path: str, open_on_load: bool = False) -> str` in `ui.py` and local `data-login-open`, `data-login-close`, and `data-login-continue` controls.
- Preserves: `POST /auth/login` and generated backend authentication semantics.

- [ ] Render the login dialog in every public page shell and change public `Log In` from navigation to a dialog control.
- [ ] Implement local open/close behavior with no URL mutation or animation.
- [ ] Implement the initial email-only surface and create the password control only after a valid synthetic local email continues.
- [ ] Make `GET /login` render the homepage with `open_on_load=true`; retain safe `next` handling.
- [ ] Run Task 4 tests until green, then run checkout/backend login tests to ensure the generated backend seam still works.

### Task 6: Source/candidate comparison and full regression

**Files:**
- Modify only if evidence identifies a measured mismatch in the files owned by Tasks 3 or 5.

**Interfaces:**
- Consumes: the source and clone scenarios at `1692 × 979`.
- Produces: a consolidated manual-review build at `http://127.0.0.1:8044/`.

- [ ] Run the same current homepage/login Playwright scenario against source and clone and compare route, dialog, fields, providers, screenshot regions, and remote requests.
- [ ] Run focused geometry, discovery, auth, backend, and visual tests.
- [ ] Run the complete non-visual and visual site-33 suites in separate processes.
- [ ] Run remote-reference, sensitive-data, and card-like-value scans.
- [ ] Run `python tools/offline_clone/run.py verify --site materials/33` and report diagnostics as advisory.
- [ ] Restart `127.0.0.1:8044` and verify HTTP 200 before returning it for manual review.
