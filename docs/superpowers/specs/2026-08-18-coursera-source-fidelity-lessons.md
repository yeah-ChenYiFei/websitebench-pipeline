# Coursera Source-Fidelity Lessons and Preflight Checklist

This document is a mandatory addendum to
`docs/superpowers/plans/2026-08-18-coursera-english-fullstack-reconstruction.md`.
It records the lessons from the Browse-page rework so later implementation
does not regress to plausible but unobserved content.

## Non-negotiable principle

Evidence precedes implementation. A page is not source-faithful merely because
its layout, headings, or card counts resemble Coursera. Every visible title,
card, organization, image, badge, rating, review count, metadata string, link,
order, and major geometry must come from the configured source evidence.

When evidence is incomplete or conflicting, stop and ask the user. Never fill a
gap with a reasonable-looking card, a homepage component, shared Coursera
knowledge, or generated imagery.

## What went wrong on Browse

1. Missing `/browse` sections were initially misclassified as homepage content.
2. The first Playwright walk blocked every non-GET request. Coursera's
   semantically read-only GraphQL queries therefore did not load, leaving a
   truncated page after `Explore roles`.
3. The incomplete source state was not recognized as incomplete, and homepage
   data was reused to make the expected headings appear.
4. Early tests asserted headings and counts but not the identity of each card,
   so invented content could pass.
5. The first visual check used only the standard viewport and did not reproduce
   the geometry in the user's 1490-pixel screenshot.

The unsupported Browse collections and their candidate evidence were removed
before the page was rebuilt from source.

## Source-authority rules

Use the following authority order for each individual route and state:

1. A fresh, read-only Playwright capture of the exact route, locale, viewport,
   actor, and interaction state.
2. A user-supplied screenshot for an A/B-tested, personalized, randomized, or
   otherwise unstable state that Playwright cannot reproduce deterministically.
3. A WACZ only for the routes and states actually contained in that WACZ.
4. Existing clone business behavior only for explicitly offline-simulated
   states; it is not visual or catalog-content authority.

Do not use a homepage WACZ to infer Browse, search, category, course, account,
learning, or checkout content.

## Dynamic-source acquisition

Before declaring a source page complete, compare its visible height, headings,
and card count with the expected page. A suspiciously short page, empty state,
or missing lower collection is evidence of failed acquisition, not permission
to invent content.

For Coursera pages backed by GraphQL:

- Allow only confirmed query operations needed for the page.
- Reject GraphQL mutations.
- Reject forms, enrollment, checkout, review, quiz, cancellation, and payment
  submissions.
- Reject analytics and eventing POST requests.
- Never retain request bodies, headers, cookies, tokens, credentials, or
  authenticated storage.
- Retain only sanitized visible facts and asset provenance.

The Browse repair required these read-only operations:
`BrowseAllDomainComponents`, `BrowseDegreeCollection`,
`CareerRolesCollectionQuery`, `DiscoveryCollections`, and `Search`.

## Per-page evidence matrix

Before production code is written, record all applicable fields:

- Exact route and canonical path
- Viewport, language, actor, and interaction state
- Heading hierarchy and section order
- Complete visible card list
- Provider or institution
- Product type, level, duration, and other metadata
- Badges, rating, review count, and CTA text
- Local destination for every link
- Image and logo source URLs
- Card count, reveal controls, tabs, filters, and empty states
- Container width, column count, card size, image ratio, and gaps
- Full-page screenshot and any material interaction screenshot
- Whether the state is direct source evidence, user-supplied dynamic evidence,
  shared-design-derived, or offline simulation

Implementation must not begin while a high-impact field is unresolved.

## Implementation rules

- Build only routes and states with an observed counterpart.
- Do not copy a component from another route solely because it looks plausible.
- Download observed media and serve it locally; do not substitute generated or
  approximate imagery when the source asset is obtainable.
- Preserve source order and canonical local paths.
- Do not add animation where none was observed. Source animation may be
  reproduced when useful and economical.
- Keep the clone free of runtime remote presentation dependencies.
- Record asset provenance and never retain user screenshots unless explicitly
  required and sanitized.

## Test-first fidelity contract

Write the failing contract before implementing a page or collection. Tests must
assert real consumer-visible identity, not just generic structure.

At minimum, assert:

- Section order within the correct route
- Exact card titles and providers
- Exact local image paths
- Exact canonical local links
- Ratings, review counts, metadata, and badges where visible
- Exact card, skill, logo, and reveal-control counts
- Absence of components known to belong to a different page

Then verify the test fails because the source-backed feature is missing, make
the smallest implementation, and watch it pass.

## Visual verification

Use two levels when evidence warrants them:

1. The project viewport: `1191 x 979`, including a full-page screenshot.
2. The evidence viewport supplied by the user or source capture.

Check geometry rather than relying only on visual impression. For the supplied
Deep Learning Browse collection at 1490 pixels, the verified reference values
were approximately:

- Card: `318 x 391`
- Card image: `300 x 169`
- Column gap: `24`
- Heading-to-card offset: `30`

Browser verification must also report console errors, failed requests, blocked
requests, missing images, and remote runtime references.

## Token- and time-efficient workflow

1. Batch one full Playwright acquisition per route/state and extract headings,
   text, links, images, cards, and geometry together.
2. Diagnose missing dynamic requests before repeating screenshots.
3. Keep screenshots to canonical states and material interactions.
4. Reuse verified source components only when their structure and content model
   match the new route.
5. Avoid image generation, speculative mockups, unnecessary agents, and
   repeated repository-wide searches for source-backed clone work.
6. Present one complete representative page for user review before scaling a
   verified pattern across sibling routes.

## Preflight gate for the next page

No implementation starts until all answers are yes:

- Is the exact route known?
- Is the selected state reachable without source mutation?
- Did the page finish loading its dynamic collections?
- Is the complete section and card inventory captured?
- Are all visible images and destinations identified?
- Are A/B or personalized differences resolved with the user?
- Is the target viewport known?
- Is there a failing source-identity contract ready to guide implementation?

If any answer is no, continue read-only evidence acquisition or ask the user.

## Data Science category correction lessons

The selected Data Science state demonstrated that a single route can expose
materially different anonymous experiments. The retained full-page source
capture, a later anonymous Playwright session, and the user's screenshot each
contained different Trending and degree collections. A newer browser response
was therefore not automatically more authoritative than the user-selected
state.

### Separate the four kinds of card evidence

Treat every card as four independently verified layers:

1. Identity: section, order, title, provider, product type and destination.
2. Metadata: badge, rating, review count, level, duration and credential copy.
3. Media: cover image and provider logo, with provenance for each local file.
4. Geometry: grid width, gap, card height, image ratio and text wrapping at the
   evidence viewport.

Do not accept a card merely because its cover or title matches. The Data
Science correction required exact per-card assertions because collection-wide
membership checks would still pass if providers, links, covers or metadata
were swapped between cards.

### Resolve A/B conflicts field by field

Use the user screenshot for the visible experiment-specific order and artwork,
then use read-only Playwright search or detail surfaces to recover facts hidden
below the screenshot edge, such as canonical links and degree titles. Do not
let a currently reachable but different experiment replace screenshot-visible
facts. Conversely, do not guess hidden titles or paths from the screenshot;
acquire them separately or ask for more evidence.

For this state, Playwright verified the hidden Pittsburgh and Leeds degree
titles and destinations while the screenshot remained authoritative for the
four-card order and covers. This mixed-evidence method is acceptable only when
provenance identifies which source supports each field.

### Prefer original media, and acknowledge crop limits

Media priority for later pages is:

1. Reuse an already verified local copy of the exact source asset.
2. Acquire the exact source media through the configured approved-origin
   browser workflow and retain its source URL.
3. Use a lossless sanitized crop from a user-supplied public screenshot only
   when the exact A/B asset cannot be reproduced or downloaded safely.

A screenshot crop is faithful to that visible state but cannot be sharper than
the screenshot. Never upscale it, apply synthetic sharpening, generate a
replacement, or claim it is an original-resolution source asset. Render it at
or below its captured CSS size and record the crop rectangle. If mild blur is
accepted for the current pass, record it as a known media limitation and move
on rather than spending repeated browser runs on an unstable experiment.

### Measure the grid instead of estimating it

At the supplied `1264 x 1312` viewport, the selected collection used a
`1159px` four-card grid inside the wider page shell, `24px` column gaps,
approximately `271.75 x 325px` Trending cards, and `254 x 143px` (`16:9`)
covers. The apparent width discrepancy came from assuming every collection
filled the shell; the source collection stopped about `17px` before the shell
edge. The Deep Learning grid already encoded this behavior, so Trending and
Online degrees needed the same route-scoped wide-grid rule.

Text wrapping is also geometry. At this viewport, `Discover the Art of
Prompting` and `Generative AI Fundamentals` remain on one line while
`Generative AI for Business Consultants` uses two. A small route-scoped title
font adjustment reproduced this without changing global typography.

### Economical acquisition and verification

- Start with one batched source lookup containing every unresolved identity.
- Use `count` observations before strict attribute observations so a missing
  experimental card does not abort the entire batch.
- Once exact selectors are known, acquire canonical paths together in one
  follow-up run; do not retry random browser contexts hoping for the same A/B
  assignment.
- Inspect existing local media before downloading or cropping duplicates.
- Write one exact per-card identity contract, watch it fail, and then update
  only the card data, optional provider-logo seam and route-scoped CSS.
- Verify both `1191 x 979` and the evidence viewport, including console errors,
  failed or blocked requests, missing images and remote runtime resources.

The completed correction is documented by
`2026-08-18-coursera-data-science-card-identity-design.md`, its implementation
plan, crop provenance, and the final `v9`/wide `v3` Playwright reports. The
accepted remaining limitation is that several screenshot-derived covers are
slightly softer than original-resolution source media.

## Search-page correction lessons

The Deep Learning search-page pass improved card media and responsive behavior,
but the user did not accept the middle content area's width as fully faithful.
That remains an open visual finding. The latest screenshots and passing tests
are diagnostic evidence, not proof that the page has been accepted.

### Width must be solved before card details

The page was refined in the wrong order. Provider marks, title truncation,
metadata order and image ratios were adjusted while the larger content-width
contract was still uncertain. Small card fixes cannot compensate for a wrong
main shell, and they cause rework when the shell later changes.

For the next pass, verify geometry in this order:

1. Browser CSS viewport, screenshot pixel dimensions, device pixel ratio and
   browser zoom.
2. Header shell left edge, right edge and width.
3. AI Overview shell and its two internal columns.
4. `All Results` section and result-grid left edge, right edge and width.
5. Column count, card width, gap and cover height.
6. Only then typography, logos, badges and metadata spacing.

Do not infer CSS width directly from a Windows screenshot's raster width. A
`2559px` image may represent a smaller CSS viewport under display scaling or
browser zoom. Mixing raster pixels, CSS pixels and Playwright's
`device_scale_factor=1` made apparently plausible width comparisons unreliable.
If the screenshot's scale cannot be established from evidence, ask the user
for browser zoom/display scaling before changing `max-width` or breakpoints.

### Measure each horizontal region independently

Coursera does not necessarily use one width for every section. The global
header, AI content, starter-card group, filter row, result grid and footer may
have different caps or gutters. A test that only proves the grid fills the
clone's own shell is circular: the shell itself may be wrong.

Before the next CSS edit, create one compact source-versus-clone geometry table
at the exact review viewport containing literal measurements for:

- viewport width and scale;
- main-shell `x`, width and right edge;
- AI left and right column widths and gap;
- results-grid `x`, width, column count and gap;
- first card width and cover width/height;
- distance from the final card to the shell's right edge.

Derive expected values from the selected source/user evidence, not from the
candidate CSS. Then make one route-scoped width or breakpoint change and rerun
the same measurements. Do not change card typography during that experiment.

### Separate three image-height questions

“The card images are the wrong height” can mean three different defects:

1. Covers in the same row have unequal rendered heights.
2. Every cover has the same height, but the aspect ratio differs from source.
3. The ratio is correct, but the card/grid is too narrow, making every cover
   shorter than the source.

The search-page work initially focused on the first two while the third was
still affected by the unresolved middle-page width. Future diagnosis must
record card width and cover height together; `aspect-ratio: 16 / 9` alone is
not enough.

### Preserve source-state authority without mixing experiments

The completed AI Overview in the user screenshot remains authoritative for the
top section, while retained Playwright captures support result identities and
responsive structure. A current anonymous Coursera A/B state must not silently
replace the user's selected state. Conversely, a different retained experiment
must not determine a breakpoint or control that conflicts with the selected
screenshot without first resolving the conflict.

Record authority per field: copy, card identity, media, geometry and
interaction. Do not label the whole page “source-backed” when those fields come
from different states.

### Lower-token workflow for the next session

1. Read this lessons file and the search-page design once; do not repeatedly
   reread the repository or unrelated plans.
2. Inspect the existing final source and clone screenshots once.
3. Collect all required geometry in one browser run or one small measurement
   script. Avoid repeated screenshot crops when numeric bounds answer the
   question.
4. If raster scale is ambiguous, ask one question immediately instead of
   trying several CSS interpretations.
5. Add one failing geometry regression for the confirmed width contract.
6. Change only the route-scoped shell/gutter/breakpoint responsible for that
   failure.
7. Run the focused test once, then capture the standard and review viewports in
   one batch.
8. Ask for visual review before touching fonts, provider marks or lower-page
   details.

Avoid repeated live-source visits when a current retained capture already
answers the question. Avoid repository-wide searches, image-generation tools,
subagents and broad test suites for a single CSS geometry correction. Keep the
development server stable during CSS/template work and restart it only once
after Python data changes are complete. Do not install or reacquire browser
dependencies until a real browser verification is ready to run.

### Search-page restart gate

Before editing the page again, all of these must be known:

- The exact viewport and scaling used for the user's width judgment.
- Which visible region “middle page” refers to: AI Overview, result shell, grid
  or all three.
- Literal source and candidate left/right bounds for that region.
- The intended column count at the same CSS viewport.
- Whether the existing `1191px` and wide breakpoints remain valid after the
  width correction.

If any item is unknown, ask the user or acquire one bounded read-only
measurement. Do not guess from appearance and do not resume card-detail work.
