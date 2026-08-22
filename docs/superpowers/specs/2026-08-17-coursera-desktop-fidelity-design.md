# Coursera Desktop Fidelity Design

## Goal

Rebuild the WebsiteBench site `33` offline Coursera clone so its desktop
experience at a `1191 × 979` viewport closely matches the current, directly
observed Coursera experience while retaining real local state and safe,
deterministic backend behavior.

## Scope

The clone covers the human traces in `materials/33/scope/human-traces.json`:

- public entry, Browse, category navigation, search, filtering, empty-result
  recovery, course and specialization detail, free preview, Help, and 404;
- unified sign-in/create-account entry, local account registration and login,
  password-recovery guidance, validation, and safe return paths;
- seeded My Learning, lessons, quizzes, bookmarks, progress, preferences,
  certificates/reviews, history, and cancellation routes;
- Deep Learning Specialization enrollment through a clone-local checkout,
  review, retry, decline, and local-sandbox approval flow.

This is desktop-only work. There is no mobile-fidelity deliverable.

## Source-grounded presentation

The default clone language is Simplified Chinese because this was the current
source rendering observed in the isolated browser. Proper names, provider
names, course identifiers, and search compatibility remain in English where
the source showed or required them.

The primary visual baseline is the observed desktop viewport: `1191 × 979` at
device-pixel-ratio `1.5`. Public, self-contained SingleFile captures are local
reference material only. They are never committed. Public screenshots or
selected permitted source assets may be placed in the site evidence/assets
directories only after secret and remote-reference checks. Authenticated HTML,
screenshots containing account information, and browser state remain local
scratch material and are never committed.

Observed checkout facts to reproduce in the local clone are:

- Deep Learning / DeepLearning.AI;
- 7-day free trial;
- `¥196/month` after the trial;
- `¥0` due today;
- billing name and country controls, payment-method area, terms acknowledgment,
  and a final start-trial action.

The offline checkout must never submit real payment data or contact Coursera.
It uses the existing `local-sandbox` adapter and synthetic local payment
controls only.

## Architecture

Keep FastAPI, the generated `websitebench.site_backend` integration, site-33
SQLite isolation, and the existing catalog/learning semantics. Replace the
current sparse, English-first visual layer with source-derived presentation
components rather than embedding source pages, iframes, remote resources, or
screenshots.

The UI is divided into:

1. global desktop chrome: audience bar, header, search, account controls, and
   footer;
2. public catalog: home, Browse, subject/category, search/results/filtering,
   no-match recovery, and public help/404;
3. learning content: specialization, component course detail, expandable
   modules, pricing, enrollment choices, and free preview;
4. account and learner views: unified auth, registration, recovery guidance,
   dashboard, course player, quizzes, history, certificates/reviews, and
   preferences;
5. purchase views: signed-out enrollment, trial plan selection, checkout,
   review, order result, retry, and cancellation.

Use a small set of focused render helpers/templates and per-surface CSS rather
than growing the existing monolithic HTML and CSS. Existing routes retain their
behavior. Add a local alias for source-facing checkout paths such as
`/payments/checkout` while preserving existing test-supported checkout URLs.

All visible data comes from the local seeded catalog and per-user SQLite state.
GET routes render state, and validated POST routes mutate it using
post-redirect-get. Repeated submissions, refreshes, server restarts, and a
second local user preserve the current backend guarantees.

## Source/task differences

Current Coursera returned AI-generated recommendations for the required
`zzzz-no-match-websitebench` query rather than a classic empty-results page.
The clone will show an explicit no-match message required by the trace, retain
useful recommendations, and expose a route back to Browse. This intentional
difference is recorded as source-current behavior rather than represented as a
verified original empty state.

Current anonymous authentication is a unified email-first entry. Direct access
to a reset-address form required identifying an existing account first. The
clone provides the requested local recovery form and validation while retaining
the observed help guidance and return-to-sign-in route. Its source limitation is
recorded honestly.

## Verification

Each production behavior begins with a focused failing test and a confirmed
failure before implementation. Site tests cover:

- Chinese desktop copy, source-facing route aliases, canonical headings, and
  accessible controls;
- catalog filtering, impossible-query recovery, detail consistency, and preview;
- local sign-up/login/logout/recovery validation and cross-user isolation;
- seeded learning progress, quizzes, bookmarks, history, settings, and
  persistence;
- local checkout price/trial display, safe form boundaries, idempotency,
  decline/retry/approval behavior, and order ownership;
- missing-route, permission, and empty/invalid input states.

Visual work is evaluated at `1191 × 979` against public source oracles for
home, Browse, search, specialization, course, authentication, help, and 404.
The existing WebsiteBench visual and diagnostic tools are diagnostic evidence,
not merge gates. Final acceptance requires side-by-side human replay of the
selected traces, offline runtime closure, and honest known-difference notes.

## Safety constraints

- No credentials, cookies, session tokens, browser profiles, real user data, or
  raw authenticated captures enter Git.
- Runtime remote requests remain closed; no source proxy, iframe, or screenshot
  substitute is used.
- The site ID, session cookie, database/volume identity, and mail branding stay
  unique to `33`.
- `local-sandbox` is the only payment profile. No live payment, real email,
  external publication, push, PR, or merge is part of this implementation.
