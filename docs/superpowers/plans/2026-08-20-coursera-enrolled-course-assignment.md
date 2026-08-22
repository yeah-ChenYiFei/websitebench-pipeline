# Coursera Enrolled Course and Assignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a source-grounded, English-only enrolled `Neural Networks and Deep Learning` learner journey with persistent notes, progress, a ten-question timed assignment, local scoring, grades, and feedback to the existing site-33 clone.

**Architecture:** Keep FastAPI route handlers thin. Put immutable source presentation data and private clone-local scoring rules in `enrolled_course.py`, owner-scoped SQLite operations in `backend/assignment_db.py`, and HTML renderers in `enrolled_page.py`. Existing WebsiteBench `backend/runtime.json` and `backend.learning_db:migrate/seed` remain the only backend and migration seam.

**Tech Stack:** Python 3, FastAPI/Starlette, SQLite, generated `websitebench.site_backend`, server-rendered HTML, CSS, minimal vanilla JavaScript, pytest, and Playwright-compatible WebsiteBench diagnostics.

## Global Constraints

- Work in `materials/33` and preserve all unrelated dirty changes; do not create a second clone or backend.
- Do not commit.
- English-only UI at the acceptance viewport `1692 × 979` CSS pixels.
- Source authority is sanitized evidence under `materials/33/source-evidence/2026-08-20-enrolled-learning/`.
- Never persist credentials, cookies, entered legal names, answer keys, or sensitive form values in evidence, logs, or screenshots.
- Do not contact Coursera, send mail, perform identity verification, submit a source assignment, or use real payment data.
- The answer key and feedback are clone-local/course-knowledge-derived and must never be presented as source-verified.
- All learner data is owner-scoped in the site-33 SQLite opened through the existing generated backend seam.
- Continue using `materials/33/backend/runtime.json` with site ID `33`, database `33.sqlite3`, payment profile `local-sandbox`, and existing mail purposes only; this work adds no mail or payment effects.
- Follow red-green-refactor for every behavior. A test must fail for the intended missing behavior before production code is added.

---

### Task 1: Source-grounded course and assignment domain data

**Files:**
- Create: `materials/33/clone/enrolled_course.py`
- Create: `materials/33/clone/tests/test_enrolled_learning_source_fidelity.py`
- Read: `materials/33/source-evidence/2026-08-20-enrolled-learning/assignment-questions-en.json`
- Read: `materials/33/source-evidence/2026-08-20-enrolled-learning/enrolled-learning-en.json`

**Interfaces:**
- Produces: `COURSE_ID`, `ASSIGNMENT_ID`, `ASSIGNMENT_SLUG`, `PROGRAM`, `COURSE`, `MODULES`, `LESSON`, `RESOURCES`, and `QUESTIONS` immutable presentation data.
- Produces: `question_by_number(number: int) -> dict[str, object]` and `validate_answers(raw: Mapping[int, Sequence[int]], *, require_complete: bool) -> dict[int, tuple[int, ...]]`.
- Produces: private `_ANSWER_KEY: dict[int, tuple[int, ...]]` and `score_answers(answers: Mapping[int, Sequence[int]]) -> list[dict[str, object]]`; only the scorer can consume `_ANSWER_KEY`.

- [ ] **Step 1: Write failing source-data tests**

  Assert literal observed identities: five-course Deep Learning program, four module navigation entries, assignment `3KFZW`, 50-minute duration, ten questions totaling ten points, exact prompt and option order, and the seven local assignment image paths. Assert malformed question numbers, duplicate options, and out-of-range options raise `ValueError`.

- [ ] **Step 2: Run the source-data tests and verify RED**

  Run: `cd materials/33/clone && pytest -q tests/test_enrolled_learning_source_fidelity.py`

  Expected: collection/import failure because `enrolled_course.py` does not exist.

- [ ] **Step 3: Implement immutable presentation data and validation**

  Load no source JSON at request time. Transcribe the sanitized evidence into immutable tuples/dicts, copy the seven evidence diagrams into a local static assignment directory in Task 5, normalize selection indexes to sorted unique integer tuples, require exactly one selection for single-choice questions, allow one or more for multiple-choice questions, and reject unknown question/option IDs.

- [ ] **Step 4: Add private local scoring rules**

  Keep the key server-side only. Return per-question records with `question_number`, `selected`, `correct`, `points_awarded`, and concise course-knowledge feedback. Add `ANSWER_KEY_PROVENANCE = "clone-local-course-knowledge-derived"` for result disclosure; do not expose `_ANSWER_KEY` from any pre-submit renderer or JSON.

- [ ] **Step 5: Run tests and verify GREEN**

  Run: `cd materials/33/clone && pytest -q tests/test_enrolled_learning_source_fidelity.py`

---

### Task 2: Owner-scoped enrolled state, notes, and attempts

**Files:**
- Create: `materials/33/clone/backend/assignment_db.py`
- Create: `materials/33/clone/tests/test_assignment_backend.py`
- Modify: `materials/33/clone/backend/learning_db.py`

**Interfaces:**
- Produces: `migrate(connection: sqlite3.Connection) -> None` and `seed(connection: sqlite3.Connection) -> None` called by `learning_db` hooks.
- Produces: `course_access(subject_id: str) -> dict[str, object]`, `mark_lesson_opened(subject_id: str) -> None`, `save_note(subject_id: str, text: str) -> dict[str, object]`, `list_notes(subject_id: str, query: str = "") -> list[dict[str, object]]`, and `delete_note(subject_id: str, note_id: int) -> None`.
- Produces: `start_or_resume_attempt(subject_id: str, now: datetime | None = None) -> dict[str, object]`, `get_attempt(subject_id: str, attempt_id: str, now: datetime | None = None) -> dict[str, object]`, `save_draft(subject_id: str, attempt_id: str, answers: Mapping[int, Sequence[int]], now: datetime | None = None) -> dict[str, object]`, and `submit_attempt(subject_id: str, attempt_id: str, answers: Mapping[int, Sequence[int]], legal_name: str, now: datetime | None = None) -> dict[str, object]`.
- Produces: `gradebook(subject_id: str) -> list[dict[str, object]]`.

- [ ] **Step 1: Write failing migration and isolation tests**

  Test repeatable migration, deterministic enrolled seed for `learner-in-progress`, no enrolled seed for `learner-empty`, owner-only notes/attempts, a stable resumed attempt ID, and persistence across `close_services()`/reopen. Use a temporary site-33 database through `WEBSITEBENCH_SITE_BACKEND_DATABASE`, not a direct ad-hoc SQLite path.

- [ ] **Step 2: Run the focused backend tests and verify RED**

  Run: `cd materials/33/clone && pytest -q tests/test_assignment_backend.py`

  Expected: import failure for `backend.assignment_db`.

- [ ] **Step 3: Add repeatable schema and seed integration**

  Add owner-scoped tables for course state, notes, attempts, attempt drafts, and immutable result snapshots. Use foreign keys/unique constraints for subject/course/assignment ownership. Call `assignment_db.migrate(connection)` from `learning_db.migrate` and `assignment_db.seed(connection)` from `learning_db.seed`; keep `backend/runtime.json` unchanged.

- [ ] **Step 4: Implement notes and course state**

  Require an active `deep-learning-specialization` enrollment for every enrolled operation. Trim note text, reject empty or oversized notes, update lesson resume state when the welcome lesson opens, and ensure note list/delete queries always include `subject_id`.

- [ ] **Step 5: Implement attempt lifecycle and draft persistence**

  Generate opaque local attempt IDs, store server `started_at`/`expires_at`, resume the sole current in-progress attempt, validate all answers with `enrolled_course.validate_answers`, and store normalized draft JSON. Derive remaining seconds from server time. On read or mutation after expiry, atomically auto-submit the current draft and return the immutable result.

- [ ] **Step 6: Run lifecycle tests and verify GREEN**

  Run: `cd materials/33/clone && pytest -q tests/test_assignment_backend.py -k 'migration or owner or note or start or draft or expiry'`

---

### Task 3: Authoritative scoring, name confirmation, grades, and attempt limits

**Files:**
- Modify: `materials/33/clone/backend/assignment_db.py`
- Modify: `materials/33/clone/tests/test_assignment_backend.py`
- Modify: `materials/33/clone/backend/learning_db.py`

**Interfaces:**
- Consumes: `enrolled_course.score_answers` and the APIs created in Task 2.
- Produces: immutable submitted result dictionaries containing `attempt_id`, `status`, `submitted_at`, `score`, `max_score`, `percentage`, `passed`, `provenance`, and per-question feedback snapshots.

- [ ] **Step 1: Write failing submission tests**

  Cover incomplete answers, forged question/option IDs, legal-name mismatch after Unicode whitespace normalization, foreign-owner attempts, a correct ten-point submission, a partially correct submission, duplicate submit returning the same immutable result, gradebook update, two subsequent attempts, and a 24-hour wait after the attempt allowance is exhausted.

- [ ] **Step 2: Run submission tests and verify RED**

  Run: `cd materials/33/clone && pytest -q tests/test_assignment_backend.py -k 'submit or score or grade or limit'`

  Expected: failures because submission scoring and limit enforcement are absent.

- [ ] **Step 3: Implement transactional submission**

  Within one `BEGIN IMMEDIATE` transaction: verify ownership/status/time, normalize and compare the entered name to `coursera_profiles.display_name` without persisting the entered value, require complete valid answers, score on the server, insert immutable question/answer/feedback snapshots, mark the attempt submitted, and update course progress/grade state. Never log answer payloads or names.

- [ ] **Step 4: Implement idempotency and attempt limits**

  A repeated submit for an already submitted owner attempt returns its stored snapshot without rescoring. Permit the observed initial attempt plus two remaining attempts, then set `available_after` 24 hours from the latest submission. Return typed `ValueError`/`LookupError` boundaries without revealing whether a foreign attempt exists.

- [ ] **Step 5: Run all assignment backend tests and verify GREEN**

  Run: `cd materials/33/clone && pytest -q tests/test_assignment_backend.py`

---

### Task 4: Source-shaped enrolled HTML renderers

**Files:**
- Create: `materials/33/clone/enrolled_page.py`
- Create: `materials/33/clone/tests/test_assignment_flow.py`
- Modify: `materials/33/clone/tests/test_authenticated_empty_surfaces.py`

**Interfaces:**
- Produces renderers: `render_my_learning_enrolled(state)`, `render_course_home(state, week)`, `render_lesson(state)`, `render_grades(rows)`, `render_notes(notes, query)`, `render_messages()`, `render_resources(resource_id)`, `render_course_info()`, `render_assignment_entry(state)`, `render_assignment_attempt(attempt)`, and `render_assignment_result(result)` returning trusted server-generated HTML strings.

- [ ] **Step 1: Write failing route-content tests against the planned URLs**

  Sign in through `/auth/learning-demo`. Assert source-observed English headings/navigation for In Progress, Completed, Certificates, module 1, Welcome lesson, Grades, Notes, Messages, Resources, Course Info, assignment entry, attempt, and result. Assert the empty learner receives an enrollment prompt and a signed-out learner receives inline sign-in with a preserved safe `next` URL.

- [ ] **Step 2: Run flow tests and verify RED**

  Run: `cd materials/33/clone && pytest -q tests/test_assignment_flow.py tests/test_authenticated_empty_surfaces.py`

  Expected: new enrolled URLs return 404 or lack observed content.

- [ ] **Step 3: Implement reusable enrolled shell and content renderers**

  Reproduce the observed course header/sidebar, week navigation, content column, source copy, empty states, course timeline, and safe local-only video poster. Escape all profile, note, query, attempt, and feedback values. Do not add unobserved messaging, rating, cancellation, or external identity controls.

- [ ] **Step 4: Implement question and result renderers without key leakage**

  Use radio controls for single-choice, checkbox controls for multiple-choice, and local images for diagram/image-choice questions. Name fields `q_<number>` and render saved selections only. Render the legal-name confirmation on submit. The pre-submit HTML and `/static/assignment.js` must contain no correct-option indices or feedback; the result renderer may show stored per-question correctness and the clone-local provenance notice.

- [ ] **Step 5: Run renderer/flow tests and verify GREEN**

  Run: `cd materials/33/clone && pytest -q tests/test_assignment_flow.py tests/test_authenticated_empty_surfaces.py`

---

### Task 5: Thin FastAPI routes and POST/Redirect/GET mutations

**Files:**
- Modify: `materials/33/clone/app.py`
- Modify: `materials/33/clone/tests/test_assignment_flow.py`
- Create: `materials/33/clone/static/assignment.js`
- Copy: `materials/33/source-evidence/2026-08-20-enrolled-learning/screenshots/assignment-assets/*` to `materials/33/clone/static/enrolled/assignment/`

**Interfaces:**
- Consumes: renderers from Task 4 and database APIs from Tasks 2–3.
- Produces the authenticated GET/POST route model defined in the approved design, including safe redirects and status-specific validation views.

- [ ] **Step 1: Write failing interaction tests**

  Test canonical `myLearningTab` values, `/home/welcome` redirect, valid weeks/resources only, honor-code requirement, start/resume, checkbox multi-value parsing, save-draft PRG, submit PRG, result ownership, duplicate submission, invalid identifiers, and logout/login draft persistence. Assert GET requests never mutate attempts and every mutation is POST.

- [ ] **Step 2: Run route interaction tests and verify RED**

  Run: `cd materials/33/clone && pytest -q tests/test_assignment_flow.py -k 'canonical or start or draft or submit or owner or identifier'`

- [ ] **Step 3: Wire authenticated read routes**

  Add exact design URLs for course home/module, lecture, assignments/grades, notes, inbox, info, resources, assignment entry/attempt/result. Use the existing `_authenticated_subject`, `_permission_page`, `_enrollment_required_page`, `_safe_next_path`, `_page`, and session-cookie helpers. Preserve intended local destinations through inline login.

- [ ] **Step 4: Wire POST mutations and validation responses**

  Add note save/delete, honor-code start, draft save, and assignment submit endpoints. Parse repeated checkbox values from Starlette `FormData.getlist`, never accept owner/score/time fields, redirect after successful writes, and return source-shaped `422` guidance for incomplete/invalid input. Foreign attempts use the same non-disclosing 404/permission response.

- [ ] **Step 5: Add presentational timer and local asset closure**

  `assignment.js` reads only a server-rendered expiry timestamp, updates remaining time, disables editing when it reaches zero, and reloads the route so the server performs authoritative expiry. It must not contain answers, calculate scores, or send background requests. Copy the seven sanitized images with stable local names and confirm all generated `src` values resolve locally.

- [ ] **Step 6: Run all assignment flow tests and verify GREEN**

  Run: `cd materials/33/clone && pytest -q tests/test_assignment_flow.py`

---

### Task 6: Desktop fidelity styles and browser contract

**Files:**
- Create: `materials/33/clone/static/enrolled-learning.css`
- Modify: `materials/33/clone/ui.py`
- Modify: `materials/33/clone/app.py`
- Create: `materials/33/clone/tests/test_enrolled_learning_browser.py`

**Interfaces:**
- Produces a versioned `/static/enrolled-learning.css` link on enrolled pages and stable `data-*` selectors for browser checks.

- [ ] **Step 1: Write failing structural/browser contract tests**

  Assert the versioned stylesheet/script links, local image resolution, `1692 × 979` viewport shell, no horizontal overflow, visible course sidebar and main content, consistent question image sizing, accessible labels, and no answer-key strings in page source. Browser tests must fail if any local request returns 4xx/5xx or if the console records an error.

- [ ] **Step 2: Run contract tests and verify RED**

  Run: `cd materials/33/clone && pytest -q tests/test_enrolled_learning_browser.py`

- [ ] **Step 3: Implement source-shaped desktop CSS**

  Match observed Coursera typography scale, restrained blue/gray palette, header heights, fixed course navigation width, central content width, cards, dividers, form controls, progress/timer treatment, and full-page scrolling at `1692 × 979`. Keep source-observed transitions only; add no invented animation.

- [ ] **Step 4: Run browser contract tests and verify GREEN**

  Run: `cd materials/33/clone && pytest -q tests/test_enrolled_learning_browser.py`

---

### Task 7: Existing behavior regression and machine diagnostics

**Files:**
- Modify only if failures identify an enrolled-slice regression: files from Tasks 1–6
- Modify if new routes must be declared: `materials/33/scope/verify.json`
- Modify: `materials/33/KNOWN_DIFFERENCES.md`

**Interfaces:**
- Consumes all prior tasks.
- Produces an honest verification report; diagnostics remain advisory and do not become a merge gate.

- [ ] **Step 1: Run focused and existing learner regression tests**

  Run: `cd materials/33/clone && pytest -q tests/test_enrolled_learning_source_fidelity.py tests/test_assignment_backend.py tests/test_assignment_flow.py tests/test_enrolled_learning_browser.py tests/test_learning_backend.py tests/test_authenticated_empty_surfaces.py tests/test_checkout_flow.py tests/test_current_phase_matrix.py`

- [ ] **Step 2: Run the complete site-33 clone suite**

  Run: `cd materials/33/clone && pytest -q`

- [ ] **Step 3: Discover and run shared clone diagnostics**

  Run from repository root:

  ```bash
  python tools/offline_clone/run.py tools list
  python tools/offline_clone/run.py verify --site materials/33
  ```

  Record `clean`, `findings`, or `incomplete` exactly as reported. Do not reinterpret Harbor `Errno 95` or other infrastructure incompleteness as a page-test pass or failure.

- [ ] **Step 4: Scan for forbidden sensitive persistence and key leakage**

  Inspect the diff and generated local database schema/data. Confirm no credential, cookie, authorization header, entered legal name, source identity, source answer submission, or answer key exists in HTML/JavaScript/evidence output. Confirm the answer key appears only in server-side Python.

- [ ] **Step 5: Update known differences and backend handoff facts**

  Document that source correctness/result feedback is unavailable, so scoring is local; source course completion/certificates remain deferred; Messages is read-only empty; and the local player does not stream source video. Report runtime `materials/33/backend/runtime.json`, site ID `33`, database `33.sqlite3`, distinct local data/volume identity, mail purposes `registration` and `password-reset`, payment `local-sandbox`, and deployment profiles from the runtime contract.

- [ ] **Step 6: Final manual browser acceptance**

  Start the clone, use the learning demo account, and traverse My Learning → Course → Welcome lesson → save note → assignment entry → start → save draft → reload → submit → result → Grades at `1692 × 979`. Confirm the browser has no broken local images, failed local requests, console errors, horizontal overflow, or cross-owner data exposure. Stop the server after capture.

