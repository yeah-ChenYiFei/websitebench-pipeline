# Coursera Public-First Reconstruction Design

## Decision

Rebuild the Coursera clone in stages. The first implementation stage covers
the current anonymous public experience at the acceptance viewport of
`1692 x 979`. Login-dependent and payment-dependent states remain in the
overall scope, but do not block the public rebuild.

## Source authority

The homepage uses one frozen, current-live Coursera capture as its authority.
The August WACZ is historical reference only and must not provide homepage
card identities, ordering, copy, providers, destinations, or images.

The capture is English, logged out, read-only, and made with one temporary
browser session. The page is fully scrolled and allowed to load before the
homepage inventory is frozen. Every homepage section records its order and
each visible card records its exact title, provider, labels, destination,
image mapping, and source rectangle. A missing record remains unresolved; it
is never replaced with a plausible card from another route.

## Stage boundaries

Stage 1 implements the public journeys: home, Browse, category pages, search
and filters, no-results recovery, publicly inspectable course details,
public help/support, signed-out enrollment validation, and not-found recovery.
The source homepage remains logged out.

Stage 2 implements the required local authentication shells: inline login,
registration, password-recovery entry, and the generated local auth seam.
Opening login from the header remains same-document and preserves the page
under the dialog. This stage does not require source credential submission.

Stage 3 implements local-account and seeded-learner journeys: dashboard,
track selection, sandbox checkout review, lessons, quiz feedback, progress,
preferences, and seeded history. Payment uses the local sandbox only; no
card number, live payment, external enrollment, mail, or other production
effect is allowed.

## Frontend architecture

The homepage is rendered from an explicit source-backed inventory rather than
one generic card factory. Each source section owns its card template because
Coursera uses different layouts, badges, metadata, and image ratios across
sections. The page shell, promotional rail, discovery collections, pathway
groups, purpose panel, testimonials, FAQ, and footer are separate regions.

At `1692 x 979`, the primary content shell resolves to the measured source
width of approximately `1344px` with independent overflow rails where the
source has them. The purpose panel uses four compact source-sized controls,
not four equal-width stretched columns. No animation is added unless the
source visibly uses it; manual carousel controls are retained where the source
provides them.

Login is a same-document local dialog. The initial state exposes the source
email field, Continue action, provider choices, terms/help text, and no
password field. A synthetic local email may reveal the second password step;
all authentication remains local and uses the generated backend contract.

## Verification

Before styling refinements, tests assert ordered section identities and exact
decisive card identities. Geometry tests then assert the measured shell and
purpose-panel bounds. Source and clone are compared at the same viewport by
route, headings, card identities, links, image loading, dialog behavior, and
region screenshots. Full site tests and the repository diagnostic remain
advisory evidence; they do not replace human acceptance.

No implementation files are changed and no commit is created by this design
decision.
