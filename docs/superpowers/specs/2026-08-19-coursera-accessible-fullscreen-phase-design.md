# Coursera Accessible Fullscreen Reconstruction Design

## Objective

Complete the source-accessible portion of the Coursera offline clone in
`materials/33` as one coherent phase. Source exploration happens before page
implementation so shared geometry, navigation, content and interactions are
derived once and reused consistently.

This phase uses one primary acceptance viewport: the user's fullscreen browser
CSS viewport, exactly `1692 × 979`. Split-screen, reduced browser windows,
mobile layouts and the earlier `1191 × 979` viewport are not acceptance targets.

## Fixed constraints

- The finished site remains `materials/33`; no second runtime is created.
- Runtime presentation is English.
- The current branch and unrelated dirty work are preserved.
- No commit is made unless the user later authorizes it.
- Source exploration is read-only except for the exact user-authorized act of
  reaching the payment page. No enrollment, trial, payment, quiz, review,
  cancellation, message or other source-side completion is submitted.
- Credentials, cookies, tokens and payment data are never placed in chat,
  repository files, logs, reports, screenshots or retained browser state.
- All clone runtime assets are local; the clone does not proxy or depend on the
  live Coursera site.
- Visible content is reproduced only when the corresponding source page or
  state exists. Plausible but unobserved pages and cards are forbidden.

## Current-phase scope

The following surfaces are reconstructed when they are reachable in the
configured public or empty-account source session:

1. Homepage, shared navigation and source-observed manual promotion controls.
2. Explore navigation, Browse landing and every reachable subject/category
   page required by the original task.
3. Search results, filter controls and the impossible-query recovery state.
4. Deep Learning Specialization detail.
5. Reachable course details: syllabus, instructor, prerequisites, reviews,
   pricing and enrollment options.
6. A public preview or sample lesson only if the source exposes one without
   enrollment. If no corresponding source surface exists, no clone-only page is
   introduced.
7. Sign-in, registration and password-recovery entry surfaces without source
   credential submission, account creation or recovery delivery.
8. Empty-account dashboard, profile, preferences and history states that are
   actually visible after the user logs in.
9. The user-reachable payment page with plan, amount and empty payment fields
   visible. No payment details are entered and no continuation is performed.
10. Signed-out prompts and required-field validation states that can be
    observed safely.
11. Public help/contact and branded not-found recovery.

## Explicitly deferred scope

The original requirements include the following states, but they are deferred
until the user has a suitable enrolled or payment-capable source account:

- enrollment or trial completion;
- checkout review after payment credentials and payment outcomes;
- populated orders, enrollment history or cancellation;
- enrolled lessons and unit navigation;
- quiz, exercise or assignment submission and feedback;
- course resume, bookmarks, progress and completion;
- certificate/completion states;
- rating or review submission.

These requirements are not deleted. They remain a later phase and must not be
silently represented as directly observed source behavior.

## Evidence acquisition

### Public batch

At `1692 × 979`, one WebsiteBench/Playwright walk per route family captures all
needed evidence together:

- canonical route and visible heading hierarchy;
- complete visible section and card inventories;
- text, providers, badges, metadata and destinations;
- image and logo resource URLs;
- main shell, section, grid, card and image bounding boxes;
- menus, tabs, filters, disclosure controls and validation states;
- full-page screenshot plus screenshots only for materially different
  interactions;
- console errors, failed/blocked requests and relevant dynamic-source gaps.

Existing retained evidence is reused when it represents the selected state.
The live site is revisited only for unresolved or stale fields. User-supplied
screenshots remain authoritative for explicitly selected A/B states.

### Authenticated batch

A temporary Playwright browser is opened at `1692 × 979`. The user personally
enters the empty test-account credentials. The agent never receives or records
them. After login, only the reachable empty-account surfaces are walked and
sanitized observations are retained. Visible personal identifiers are excluded
or masked.

The user personally navigates to the authorized payment page and stops before
entering card, wallet or billing credentials. The agent then records only safe
presentation facts and empty-field behavior. The temporary session is closed
after acquisition; its profile or storage state is not retained.

If any requested surface cannot be reached, acquisition stops for that surface,
the exact gap is reported to the user, and no visual details are invented.

## Geometry and shared design system

Width is solved before page details. The source-versus-clone geometry table for
every major route records literal CSS-pixel values for:

- viewport and page scrollbar width;
- shared header and main-shell left/right bounds;
- section-specific width caps and gutters;
- internal columns and gaps;
- grid column count, card width and gap;
- card-cover width, height and aspect ratio;
- footer bounds.

The header, AI/content sections, results grids and footer are measured
independently; they are not assumed to share one container. Candidate tests use
source-derived literal bounds, never the clone shell as its own expected value.

After geometry is fixed, shared typography, navigation, buttons, cards, badges,
logos and footer styles are implemented once. Route-scoped rules cover genuine
source differences. No animation is added where the source has none; observed
animation is optional when it is useful and economical.

## Implementation architecture

- Preserve the generated site-33 backend runtime and integration seam.
- Continue moving route presentation out of coupled inline HTML into focused
  Jinja templates and route data/view-model modules.
- Reuse shared shell components only when source geometry and behavior match.
- Keep public route data explicit and source-backed rather than inferred from
  title heuristics.
- Keep existing deterministic local backend behavior for capabilities already
  implemented, but do not present deferred post-enrollment states in this phase.
- Implement interactions with the smallest same-origin mechanism compatible
  with the existing content-security policy.
- Do not introduce new hash, gate, approval, payment or authentication
  infrastructure.

## Implementation order

1. Freeze the accessible route/state/viewport matrix and evidence gaps.
2. Acquire public evidence in route-family batches.
3. Run the temporary user-assisted authenticated/payment acquisition.
4. Establish the shared fullscreen shell and geometry contracts.
5. Complete public discovery pages: homepage, Explore, Browse and categories.
6. Complete search, filters and no-results.
7. Complete specialization, course detail and any genuinely public preview.
8. Complete anonymous account/access, help/contact and not-found pages.
9. Complete directly observed empty-account and empty-payment states.
10. Connect accessible interactions to the existing backend and repair only
    evidence-backed differences.
11. Run focused verification, then the whole current-phase journey matrix.

## Testing and diagnostic evidence

Each page begins with a failing contract for consumer-visible behavior:

- route, heading and section order;
- exact card/provider/image/link identity;
- visible metadata and controls;
- absence of unobserved components;
- literal fullscreen geometry at `1692 × 979`;
- interaction, validation and recovery behavior;
- no runtime remote presentation dependencies.

After route-level tests pass, WebsiteBench/Playwright replays the current-phase
journeys at the primary viewport. Final checks include frontend/backend tests,
actor isolation where applicable, asset closure, English runtime copy, secret
and payment-data scans, and WebsiteBench static/live diagnostics. Diagnostic
reports remain advisory and do not replace user visual review.

## Token- and time-control rules

- Read the governing design and fidelity lessons once per phase.
- Batch all observations for a route family into one source walk.
- Measure geometry numerically before taking repeated screenshots.
- Reuse exact retained assets and observations rather than reacquiring them.
- Use focused tests during repair; run broad suites only at phase checkpoints.
- Keep the local server stable and restart only after Python/template state
  requires it.
- Ask immediately when a page, A/B state or source authority is ambiguous.
- Present the completed current phase for one consolidated manual review rather
  than requesting approval after every page.

## Completion boundary

This phase is complete when all source-accessible original-task surfaces are
faithfully reachable at the fullscreen viewport, their accessible interactions
work locally, the empty payment page stops before sensitive input, and every
inaccessible post-enrollment requirement is listed as deferred with no false
source-fidelity claim.
