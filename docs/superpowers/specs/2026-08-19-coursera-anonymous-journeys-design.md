# Coursera Anonymous Journeys Reconstruction Design

## Decision

Complete the signed-out portions of the 23 frozen Coursera journeys before
redesigning authenticated, enrolled-learning, history, or checkout states.
Work remains journey-driven: a page or state is implemented only when one of
the frozen journeys reaches it or when it is necessary for safe recovery.

## Authority and viewport

Current live Coursera is the authority for publicly reachable presentation.
The acceptance viewport is `1692 x 979` CSS pixels in an English, signed-out
browser session. Each route family uses one frozen Playwright evidence set so
content from rotating anonymous sessions is not mixed. The historical WACZ and
older clone screens may explain provenance, but they do not override current
live evidence.

Source exploration is read-only. It does not submit authentication,
registration, enrollment, recovery, review, quiz, or payment actions. No
credentials, cookies, browser profiles, personal identifiers, card data, or
source-side effects are retained.

## In-scope signed-out surfaces

The current stage covers:

- the public homepage and primary navigation;
- Browse and one fully source-backed representative subject page, initially
  `/browse/business`;
- existing subject routes required for safe catalog navigation, without a
  claim that every route is a pixel-identical independent reconstruction;
- search results, visible filters, and the impossible-query no-results state;
- the Deep Learning Specialization and publicly inspectable course details;
- a public preview only if the current source exposes a real anonymous preview;
- the same-document login dialog, registration entry, and password-recovery
  entry without submitting identity data;
- signed-out enrollment and required-field validation with no mutation;
- public help/contact guidance and branded not-found recovery.

The representative Business category page is reconstructed from its own
current evidence. Its titles, providers, images, links, labels, ordering, and
section structure are explicit route-owned data. Records are never borrowed
from another category to fill an unresolved position.

## Deferred surfaces

The following existing local routes are not redesigned or accepted as current
source-fidelity work in this stage:

- account creation completion and onboarding;
- signed-in dashboard and enrolled-course collections;
- paid or free track completion and checkout review;
- enrolled lessons, quizzes, assignments, bookmarks, progress, and completion;
- learner preferences, ratings, certificates, and account history.

These routes may remain operational for compatibility, but their current UI is
not presented as a reconstruction of current Coursera. They receive a separate
evidence and design pass later. Real payment credentials and production effects
remain forbidden.

## Frontend structure

Each public route family keeps its own source-backed view model and template.
Shared chrome is limited to elements that are actually common in the captured
source, such as the audience bar, primary header, search entry, login trigger,
and footer. Route-specific cards are not generated from a shared plausible
catalog list.

At `1692 x 979`, principal shells, column counts, card media dimensions, and
vertical section positions are measured from the frozen evidence. Local raster
assets preserve the observed crop and ratio. Manual controls are implemented
where the source has them; no additional animation is introduced.

## Interaction and error boundaries

Public navigation and filters are local and deterministic. An unavailable
source preview remains absent. Enrollment actions while signed out expose the
observed permission or correction prompt and perform no enrollment. Login,
registration, and recovery entries may be inspected and dismissed without
submitting data. Unknown routes retain branded navigation back to Browse and
search.

## Verification

For each route family:

1. Capture one sanitized current-source route/state set at `1692 x 979`.
2. Freeze exact visible identities and local asset mappings before styling.
3. Test heading, canonical path, card order, links, image loading, and required
   signed-out interactions.
4. Capture the local candidate with the same scenario and inspect the full-page
   result for evidence-backed differences.
5. Run the anonymous journey matrix, full site tests, secret/network-closure
   checks, and the repository diagnostic.

Machine reports remain diagnostic. Human review determines visual acceptance.
No commit, push, deployment, real account operation, enrollment, or payment is
part of this stage.
