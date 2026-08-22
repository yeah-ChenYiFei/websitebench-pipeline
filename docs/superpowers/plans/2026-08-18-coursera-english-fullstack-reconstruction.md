# Coursera Pure-English Full-Stack Reconstruction Plan

> **Mandatory fidelity addendum:** Read and follow
> `docs/superpowers/specs/2026-08-18-coursera-source-fidelity-lessons.md`
> before acquiring or implementing each additional route. It defines the
> evidence-completeness gate, dynamic GraphQL handling, card-identity tests,
> visual geometry checks, and anti-invention rules learned from the Browse
> reconstruction.

> **For agentic workers:** Use `superpowers:executing-plans` to implement this plan inline and `superpowers:test-driven-development` for behavior changes. Do not dispatch subagents or create commits unless the user explicitly changes those constraints.

**Goal:** Rebuild the 23 agreed Coursera core journeys as a pure-English, desktop-first offline clone with source-grounded visuals and safe local accounts, learning state, checkout, orders, and payments.

**Architecture:** Keep `materials/33` as the only finished site and preserve its WebsiteBench site identity and backend runtime. Replace the coupled HTML presentation with FastAPI/Jinja2 templates, modular CSS, small source-grounded JavaScript interactions, and explicit view-model/service boundaries. Use Playwright for one-pass source evidence acquisition; retain the existing homepage WACZ only as homepage evidence and an asset source.

**Tech Stack:** Python, FastAPI, Jinja2, SQLite, `websitebench.site_backend`, vanilla JavaScript, CSS, pytest, Playwright, and the repository WebsiteBench offline-clone diagnostics.

## Global Constraints

- Finished site: `materials/33`; do not build a second full backend in `materials/coursera-wacz-home`.
- Language: all runtime UI, catalog data, learning content, errors, mail branding, checkout facts, and business snapshots are English.
- Viewport: desktop `1191 x 979`; mobile fidelity is not part of this iteration.
- Scope: exactly the 23 agreed Coursera journeys; no bonus features in this iteration.
- Source origin: `https://www.coursera.org` and only explicitly approved presentation-asset origins.
- Source acquisition is read-only. Never submit enrollment, trial, quiz, review, cancellation, order, or payment mutations.
- Never receive, persist, log, screenshot, or submit account passwords, cookies, tokens, card numbers, CVV, expiry dates, wallet credentials, or private account data.
- Payments remain `local-sandbox`; Stripe live and real payments are forbidden.
- Preserve `site_id=33`, its separate database/volume identity, session isolation, mail purposes, and the generated WebsiteBench integration seam.
- Do not create or extend hash, approval, freeze, merge-gate, or scoring infrastructure.
- Preserve historical Chinese evidence, compatibility data, hashes, and recorded commands unchanged.
- Keep every implementation change uncommitted until the user explicitly authorizes a commit.
- If evidence, source behavior, pricing, or product intent is unclear, stop and ask the user before implementing that part.

## Current State and Authority

- `materials/33` already has catalog, search, authentication, learning, checkout, order, and SQLite behavior covering the 23 journeys, but its presentation is coupled, visually incomplete, and mixed Chinese/English.
- `materials/coursera-wacz-home` is an uncommitted homepage-only experiment. Its source WACZ is available at `/mnt/c/Users/15332/Downloads/my-archiving-session (1).wacz` and contains only two equivalent English homepage captures.
- Source authority order:
  1. Fresh pure-English Playwright capture for public pages, authenticated chrome, the empty learner account, and the reachable payment page.
  2. The 2026-08-17 homepage WACZ for homepage content, fonts, and recoverable presentation assets.
  3. Existing site-33 business rules and safely observed checkout facts for states that cannot be visited without a source mutation.
  4. Shared Coursera design patterns plus explicit clone-local simulation for inaccessible authenticated states.
- Existing Chinese screenshots may explain historical work but are not English visual authority.
- Capture the current homepage with Playwright before implementation. If its shared navigation or primary layout materially conflicts with the WACZ, ask the user which version governs before combining them.

## Evidence Acquisition Protocol

### Temporary authenticated session

1. Start one disposable Playwright-backed browser session at `1191 x 979`, locale `en-US`, with normal source motion enabled for observation.
2. Give the user the temporary live browser surface; the user personally types credentials for the dedicated, empty test account.
3. The user personally navigates to the reachable payment page and stops with all payment-credential fields empty.
4. Starting from the already-open page, capture only visible presentation facts, structure, labels, geometry, and safe screenshots.
5. Mask visible name/email/account identifiers before retaining a screenshot.
6. Close and release the session after capture. Do not persist its profile, storage, live-session identifier, cookies, or tokens.
7. If a live session is unavailable, use a user-created temporary Playwright storage-state file outside the repository. Consume it read-only by path and have the user delete it afterward; never print or copy its contents.

### Network and interaction rules

- Configure `source_mutations_authorized=false` and block non-GET source requests.
- Menus, tabs, accordions, carousel controls, and other client-only presentation changes may be opened when they create no remote state.
- Do not bypass a card form, paywall, enrollment condition, or course permission.
- Treat third-party payment iframes as visual rectangles: capture their visible appearance and size, but do not inspect or record values.
- Strip queries/fragments from recorded URLs and retain no raw request/response bodies or headers.
- Use the repository Playwright/WebsiteBench capture path for formal evidence. A cloud browser is only a fallback for login/CAPTCHA reliability, not the default acquisition path.

### Batch capture matrix

- Public: current homepage, all manually selectable homepage promotion states, Explore menu, browse, one representative category plus the 11 discovered category routes, search results, each filter family, no-results, Deep Learning specialization, expandable course-detail module descriptions, login, signup, recovery, help/contact, and 404.
- Authenticated/direct: account navigation, empty My Learning/Dashboard, safely reachable preferences/history surfaces, logged-in Deep Learning surfaces, track selection visible before mutation, payment page, and empty-field/disabled-continuation state when observable without submission.
- Never acquire through source mutation: onboarding completion, enrollment completion, lesson access unavailable to the empty account, quiz submission, bookmark/progress changes, certificate completion, review submission, order confirmation, cancellation, approved/declined/retry results.
- Extract one compact JSON summary per route/state: title, safe path, visible text, landmark/control tree, form labels, key boxes, necessary computed styles, resource manifest, animation observation, and screenshot references.
- Keep screenshots to canonical states and material interaction states. Do not use screenshot-per-click capture.

## Evidence Classification

| Surface | Classification | Clone treatment |
| --- | --- | --- |
| Public home/catalog/search/course/help/404 | `direct-source` | Reproduce from Playwright; use WACZ assets on the homepage |
| Login/signup/recovery/account chrome/empty dashboard | `direct-source` | Reproduce directly and connect to local auth |
| Deep Learning track and reachable payment page | `direct-source` | Reproduce page facts and appearance without source submission |
| Payment empty-field state | `direct-source` when locally observable | Reproduce visible validation/disabled state safely |
| Seeded dashboard/onboarding/lesson/quiz/progress | `shared-design-derived` + `offline-simulation` | Use source design system with deterministic site-33 state |
| Review/confirmation/approved/declined/retry | `offline-simulation` | Use server-owned source facts and local-sandbox outcomes |
| History/cancellation/certificate/review/preferences mutations | `offline-simulation` | Persist only in site-33 SQLite and label honestly |

Reflect these classifications in the site's purpose, claims, coverage, checkpoints, journeys, verification recipes, and `KNOWN_DIFFERENCES.md`. Never describe a clone-local state as directly observed source behavior.

## Animation Policy

- Do not invent animation where the source has none.
- Reproduce a source animation when it is prominent, affects comprehension, or is central to an interaction and can be implemented economically.
- Decorative or expensive source animation may use its correct static end state in the first iteration; record the omission when visually material.
- The homepage promotion area remains user-controlled and never auto-advances.
- Do not apply global hover, reveal, card-motion, or page-transition effects merely for polish.
- Respect `prefers-reduced-motion` in the clone.
- Observe the source once with normal motion to record triggers and behavior. Freeze animations only for deterministic reference screenshots and pixel/region comparison.

## Target Frontend Structure and Contracts

- Introduce Jinja2 layouts for public, auth, learning, and checkout shells.
- Introduce reusable components for header/footer, Explore navigation, course cards, filters, modals, forms, status/error panels, enrollment tracks, progress, and checkout summary.
- Split styles into design tokens, shared components, and route-specific sheets. Use recovered local fonts and presentation assets; no runtime remote assets.
- Use small vanilla ES modules only for evidenced interactions: Explore/menu state, manual promotion switching, search/filter enhancement, form feedback, lesson navigation, quiz UI, bookmark/progress controls, and checkout scenario selection.
- Split the current monolithic route/presentation implementation into controllers, existing backend services, view-model mapping, and templates. Do not replace the WebsiteBench auth/payment/database seam.
- Preserve the canonical browser routes declared in `scope/routes.json`. If a source-grounded canonical path changes, keep a safe compatibility alias for the previous local path.
- Preserve existing POST action semantics where safe; use server validation and POST/Redirect/GET for mutations.
- Do not add a public JSON API. Add stable `data-testid` attributes only where browser tests need them, without changing visible layout.

## Implementation Tasks

### Task 1: Freeze Evidence and Baseline

- Run the existing site-33 test suite and record baseline failures before edits.
- Execute the Playwright public and authenticated capture matrices once.
- Build the route/state/evidence/asset matrix and classify every required state.
- Compare current Playwright homepage chrome to the WACZ. Stop for user direction on a material version conflict.
- Record exact directly observed payment facts: product, organization, currency, due-now amount, trial length, renewal amount/period, tax/total presentation, CTA, terms, and visible field labels.
- Exit criterion: all 23 journeys have a declared direct/derived/simulated evidence source and no unresolved high-impact fact.

### Task 2: Protect and Rebuild Canonical Data

- Use the existing SiteBackend backup API to back up `data/33.sqlite3` outside the repository in a user-private location.
- Verify integrity, `site_id=33` binding, and restoration to a disposable target before reset.
- Add tests for pure-English canonical seed output and deterministic reset before changing seeds.
- Use the existing reset seam to rebuild English catalog, learner, course, lesson, history, and checkout seeds.
- Preserve runtime site/database/session/mail isolation. Do not copy or manually delete the SQLite file.
- Exit criterion: backup is recoverable, reset is deterministic, and runtime pages/data no longer mix Chinese and English.

### Task 3: Establish Templates and Shared Chrome

- Add failing route/presentation tests for English shared navigation, footer, design assets, and anonymous/authenticated states.
- Introduce Jinja2 rendering, layouts, components, design tokens, local fonts/assets, and minimal JavaScript entry points.
- Move routes incrementally from inline HTML to templates while keeping current functionality green.
- Implement the animation policy and reduced-motion behavior.
- Exit criterion: shared chrome matches the frozen English evidence and existing route/backend contracts still pass.

### Task 4: Public Discovery and Course Surfaces

- Rebuild home with manual promotion switching and no autoplay.
- Rebuild Explore, browse, 11 category routes, the 40-record real English catalog, search, all six filter families, and no-results recovery.
- Rebuild Deep Learning specialization, course detail, syllabus, instructor, prerequisites, reviews, pricing/tracks, and the observed expandable module descriptions. Do not create a standalone preview route unless a directly corresponding source page is later observed.
- Rebuild public help/contact and branded 404 recovery.
- Covers journeys 1, 3-6, 15, 21, and 22.
- Exit criterion: relevant HTTP/browser tests pass and canonical visual regions match direct evidence at `1191 x 979`.

### Task 5: Account and Permission Surfaces

- Rebuild login, signup, verification, logout, onboarding, recovery, local inbox/outbox, account chrome, and validation.
- Rebuild empty and seeded dashboards using direct empty-account evidence plus honest offline seeded state.
- Keep Google/Facebook/Apple choices presentational; never contact external identity providers.
- Preserve session rotation, non-enumerating recovery, account isolation, and signed-out prompts.
- Covers journeys 7, 8, 16-18, and 20.
- Exit criterion: local account lifecycle works end-to-end, evidence labels are accurate, and no source/auth secret is retained.

### Task 6: Free Enrollment and Learning

- Add a local `Audit / Learn for free` track that requires no card and creates a site-local enrollment.
- Rebuild enrolled dashboard, resume, lesson/unit navigation, deterministic quiz/feedback, bookmark, progress/completion, certificate options, rating/review, and preferences.
- Keep all state owner-scoped and durable across refresh and service restart.
- Covers journeys 9 and 11-14.
- Exit criterion: the seeded and newly enrolled learners complete the full local learning journey with no remote request.

### Task 7: Checkout, Orders, and Task 265

- Rebuild track selection and the payment page from direct Playwright evidence.
- Derive identity, course, plan, trial, currency, amount, tax, total, and renewal facts from a server-owned checkout draft.
- Do not submit payment credential fields. The only payment input accepted by the backend is an opaque configured local-sandbox scenario ID plus a valid idempotency key.
- Implement review/confirmation and approved/declined/retry outcomes as explicit offline simulation.
- Approved consumption, immutable order snapshot, and paid enrollment transition remain atomic in one owner-scoped SQLite transaction.
- Rebuild order/enrollment history, detail, safe cancellation, and foreign-owner non-disclosure.
- If direct English source payment facts differ from the current CNY runtime, update the supported runtime/payment-scope contract and run the existing checker; never hand-edit digest infrastructure.
- Covers journeys 2, 10, 19, and 23, including task 265.
- Exit criterion: the public-to-review task displays requested choices and server-derived totals without receiving payment credentials or causing a source effect.

### Task 8: Full Verification and Manual Handoff

- Run focused unit/route tests after each task and the complete suite after the final task.
- Replay all 23 browser journeys at `1191 x 979`, including positive, validation, signed-out, no-results, retry/decline, and recovery states.
- Run backend semantic tests for account/session/owner isolation; enrollment/progress persistence; payment approval/decline/retry/idempotency/staleness/forgery/foreign ownership; cancellation; reset; and backup/restore.
- Run WebsiteBench static/live diagnostics plus functional and region-level visual comparison. Treat results as diagnostic, not as a release gate.
- Check runtime source for remote URLs, secret material, payment fields, and unintended Chinese user-visible copy.
- Report runtime path, site ID, database/volume identity, mail purposes, payment profile, deployment profiles, exact test results, known differences, and incomplete machine checks.
- Give the user a local URL and route-by-route manual review checklist. Do not commit.

## Acceptance Criteria

- All 23 agreed journeys are reachable and functionally complete in the offline clone.
- Public/auth/payment surfaces use direct pure-English source evidence wherever safely available.
- Inaccessible authenticated and post-payment states are explicitly identified as offline simulations but use a consistent source-grounded design system.
- No source mutation, real enrollment, trial, payment, quiz, review, cancellation, email, or order is performed by the agent.
- No card or account credential data crosses the clone boundary or enters repository artifacts.
- No mixed Chinese/English runtime UI remains.
- No animation is invented; material source animation is reproduced when practical, and the homepage never autoplays.
- The clone runs without remote presentation dependencies and preserves site-33 backend isolation.
- Tests and diagnostics are freshly reported, known differences are honest, and no commit exists before user approval.

## Current Execution Status

- Planning and read-only repository inspection are complete.
- The homepage, Deep Learning specialization, Neural Networks course detail, and Browse landing have source-grounded frontend prototypes in progress.
- The earlier clone-only standalone course Preview route was removed because no directly corresponding source page was observed. Frozen historical records may retain the earlier term as immutable evidence; they do not authorize reintroducing the route.
- No database backup/reset from this plan has run.
- No source authenticated capture from this plan has run.
- No commit is authorized.
