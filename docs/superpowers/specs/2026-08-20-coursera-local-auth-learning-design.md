# Coursera Local Auth and Learning Design

## Goal

Continue site 33 from the completed signed-out public surfaces by implementing
the locally simulated account, learning, history, preference, and enrollment
flows that are explicitly covered by the 23 journeys, while preserving the
source-grounded public pages and never requiring real credentials, email, or
payment data.

## Scope and Boundaries

The first implementation slice covers local registration, verification inbox,
onboarding, login, logout, password recovery, and the learner dashboard. The
second slice covers seeded learning state, lesson navigation, progress,
bookmarks, quiz feedback, preferences, history, and cancellation boundaries.
The final slice covers Deep Learning Specialization enrollment through the
empty payment fields and local-sandbox review/result states.

The source site remains read-only. No account is created on Coursera, no
external identity provider is opened, no real email is sent, and no card value
is accepted or persisted. Existing `materials/33/backend/runtime.json` and the
generated `websitebench.site_backend` seam remain authoritative.

## Architecture

FastAPI route handlers remain thin: they read the authenticated subject from
the existing site backend, call `backend.learning_db` or `backend.checkout`,
and render the existing local shell. Templates never invent authentication or
enrollment state. Each state transition is owner-bound to `site_id=33` and is
exercised through TestClient plus focused browser checks.

Public pages remain source snapshots or source-backed templates. Authenticated
pages are truthful local simulations and must visibly identify local behavior
where a user could confuse it with a real Coursera account or transaction.

## Complete-Load Strategy

Every browser scenario that visits a long or lazy page must use the same
settling helper and record its evidence:

1. Open at the acceptance viewport `1692 x 979`.
2. Wait for `domcontentloaded`, then `networkidle` with a bounded timeout.
3. Scroll the document in viewport-sized increments until the bottom is
   reached, waiting briefly after each increment for newly inserted content.
4. Repeat the bottom check twice; stop only when `scrollHeight`, section count,
   image count, and loaded-image count remain unchanged.
5. Assert every visible image has `complete == true` and, where applicable,
   `naturalWidth > 0`; remote URLs and failed requests are failures.
6. Capture the final `scrollHeight`, ordered headings, card counts, and full
   page screenshot. A partial first viewport is never accepted as complete.

The helper must be bounded: a maximum number of scroll rounds and a maximum
settling duration produce an explicit `incomplete` result instead of hanging.
Lazy sections that cannot settle are reported with their selector and counts;
they are not replaced with guessed cards or placeholder content.

## Backend Contracts

- Registration and recovery use the existing local inbox and configured mail
  purposes only.
- Sessions use the generated host-only `__Host-websitebench-33-session` cookie.
- Learner records, progress, preferences, bookmarks, quizzes, and orders stay
  in the site-33 SQLite database.
- Enrollment and checkout use the existing `local-sandbox` adapter and its
  approved/declined/retry scenarios.
- Every mutating route validates the current subject, exact allowed fields,
  ownership, idempotency where applicable, and safe same-origin continuation.
- Sensitive-looking payment inputs have no `name` attribute and are never
  submitted to or stored by the server.

## UI Contracts

The current desktop shell and measured content width are preserved. Auth
dialogs stay same-document where the source shows a modal; direct auth routes
retain the public page identity where already captured. Authenticated screens
use the existing local learner chrome and do not add source-unverified
marketing sections. Controls expose real validation, permission, empty,
loading, and success/error states.

## Test and Evidence Gates

Each slice follows red-green verification:

- backend unit/integration tests for state, ownership, persistence, and
  idempotency;
- route-level HTML assertions for fields, labels, links, and error states;
- Playwright checks at `1692 x 979` for navigation, complete-load settling,
  image health, route stability, and visible state transitions;
- full-page screenshots only after the complete-load helper settles;
- repository static/network diagnostics and the existing public regression
  suite before handoff.

Authenticated and payment states are labeled as local simulations unless a
current source artifact directly verifies them. No deferred journey may be
silently promoted to source-complete.

## Non-Goals

Do not recapture changing Coursera pages without a specific evidence gap. Do
not add real payment processing, production email, external OAuth, CAPTCHA
bypass, source account creation, or new marketing/catalog sections. Do not
commit, deploy, or clean unrelated worktree changes.
