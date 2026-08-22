# Coursera Interaction and Backend Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every source-supported control on the reproduced Coursera pages a real local interaction with a tested route, state transition, persistence rule, or explicit safe boundary.

**Architecture:** Add a site-specific interaction audit that checks semantic markup and binds required source controls to the 23 human traces. Close behavior in five existing domains—public discovery, account, checkout, enrolled learning, and learner records—using the generated WebsiteBench backend seam for durable state and small declarative JavaScript only for transient UI state.

**Tech Stack:** Python 3.14, FastAPI/Starlette, Jinja2, SQLite, `websitebench.site_backend`, HTML/CSS/vanilla JavaScript, pytest, FastAPI TestClient, Playwright.

## Global Constraints

- Formal acceptance is the 23 traces in `materials/33/scope/human-traces.json` plus all source-supported controls on reproduced pages reachable from those traces.
- English-only UI; primary viewport `1692 x 979`; frontend similarity target at least 90 percent.
- Images may provide visual content, never the operative button, link, field, tab, menu, or switch.
- No empty link, `javascript:` URL, inert enabled button, fake success message, source-site mutation, remote dependency, real payment credential, live payment, real mail, or third-party sign-in.
- Durable enrollment, order, learning, assignment, bookmark, note, review, and preference state is owner-scoped and stored in site 33's generated backend runtime.
- Payment remains `local-sandbox` and accepts only opaque scenario IDs.
- Preserve unrelated dirty work. Do not reset, commit, push, create a PR, or deploy.
- Use focused tests during tasks; run the full site suite only at milestones.

---

### Task 1: Site-Specific Interaction Auditor

**Files:**
- Create: `materials/33/clone/interaction_contract.py`
- Create: `materials/33/clone/tests/test_interaction_contract.py`
- Create: `materials/33/scope/interaction-controls.json`
- Modify: `materials/33/scope/routes.json`

**Interfaces:**
- Produces: `audit_markup(html: str, *, route: str) -> tuple[InteractionFinding, ...]`
- Produces: `load_control_contract(path: Path) -> tuple[ControlContract, ...]`
- Produces: JSON entries with `id`, `route`, `selector`, `behavior`, `target`, `persistence`, `trace_ids`, and `evidence_refs`.
- Behavior values: `navigate`, `submit`, `client-state`, `durable-state`, `safe-boundary`.

- [ ] **Step 1: Write unit tests for semantic interaction failures**

```python
def test_auditor_rejects_inert_controls_and_accepts_explicit_boundaries():
    broken = '<a href="#">Open</a><button type="button">Save</button>'
    assert {item.code for item in audit_markup(broken, route="/")} == {
        "placeholder-link", "inert-button"
    }

    valid = (
        '<form action="/prefs" method="post"><button type="submit">Save</button></form>'
        '<button type="button" disabled aria-describedby="why">Verify</button>'
        '<p id="why">Unavailable offline.</p>'
    )
    assert audit_markup(valid, route="/") == ()
```

- [ ] **Step 2: Run the focused test and observe the missing-module failure**

Run: `python -m pytest materials/33/clone/tests/test_interaction_contract.py -q`  
Expected: FAIL because `interaction_contract` does not exist.

- [ ] **Step 3: Implement the standard-library HTML audit**

```python
@dataclass(frozen=True)
class InteractionFinding:
    route: str
    code: str
    label: str

def audit_markup(html: str, *, route: str) -> tuple[InteractionFinding, ...]:
    parser = _InteractionParser(route)
    parser.feed(html)
    parser.close()
    return tuple(parser.findings)
```

The parser must reject empty/hash/`javascript:` links; enabled `type=button`
controls without `data-control-action`; submit buttons outside a local-action
form; image-map controls; and disabled controls without a valid
`aria-describedby` explanation. It must allow anchors containing card images
when the anchor has a local `href` and an accessible name.

- [ ] **Step 4: Add and validate the control-contract loader**

```python
@dataclass(frozen=True)
class ControlContract:
    id: str
    route: str
    selector: str
    behavior: str
    target: str
    persistence: str
    trace_ids: tuple[str, ...]
    evidence_refs: tuple[str, ...]
```

Reject duplicate IDs, unknown behavior values, missing selectors, non-local
targets, unknown `trace-001` through `trace-023` bindings, and empty evidence
references. Seed `interaction-controls.json` with header/login/search, public
enrollment, checkout, My Learning, assignment, preferences, support, and 404
controls already required by the trace files. Add purchases, settings, updates,
orders, enrolled-course, and assignment routes to `scope/routes.json`.

- [ ] **Step 5: Run Task 1 tests**

Run: `python -m pytest materials/33/clone/tests/test_interaction_contract.py materials/33/clone/tests/test_current_phase_matrix.py -q`  
Expected: PASS.

---

### Task 2: Public Discovery Controls

**Files:**
- Modify: `materials/33/clone/templates/pages/home.html`
- Modify: `materials/33/clone/home_page.py:13-67`
- Modify: `materials/33/clone/ui.py:11-116`
- Modify: `materials/33/clone/search_page.py:237-end`
- Modify: `materials/33/clone/business_category.py:339-end`
- Create: `materials/33/clone/static/public-interactions.js`
- Modify: `materials/33/clone/app.py:783-964`
- Modify: `materials/33/scope/interaction-controls.json`
- Create: `materials/33/clone/tests/test_public_control_closure.py`

**Interfaces:**
- Client actions: `switch-promo`, `switch-collection`, `toggle-faq`, `open-login`.
- Server destinations remain local and canonical: `/browse`, `/browse/{category}`,
  `/search`, `/specializations/deep-learning`, `/learn/{course_id}`, `/help`, and
  explicit local landing aliases for source-linked partner/career paths.

- [ ] **Step 1: Write browser failures for the current inert public controls**

```python
def test_home_tabs_and_promo_controls_change_real_visible_content(page, base_url):
    page.goto(base_url + "/")
    page.get_by_role("button", name="Bestsellers").click()
    assert page.locator("[data-collection-panel]:visible").get_attribute("data-key") == "bestsellers"
    before = page.locator("[data-promo-panel]:visible img").get_attribute("src")
    page.get_by_role("button", name="Next promotion").click()
    assert page.locator("[data-promo-panel]:visible img").get_attribute("src") != before
```

Add tests that every public anchor resolves locally without 404/405, filters
change result IDs, FAQ buttons update `aria-expanded`, and Log In preserves the
invoking document.

- [ ] **Step 2: Run the public-control tests and observe the missing behavior**

Run: `python -m pytest materials/33/clone/tests/test_public_control_closure.py -q`  
Expected: FAIL on the first currently inert tab, switch, or missing local target.

- [ ] **Step 3: Replace visual-only labels with semantic controls**

```html
<button type="button" data-control-action="switch-collection"
        data-collection-target="bestsellers" aria-selected="false">
  Bestsellers
</button>
```

Keep images as child media only. Each card keeps a real local anchor. Add
accessible previous/next buttons to the source-backed promotional switch where
the original page exposes switching.

- [ ] **Step 4: Implement declarative transient behavior**

```javascript
document.addEventListener("click", (event) => {
  const control = event.target.closest("[data-control-action]");
  if (!control) return;
  if (control.dataset.controlAction === "switch-collection") {
    activateCollection(control.dataset.collectionTarget);
  }
});
```

The active button must update `aria-selected`; the active panel must become the
only visible panel; navigation/search/filter actions remain browser-native GETs.

- [ ] **Step 5: Add real local destinations for currently exposed source links**

Use the existing catalog and category renderers to serve source-path aliases for
Coursera Plus, teams, careers, degrees, and partner/provider collections. Each
alias must show a heading, matching local records, and a route back to Browse;
it must not be a generic fake-success page.

- [ ] **Step 6: Run public discovery regressions**

Run: `python -m pytest materials/33/clone/tests/test_public_control_closure.py materials/33/clone/tests/test_anonymous_journey_matrix.py materials/33/clone/tests/test_search_interactions_fidelity.py materials/33/clone/tests/test_live_home_inline_login_contract.py -q`  
Expected: PASS, except no pre-existing visual-threshold test is included here.

---

### Task 3: Account, Login, Onboarding, Settings, and Updates Controls

**Files:**
- Modify: `materials/33/clone/static/auth-dialog.js`
- Modify: `materials/33/clone/ui.py:11-70`
- Modify: `materials/33/clone/app.py:1205-1671`
- Modify: `materials/33/clone/backend/learning_db.py:231-281,611-664`
- Modify: `materials/33/scope/interaction-controls.json`
- Create: `materials/33/clone/tests/test_account_control_closure.py`

**Interfaces:**
- Existing generated-auth routes remain authoritative.
- Add owner-scoped setters only for source-visible settings and update
  preferences: `update_account_settings(subject_id, *, display_name, timezone)`
  and `update_update_preferences(subject_id, *, product_updates, course_updates)`.

- [ ] **Step 1: Write failures for complete account control journeys**

```python
def test_account_settings_persist_for_only_the_signed_in_owner(site_client):
    login(site_client, "progress@coursera.test", "Progress-Learner-33")
    saved = site_client.post(
        "/account-settings",
        data={"display_name": "Progress Learner", "timezone": "Asia/Shanghai"},
        follow_redirects=False,
    )
    assert saved.status_code == 303
    assert "Asia/Shanghai" in site_client.get("/account-settings").text
```

Also cover invalid input, safe `next`, modal close, email-to-password transition,
registration verification, local recovery, logout, provider boundaries, updates
preference persistence, relogin, and a second owner seeing their own defaults.

- [ ] **Step 2: Run and observe missing POST routes or persistence**

Run: `python -m pytest materials/33/clone/tests/test_account_control_closure.py -q`  
Expected: FAIL because one or more settings/update controls are display-only.

- [ ] **Step 3: Add the minimum owner-scoped schema and functions**

```sql
CREATE TABLE IF NOT EXISTS coursera_update_preferences (
  owner_subject_id TEXT PRIMARY KEY,
  product_updates INTEGER NOT NULL CHECK(product_updates IN (0,1)),
  course_updates INTEGER NOT NULL CHECK(course_updates IN (0,1)),
  updated_at TEXT NOT NULL
)
```

Reuse `coursera_profiles` and `coursera_preferences` for name/timezone. Keep the
migration idempotent and bound to site 33's existing database connection.

- [ ] **Step 4: Render real forms and POST handlers**

```python
@app.post("/updates")
async def save_updates(request: Request) -> Response:
    subject = _authenticated_subject(request)
    values = await _form_values(request)
    learning_db.update_update_preferences(
        subject, product_updates="product_updates" in values,
        course_updates="course_updates" in values,
    )
    return RedirectResponse("/updates?saved=1", status_code=303)
```

Use inline validation for invalid names/timezones. Provider buttons continue to
open explicit local boundaries rather than external identity services.

- [ ] **Step 5: Run account and generated-backend tests**

Run: `python -m pytest materials/33/clone/tests/test_account_control_closure.py materials/33/clone/tests/test_learning_backend.py -q`  
Expected: PASS.

---

### Task 4: Enrollment, Checkout, Orders, and Cancellation Controls

**Files:**
- Modify: `materials/33/clone/app.py:939-1139,1672-1806`
- Modify: `materials/33/clone/backend/checkout.py`
- Modify: `materials/33/clone/backend/learning_db.py:282-400`
- Modify: `materials/33/scope/interaction-controls.json`
- Modify: `materials/33/clone/tests/test_checkout_backend.py`
- Modify: `materials/33/clone/tests/test_checkout_flow.py`
- Create: `materials/33/clone/tests/test_enrollment_control_closure.py`

**Interfaces:**
- Existing `enroll`, `cancel_enrollment`, checkout draft, sandbox attempt, order
  list/detail, and cancel operations remain the domain seam.
- Browser payment fields are presentation-only and must never be submitted.
- POST payload accepts canonical plan/track and opaque sandbox scenario only.

- [ ] **Step 1: Add failing end-to-end tests for every exposed checkout control**

```python
def test_paid_track_reaches_server_owned_review_without_payment_values(client):
    login_seeded(client)
    draft = client.post(
        "/checkout/deep-learning",
        data={"plan": "specialization-monthly"},
        follow_redirects=False,
    )
    assert draft.status_code == 303
    payment = client.get(draft.headers["location"])
    assert "Payment method" in payment.text
    review_path = extract_review_path(payment.text)
    review = client.get(review_path)
    assert "¥0 due today" in review.text
    assert "7-day free trial" in review.text
```

Add free/audit enrollment, signed-out return, required-field validation,
tampered price rejection, foreign-owner rejection, approval, decline, retry,
idempotent duplicate, order detail, cancellation, repeated cancellation, and
return-to-collection cases.

- [ ] **Step 2: Run the checkout/enrollment tests and observe the first missing behavior**

Run: `python -m pytest materials/33/clone/tests/test_checkout_backend.py materials/33/clone/tests/test_checkout_flow.py materials/33/clone/tests/test_enrollment_control_closure.py -q`  
Expected: FAIL on an exposed control that lacks a complete server result.

- [ ] **Step 3: Make every plan and enrollment CTA a real form or local route**

```html
<form action="/checkout/deep-learning" method="post">
  <input type="hidden" name="plan" value="specialization-monthly">
  <button type="submit">Start free trial</button>
</form>
```

Free and audit use `/enrollments`; paid uses the checkout draft. No enabled CTA
may link directly to a success page.

- [ ] **Step 4: Enforce server-owned state and idempotency**

```python
if submitted_total is not None:
    raise CheckoutValidation("Client-provided totals are not accepted")
result = checkout.attempt(
    owner_subject_id=subject,
    draft_id=draft_id,
    scenario_id=scenario_id,
    idempotency_key=idempotency_key,
)
```

Approval writes order and enrollment atomically; decline/retry write no paid
enrollment; cancel acts only on the authenticated owner's current record.

- [ ] **Step 5: Run enrollment and checkout regressions**

Run: `python -m pytest materials/33/clone/tests/test_checkout_backend.py materials/33/clone/tests/test_checkout_flow.py materials/33/clone/tests/test_enrollment_control_closure.py materials/33/clone/tests/test_learning_backend.py -q`  
Expected: PASS.

---

### Task 5: Enrolled Course, Lesson, Notes, Reactions, and Assignment Controls

**Files:**
- Modify: `materials/33/clone/enrolled_page.py:19-176`
- Modify: `materials/33/clone/static/assignment.js`
- Create: `materials/33/clone/static/enrolled-interactions.js`
- Modify: `materials/33/clone/backend/learning_db.py:401-610`
- Modify: `materials/33/clone/app.py:1807-2273`
- Modify: `materials/33/scope/interaction-controls.json`
- Create: `materials/33/clone/tests/test_enrolled_control_closure.py`
- Modify: `materials/33/clone/tests/test_assignment_backend.py`
- Modify: `materials/33/clone/tests/test_assignment_flow.py`

**Interfaces:**
- Add `set_weekly_target(subject_id: str, minutes: int) -> None`.
- Add `set_lesson_reaction(subject_id: str, lesson_id: str, reaction: str | None) -> None`.
- Add `report_lesson_issue(subject_id: str, lesson_id: str, reason: str) -> int` returning a local issue ID.
- Existing note, bookmark, progress, quiz, assignment draft, timer, submit, score,
  and feedback interfaces remain authoritative.

- [ ] **Step 1: Write browser and backend tests for known inert course controls**

```python
def test_learning_objectives_tabs_player_and_weekly_target_are_operable(page, enrolled_url):
    page.goto(enrolled_url + "/home/module/1")
    page.get_by_role("button", name="Show Learning Objectives").click()
    assert page.get_by_role("region", name="Learning Objectives").is_visible()
    page.get_by_role("button", name="Set your weekly learning target").click()
    page.get_by_label("Minutes per week").fill("90")
    page.get_by_role("button", name="Save target").click()
    assert page.get_by_text("90 minutes per week").is_visible()
```

Also test More options, play/pause, Transcript/Notes/Files, Like/Dislike,
Report an issue, note deletion, search/filter notes, next/previous unit,
bookmark/progress, assignment start/draft/submit/result, timeout, attempt limit,
foreign-owner result, and relogin persistence.

- [ ] **Step 2: Run focused tests and verify failure on the current inert controls**

Run: `python -m pytest materials/33/clone/tests/test_enrolled_control_closure.py -q`  
Expected: FAIL on Show Learning Objectives or the next inert control.

- [ ] **Step 3: Add owner-scoped durable tables**

```sql
CREATE TABLE IF NOT EXISTS coursera_weekly_targets (
  owner_subject_id TEXT PRIMARY KEY,
  minutes INTEGER NOT NULL CHECK(minutes BETWEEN 15 AND 1200),
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS coursera_lesson_reactions (
  owner_subject_id TEXT NOT NULL,
  lesson_id TEXT NOT NULL,
  reaction TEXT NOT NULL CHECK(reaction IN ('like','dislike')),
  updated_at TEXT NOT NULL,
  PRIMARY KEY(owner_subject_id, lesson_id)
)
```

Add a local issue table with owner, lesson, reason, and timestamp. Migrations and
seeds remain idempotent.

- [ ] **Step 4: Replace inert buttons with real disclosure, forms, and routes**

```html
<button type="button" data-control-action="toggle-objectives"
        aria-expanded="false" aria-controls="learning-objectives">
  Show Learning Objectives
</button>
<section id="learning-objectives" aria-label="Learning Objectives" hidden>...</section>
```

The local player exposes play/pause and deterministic elapsed state without
claiming remote video playback. Transcript, Notes, and Files reveal real local
content. Reaction, issue, and weekly-target forms POST owner-scoped state.

- [ ] **Step 5: Preserve the existing assignment guarantees**

Keep server timer, honor-code requirement, answer validation, draft ownership,
single submission, local scoring disclosure, per-question feedback, attempt
limits, timeout submission, grade update, and restart persistence. Do not put the
answer key into browser JavaScript.

- [ ] **Step 6: Run the complete enrolled-learning slice**

Run: `python -m pytest materials/33/clone/tests/test_enrolled_control_closure.py materials/33/clone/tests/test_enrolled_learning_browser.py materials/33/clone/tests/test_assignment_backend.py materials/33/clone/tests/test_assignment_flow.py -q`  
Expected: PASS.

---

### Task 6: Purchases, Preferences, Completion, Certificate, and Review Controls

**Files:**
- Modify: `materials/33/clone/app.py:1410-1806,2151-2311`
- Modify: `materials/33/clone/enrolled_page.py:19-43`
- Modify: `materials/33/clone/backend/learning_db.py:539-664`
- Modify: `materials/33/scope/interaction-controls.json`
- Create: `materials/33/clone/tests/test_learner_record_control_closure.py`

**Interfaces:**
- Add `completion_state(subject_id: str) -> dict[str, object]` derived from stored
  module/lesson/assignment state.
- Existing `upsert_review`, `get_review`, `update_preferences`, enrollment
  history, order history, and cancellation functions remain authoritative.

- [ ] **Step 1: Write failures for every exposed record and preference action**

```python
def test_preferences_review_and_completion_are_owner_scoped(site_client):
    login_progress(site_client)
    assert site_client.post(
        "/account/preferences",
        data={"language": "English", "timezone": "Asia/Shanghai", "email_updates": "on"},
        follow_redirects=False,
    ).status_code == 303
    assert site_client.post(
        "/learning/review", data={"rating": "5", "review_text": "Useful local course"},
        follow_redirects=False,
    ).status_code == 303
    assert "Useful local course" in site_client.get("/account/preferences").text
```

Cover purchases lower-page links, enrollment/order detail, edit/cancel routes,
invalid rating, certificate not-yet-earned boundary, earned completion state,
and second-owner isolation.

- [ ] **Step 2: Run and observe incomplete controls**

Run: `python -m pytest materials/33/clone/tests/test_learner_record_control_closure.py -q`  
Expected: FAIL on the first display-only purchases, completion, or preference action.

- [ ] **Step 3: Derive completion server-side and render real controls**

```python
def completion_state(subject_id: str) -> dict[str, object]:
    state = learning_state(subject_id)
    required = len(state["lessons"])
    completed = sum(1 for lesson in state["lessons"] if lesson["completed"])
    return {"completed": completed == required and required > 0,
            "completed_lessons": completed, "required_lessons": required}
```

Certificate verification remains an explicit disabled boundary until completion
and identity evidence exist. Rating/review is a real clone-local form and must be
labeled local; cancellation is a real owner-scoped POST with confirmation.

- [ ] **Step 4: Ensure purchases recommendations link to real local results**

`Get started with these free courses`, degree, certificate, and related cards
must use catalog entity IDs and real local detail/search destinations. No card
may be a background image pretending to be a clickable unit.

- [ ] **Step 5: Run record and preference regressions**

Run: `python -m pytest materials/33/clone/tests/test_learner_record_control_closure.py materials/33/clone/tests/test_authenticated_empty_surfaces.py materials/33/clone/tests/test_learning_backend.py -q`  
Expected: PASS.

---

### Task 7: Full Reachable-Control Browser Audit and 23-Trace Binding

**Files:**
- Create: `materials/33/clone/tests/test_reachable_control_matrix.py`
- Create: `materials/33/scope/interaction-trace-bindings.json`
- Modify: `materials/33/scope/interaction-controls.json`
- Modify: `materials/33/scope/coverage.json`
- Modify: `materials/33/KNOWN_DIFFERENCES.md`

**Interfaces:**
- The browser matrix consumes `interaction-controls.json` and asserts each
  selector is visible in its declared state and produces the declared result.
- Trace bindings contain `trace_id`, ordered `control_ids`, `routes`,
  `state_assertions`, and `evidence_classification`.

- [ ] **Step 1: Write the matrix test before completing bindings**

```python
@pytest.mark.parametrize("contract", load_browser_contracts())
def test_declared_control_has_observable_result(page, base_url, contract):
    enter_declared_state(page, base_url, contract)
    control = page.locator(contract.selector)
    assert control.is_visible()
    operate_and_assert(page, contract)
```

The helper must assert a URL change, visible state change, server validation,
durable reload result, or accessible safe-boundary explanation according to the
declared behavior. Merely receiving a click event is not an observable result.

- [ ] **Step 2: Run the matrix and collect the exact remaining failures**

Run: `python -m pytest materials/33/clone/tests/test_reachable_control_matrix.py -q`  
Expected: FAIL with named control IDs until every reachable control is bound.

- [ ] **Step 3: Close only the reported gaps in their owning domain**

For each failure, first add or refine the domain-specific failing test, then make
the minimum production change. Do not weaken the matrix, delete a source-backed
control, or classify an inert control as a boundary merely to pass.

- [ ] **Step 4: Bind all 23 traces**

```json
{
  "trace_id": "trace-012",
  "control_ids": ["course.assignment.open", "assignment.start", "assignment.submit"],
  "routes": ["/my-learning", "/learn/neural-networks-deep-learning/assignment-submission/3KFZW/introduction-to-deep-learning"],
  "state_assertions": ["attempt persisted", "score visible", "feedback visible"],
  "evidence_classification": "source-structure-plus-clone-local-scoring"
}
```

Every `trace-001` through `trace-023` must occur exactly once. Record source-
observed, inferred, and clone-local behavior honestly.

- [ ] **Step 5: Run the interaction milestone suite**

Run: `python -m pytest materials/33/clone/tests -q --ignore=materials/33/clone/tests/test_desktop_visual.py`  
Expected: PASS with no interaction, backend, or browser failures.

---

### Task 8: Visual Pass, Diagnostics, and Handoff Evidence

**Files:**
- Modify only if required: `materials/33/clone/static/*.css`
- Modify: `materials/33/KNOWN_DIFFERENCES.md`
- Modify: `materials/33/scope/verify.json`

**Interfaces:**
- No new product behavior. This task verifies the completed contract and records
  current evidence.

- [ ] **Step 1: Run the current full site test suite**

Run: `python -m pytest materials/33/clone/tests -q`  
Expected: all functional tests pass; record any pre-existing visual threshold
failure exactly rather than hiding it.

- [ ] **Step 2: Run focused fullscreen browser checks**

At `1692 x 979`, verify home, browse, search, specialization, course, login
overlay, checkout, My Learning, enrolled course, assignment, purchases, settings,
updates, help, and 404. Assert no unexpected remote requests, failed local
requests, console errors, horizontal overflow, or inaccessible enabled controls.

- [ ] **Step 3: Apply one consolidated visual correction pass if needed**

Write a failing geometry or visual-region test before each CSS change. Modify
only layout that materially blocks the 90-percent target or control usability;
do not reopen card-content exploration that already has source evidence.

- [ ] **Step 4: Run WebsiteBench diagnostics**

Run: `python -m websitebench.offline_clone.cli verify --site materials/33`  
Expected: report `clean`, `findings`, or the already-understood Harbor sandbox
`incomplete`; diagnostics remain advisory and must be reported honestly.

- [ ] **Step 5: Report backend identity and safety profile**

Read `materials/33/backend/runtime.json` and report runtime path, unique site ID,
SQLite database/volume identity, mail purposes, `local-sandbox` payment profile,
deployment profile, test totals, diagnostic status, and remaining known
differences. Confirm no credential, cookie, token, payment value, browser profile,
real user data, commit, push, PR, or deployment was produced.
