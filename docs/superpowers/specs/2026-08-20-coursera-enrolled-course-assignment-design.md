# Coursera Enrolled Course and Assignment Design

## Goal

Extend the existing `materials/33` Coursera offline clone with one deeply
reconstructed enrolled-learning mainline for `Neural Networks and Deep
Learning`. The slice covers the enrolled My Learning card, course navigation,
lesson shell, notes, progress, grades, resources, course information, and a
functional ten-question assignment with local drafts, submission, scoring, and
feedback.

## Authority and scope

- The source authority is the sanitized English authenticated evidence under
  `materials/33/source-evidence/2026-08-20-enrolled-learning/`.
- The acceptance viewport remains `1692 × 979` CSS pixels.
- The source-observed program is `Deep Learning`; the representative course is
  `Neural Networks and Deep Learning`, Course 1 of 5 from `DeepLearning.AI`.
- Question wording, option ordering, diagrams, routes, controls, attempt rules,
  and empty states come from direct source evidence.
- The answer key is a clone-local course-knowledge rule because no answer was
  selected or submitted on the source. The UI and documentation must not claim
  the key was source-verified.
- All persistent state is site-33-local. No clone action contacts Coursera,
  sends mail, performs identity verification, uses payment data, or changes a
  source account.
- No real Git commit is created unless the user later authorizes one.

## Selected approach

Build a deep representative slice instead of a shallow generic course engine.
Reuse the existing FastAPI application, WebsiteBench account/session seam,
`backend/learning_db.py`, renderer pattern, and local static assets. Add only
the course-specific view data and owner-scoped state necessary for the observed
course and assignment.

This approach maximizes source fidelity and backend completeness for the core
learner journey while avoiding invented course content for unrelated products.
The persistence and route interfaces remain structured so another
source-grounded course can be added later without replacing this slice.

## Route model

Authenticated enrolled routes are:

- `/my-learning?myLearningTab=IN_PROGRESS`
- `/my-learning?myLearningTab=COMPLETED`
- `/my-learning?myLearningTab=CERTIFICATES`
- `/learn/neural-networks-deep-learning/home/welcome`
- `/learn/neural-networks-deep-learning/home/module/{week}` for weeks 1–4
- `/learn/neural-networks-deep-learning/lecture/Cuf2f/welcome`
- `/learn/neural-networks-deep-learning/home/assignments`
- `/learn/neural-networks-deep-learning/home/notes`
- `/learn/neural-networks-deep-learning/course-inbox`
- `/learn/neural-networks-deep-learning/home/info`
- `/learn/neural-networks-deep-learning/resources/{resource_id}`
- `/learn/neural-networks-deep-learning/assignment-submission/3KFZW/introduction-to-deep-learning`
- `/learn/neural-networks-deep-learning/assignment-submission/3KFZW/introduction-to-deep-learning/attempt`
- `/learn/neural-networks-deep-learning/assignment-submission/3KFZW/introduction-to-deep-learning/result/{attempt_id}`

`/home/welcome` canonicalizes to module 1 for an enrolled owner. Signed-out
requests preserve the intended destination through the existing inline login
continuation. A user without the local enrollment receives a permission prompt
and a safe route back to My Learning; the application never leaks another
owner's attempt, note, or progress identifier.

## Presentation components

### Enrolled My Learning

The In Progress tab renders the observed `Deep Learning` five-course program
card. Course 1 exposes the `Welcome` item and `Get started` or `Resume` action;
courses 2–5 remain not started. The calendar, completion unlock copy, career
goal header, Completed empty state, and Certificates empty state follow the
retained evidence. The clone does not open third-party identity verification.

### Course home and navigation

The enrolled shell contains the Coursera course header, DeepLearning.AI brand,
course title, course search, Week 1–4 navigation, Grades, Notes, Messages,
Resources, and Course Info. Module 1 reproduces the observed learning-objective
summary, item groups, course timeline, deadlines, and weekly-target surface.
Weeks 2–4 use only titles and content identities already observed in the source
or existing site data; missing source details are not invented.

### Lesson shell

The Welcome lesson reproduces the video poster, disabled/local-only player,
Transcript, Notes, Files, Save note, reaction controls, course item sidebar,
and Go to next item. Local playback controls do not stream a remote source
video. Opening or using the local lesson updates only local resume/progress
state. Saving a note persists owner-scoped text and makes it visible on the
course Notes page.

### Grades, Notes, Messages, Resources, and Course Info

- Grades renders the observed assignment table and reflects the locally
  submitted Week 1 result.
- Notes starts with `You have no notes`, supports local note creation from the
  lesson, filtering, and deletion by the owner.
- Messages retains the observed `There are no messages yet.` state. No send
  control is introduced because source sending was not authorized or observed.
- Resources exposes Course Notation Sheet and Course Acknowledgments as local
  read-only pages.
- Course Info contains the observed course/provider, description, instructors,
  basic facts, syllabus, How It Works, specialization position, and related
  courses.

## Assignment interaction

### Entry and attempt lifecycle

The entry page contains What to expect, Coursera Honor Code, `Start assignment`,
and the observed 50-minute rules. Starting creates one owner-scoped local
attempt with a server timestamp, a stable attempt ID, an empty answer map, and
status `in_progress`.

The first start requires the local Honor Code acknowledgement. A current
attempt resumes instead of silently creating duplicates. The server derives
remaining time and attempt state; client-supplied timestamps, points, grades,
or owner IDs are ignored.

### Questions and drafts

The attempt renders all ten directly observed questions in source order,
including radio, checkbox, and image-choice controls. `Save draft` stores the
current answer map without grading. Refresh, logout/login, and process restart
preserve the draft. Empty, malformed, foreign-question, and invalid-option
values are rejected without disclosing answer-key data.

The local browser timer is presentational; the server timestamp is
authoritative. An expired attempt becomes locally auto-submitted the next time
the owner loads or mutates it. The clone does not require a background worker.

### Submission, scoring, and feedback

Submission requires the locally stored learner display name to match the
entered legal-name confirmation after whitespace normalization. It rejects
missing questions, invalid answer shapes, duplicate submission, foreign
attempts, and expired/stale forms.

The server scores each question against a private clone-local answer key. The
result stores immutable question, answer, points, and feedback snapshots in the
same transaction that marks the attempt submitted and updates Grades/progress.
The response shows total points, percentage, pass state, per-question
correct/incorrect status, the learner's selection, and concise explanatory
feedback. The answer key is never embedded in HTML or JavaScript before
submission.

The result is a local simulation of Coursera-shaped behavior, not a claim that
the source accepted or graded those answers.

## Persistence model

Extend the existing site-33 SQLite learning schema rather than creating another
database or backend. New owner-scoped records are:

- enrolled-program/course state;
- lesson resume and completion state;
- course notes;
- assignment attempts;
- attempt answers/drafts;
- immutable submitted result snapshots.

Every table is bound to the authenticated subject and course/assignment IDs.
Migrations remain repeatable, seed data remains deterministic, and restart
preserves included state. Seeded empty and enrolled learners stay distinct so
anonymous, unenrolled, and enrolled tests cannot contaminate one another.

## Validation and error behavior

- Signed-out access opens or returns to the inline login flow with a safe local
  `next` path.
- Unenrolled access returns a source-shaped permission prompt rather than a
  fabricated lesson.
- Week, lesson, resource, question, option, and attempt identifiers are
  allow-listed from retained course data.
- Draft and submission mutations use POST/Redirect/GET.
- Foreign-owner and forged-attempt access returns the same non-disclosing
  not-found/permission behavior.
- Duplicate submission returns the existing immutable result.
- No password, session token, answer key, personal identifier, entered legal
  name, note body, or answer payload is written to logs or evidence artifacts.

## Testing strategy

Implementation follows red-green-refactor for each independently observable
behavior:

1. evidence-loader and route inventory integrity;
2. authenticated enrollment/owner isolation;
3. My Learning and course-shell source content;
4. lesson resume and owner-scoped notes;
5. assignment start and draft persistence;
6. validation, scoring, immutable results, and grade/progress update;
7. Playwright fidelity and interaction checks at `1692 × 979`;
8. full existing 23-boundary regression, sensitive-data scan, static/live
   diagnostics, and honest reporting of Harbor limitations.

Browser checks require zero broken local presentation images, zero failed local
requests, zero console errors, no horizontal overflow, stable route recovery,
and complete internal-scroll capture for the assignment. Source answer
submission is never part of verification.

## Deferred states

- Source-verified answer correctness and source result/feedback presentation;
- completion of the source course or specialization;
- populated source certificates;
- source rating/review submission;
- source cancellation or unenrollment;
- real message sending, identity verification, mail, payment, or external
  provider effects.

The local assignment result is implemented because the user requested working
answering and grading, but its answer key and feedback remain explicitly local
until direct non-destructive source evidence becomes available.
