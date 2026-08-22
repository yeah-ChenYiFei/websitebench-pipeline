# Coursera Interaction and Backend Closure Design

**Date:** 2026-08-20  
**Site:** `materials/33`  
**Status:** User-approved design; implementation not started by this document

## 1. Objective

Complete the functional reconstruction of the scoped Coursera offline clone. Every
interactive control visible on a reproduced source page must be a real DOM control
with an observable local result. A button, link, tab, menu, filter, form field,
carousel switch, player control, or similar source interaction must not be baked
into an image, left inert, or replaced by a fake success message.

The formal acceptance spine remains the 23 human traces in
`materials/33/scope/human-traces.json`. The interaction audit also covers every
source-supported control on the reproduced pages reachable through those traces.
This does not authorize unbounded crawling or reconstruction of every Coursera
entity.

## 2. Product and Safety Boundaries

- The clone is English-only and is primarily accepted at a `1692 x 979` CSS
  viewport.
- Frontend similarity targets at least 90 percent for the representative pages.
- Core behavior must be real, local, deterministic, and persistent where the
  source behavior represents durable learner state.
- Representative catalog and learning data are sufficient. The clone does not
  need every Coursera course or specialization.
- The primary learning journey uses Deep Learning Specialization and Neural
  Networks and Deep Learning for a normal learner.
- No request may reach Coursera private APIs or create a source-site mutation.
- No real payment credential, live payment, real recovery message, source quiz
  submission, source rating, or source cancellation is allowed.
- The clone uses the generated WebsiteBench backend integration and its
  `local-sandbox` payment adapter. It must not introduce custom authentication,
  mail, payment, database identity, hashing, or release-gate infrastructure.
- Existing user changes are preserved. This work does not authorize a commit,
  push, pull request, or deployment.

## 3. Interaction Contract

Maintain a site-specific control inventory for the reproduced, reachable pages.
Each entry records:

- local route and stable control identity;
- visible label and semantic control type;
- source-observed behavior and evidence reference;
- local route, form action, API, or client-side state transition;
- owning data domain and actor;
- persistence requirement;
- authentication and authorization requirement;
- safe external-effect boundary, when applicable;
- positive, validation, permission, duplicate, and recovery tests as applicable.

The inventory is diagnostic site data, not a new repository-wide gate. The source
of truth for acceptance remains the human traces, site scope, tests, evidence, and
maintainer judgment together.

## 4. Control Rules

### 4.1 Required behavior

- Navigation controls open a real local destination.
- Search, filters, sorting, pagination, and category controls change real local
  query results.
- Tabs and disclosure controls change visible state and expose the corresponding
  content.
- Forms submit to a local endpoint and show server-derived success or validation
  results.
- Enrollment, order, progress, bookmark, note, assignment, preference, and
  history controls mutate owner-scoped local state.
- Refresh, relogin, and process restart preserve state when the represented
  source action is durable.
- Lists and detail pages use consistent local entity identities.

### 4.2 Forbidden substitutes

- No screenshot or raster asset may contain a primary interactive control used
  as the interaction itself.
- No empty `href`, placeholder `javascript:` URL, inert enabled button, or
  click-only fake success message is acceptable.
- An enabled control may not silently do nothing.
- A disabled control must be disabled intentionally, name the unavailable
  capability, and provide a safe return route when appropriate.

### 4.3 Safe substitutes for external capabilities

- Google, Facebook, and Apple identity choices open a local provider-boundary
  view; they never contact the provider.
- Password recovery uses the generated local mail/outbox behavior or a local
  preview boundary; it sends no real message.
- Checkout accepts only opaque `local-sandbox` scenario identifiers. It never
  accepts or stores a real card number, CVV, expiry, bank account, wallet value,
  or provider token.
- Read-only source activities remain read-only. The clone can reproduce the
  local outcome without claiming a source-side action occurred.

## 5. Functional Domains

### 5.1 Public discovery

Includes header and footer navigation, Explore menus, promotional switching,
category navigation, search, filters, result cards, course and specialization
details, preview materials, no-results recovery, help, and not-found recovery.
Public query state may use route and query parameters; no database write is
required unless the source behavior represents a durable preference.

### 5.2 Account and onboarding

Includes registration, login, logout, account recovery entry, onboarding,
settings, updates, and authenticated navigation. Account and session behavior
must use `websitebench.site_backend` through the generated integration seam.
Errors must preserve the initiating page as the background or safe return target.

### 5.3 Enrollment, checkout, and orders

Includes track selection, signed-out permission prompts, local enrollment,
checkout draft creation, payment-boundary display, server-owned review totals,
deterministic sandbox outcomes, order history, enrollment history, cancellation,
and duplicate-submission protection. Totals, owner, currency, fingerprint, and
status are validated by the server.

### 5.4 Enrolled learning

Includes My Learning, course navigation, unit navigation, local lesson content,
notes, bookmarks, progress, grades, resources, assignment attempts, drafts,
timers, submission, scoring, and feedback. Durable learner state is owner-scoped
and stored in the site database.

### 5.5 Learner records and preferences

Includes purchases, enrollment history, learning preferences, updates,
completion state, certificate boundary, and locally supported rating or review
controls. Actions unavailable by safety or missing evidence expose an explicit
local boundary rather than an inert control.

## 6. Data Flow

Use semantic HTML links and forms whenever a browser-native request is sufficient.
Use JavaScript only for transient presentation behavior such as modal visibility,
menu expansion, carousel switching, tab presentation, and media UI state.

Durable operations follow this flow:

1. The control submits a local request containing only user-editable fields and
   opaque local identifiers.
2. The server resolves the authenticated owner and canonical entity.
3. The server validates permission, required input, current state, and duplicate
   or idempotency constraints.
4. The domain service writes the state through the site-specific database and,
   where applicable, the generated WebsiteBench integration seam.
5. The server redirects or returns a server-derived view of the new state.
6. A subsequent refresh or login reconstructs the same state from storage.

Client-provided prices, ownership, completion status, scores, and order totals
are never trusted.

## 7. Validation, Errors, and Recovery

- Missing required input produces an inline correction next to the responsible
  control and performs no mutation.
- Anonymous protected actions produce a login or permission prompt with a
  validated local return path.
- Foreign-owner objects fail closed without exposing whether another learner's
  private record exists.
- Unknown local entities use the branded not-found or domain-specific recovery
  view and retain primary navigation.
- Duplicate enrollment, order, assignment, and cancellation requests are
  idempotent or rejected with the already-existing result visible.
- Sandbox decline and retry states create no paid enrollment or completed order.
- External or unsafe actions visibly explain the boundary and offer a safe local
  continuation or return route.

## 8. Test Strategy

Every production behavior change follows red-green-refactor: add a focused test,
observe the expected failure, implement the smallest behavior, and rerun the
focused and adjacent tests.

### 8.1 Static interaction checks

Check reproduced reachable pages for:

- empty or placeholder links;
- enabled buttons lacking a form action, route, or registered behavior;
- forms lacking a meaningful local target;
- primary source controls represented only inside raster images;
- local links that escape to the source site;
- controls absent from the site interaction inventory.

Intentional disabled boundaries are allowed only when they expose an accessible
reason.

### 8.2 Browser interaction checks

At `1692 x 979`, use Playwright to operate each inventory control and assert the
expected URL, visible state, result count, modal state, validation message, or
durable outcome. Checks must also fail on console errors, failed local requests,
unexpected remote requests, and horizontal overflow in scoped checkpoints.

### 8.3 Backend semantic checks

Test positive and negative behavior for owner isolation, validation, persistence,
restart recovery, idempotency, tampered values, foreign objects, sandbox decline,
and sandbox retry. Use actor-isolated loopback tests where they fit the existing
WebsiteBench diagnostic interface.

### 8.4 Trace replay

Replay all 23 human traces and bind each trace step to the concrete control,
route/API, stored result, and evidence classification. A visually present but
inert control does not satisfy a trace.

### 8.5 Visual verification

After functional closure, compare the main checkpoints against the source at the
acceptance viewport. Visual micro-adjustments must not interrupt functional
domain completion unless they hide or prevent operation of a control.

## 9. Execution Order

1. Inventory all controls on reproduced reachable pages and classify each as
   working, incomplete, safe boundary, or missing.
2. Add static contract tests that expose inert and image-baked controls.
3. Close public discovery interactions.
4. Close account and onboarding interactions.
5. Close enrollment, checkout, and order interactions.
6. Close enrolled-learning and assignment interactions.
7. Close records, preferences, updates, and completion boundaries.
8. Replay the 23 traces, run backend isolation checks, run site tests, and run
   current diagnostics.
9. Perform one consolidated visual correction pass.

Focused tests run after each domain. The full site suite runs at milestones rather
than after every small edit. Repository-wide tests are not part of the inner loop.

## 10. Completion Criteria

The work is ready for user review only when:

- every source-supported control on every reproduced reachable page is functional
  or is an explicit, accessible safety boundary;
- no primary interaction is embedded in an image;
- all 23 traces have concrete control and backend bindings;
- durable state survives refresh, relogin, and restart as applicable;
- cross-owner access, tampering, invalid input, and duplicates behave correctly;
- no real external effect or remote dependency is introduced;
- focused and site-wide tests have current reported results;
- diagnostics and known differences are reported honestly;
- no commit, push, pull request, or deployment has occurred without separate
  authorization.
