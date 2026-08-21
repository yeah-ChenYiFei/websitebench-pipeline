# Coursera WACZ Homepage Reconstruction Design

## Purpose

Reconstruct only the public Coursera homepage captured in the user-provided
WACZ archive as a maintainable, network-closed frontend. The result is an
independent WebsiteBench site and does not modify or depend on the existing
full Coursera clone under `materials/33`.

The archive remains an external source input at
`/mnt/c/Users/15332/Downloads/my-archiving-session (1).wacz`. It is not copied
into the repository.

## Observed source boundary

The WACZ is an ArchiveWeb.page 0.16.2 data package of approximately 11.4 MB.
Its page list contains two captures of `https://www.coursera.org/`, both with
the same title and identical extracted page text. It contains no captured
search, course detail, authentication, account, checkout, or learning route.

The resource index contains the homepage HTML and its visual dependencies as
well as analytics, advertising, and telemetry traffic. Only resources needed
to render the public homepage are eligible for the reconstructed frontend.
Telemetry, advertising pixels, analytics scripts, request bodies, session
state, cookies, headers, and other private or operational data are excluded.

## Chosen approach

Build a sanitized static reconstruction from the archived public content and
visual resources. This is preferred over embedding a WACZ replay runtime,
because the deliverable should be ordinary maintainable frontend code, and
over trimming the existing `materials/33` clone, because that would retain
unrelated catalog, account, learning, and payment behavior.

The new site lives at `materials/coursera-wacz-home`. Its browser-facing
implementation is plain HTML, CSS, JavaScript, and local visual assets. A
minimal repository-compatible local serving seam may be included for browser
diagnostics, but it does not provide business APIs or persistent state.

The WACZ-rendered homepage is the sole visual authority. The reconstruction
does not substitute generic symbols, invented illustrations, approximate card
content, or independently designed visual treatments where the archived page
provides visible evidence. Archived presentation assets are used directly when
recoverable. When a visible decorative asset is not independently recoverable,
it is redrawn as a local vector or CSS asset against the archived rendering so
that shape, color, scale, crop, and placement remain source-grounded.

## Page structure

The only supported content route is `/`. It reconstructs the archived English
homepage in this order:

1. The dark audience navigation bar.
2. The Coursera brand/navigation row with Explore, Degrees, search, sign-in,
   and join affordances.
3. The two-column promotional area visible in the archive.
4. The position indicators and controls for the promotional content.
5. The three-column trending-course area and its archived cards.
6. The three learning-pathway cards, including their pale blue-lilac
   backgrounds and career, business, and degree illustrations.
7. The category and trending-search regions.
8. The four learner-purpose choices, including their blue square pictograms,
   borders, spacing, and source-sized alignment.
9. Remaining homepage sections present in the archived page text and visual
   resources, followed by the public footer.
10. The footer privacy and cookie-preference affordances. The replayed default
   state does not display a fixed privacy banner.

The primary fidelity viewport is `1191 x 979`. The layout also reflows safely
on narrow screens without adding mobile-only business behavior that was not
captured.

Fidelity review compares every visible homepage region against the WACZ
rendering, not only the hero. Typography, spacing, dimensions, borders,
backgrounds, image crops, icons, section order, and responsive behavior are all
in scope for repair. Any remaining mismatch must be a demonstrable archive or
machine limitation and must be recorded honestly; implementation convenience
is not an acceptable known difference.

## Promotional switching interaction

The promotional area is not time-driven. Two cards are visible together by
default, matching the captured desktop state. There is no autoplay timer.

Users can explicitly switch the displayed pair with previous/next controls or
the position indicators. Switching updates the selected indicator and keeps
the chosen pair until another user action. Controls expose accessible labels,
support keyboard activation, maintain a visible focus state, and respect
reduced-motion preferences. Tests use a clock or an observation interval to
confirm that the content never advances by itself.

## Other interactions and uncaptured routes

Homepage-only interactions may include opening a navigation menu, submitting
the visible search control, expanding FAQs, and opening or closing a local
cookie-preference explanation. They remain client-side and deterministic.

Links that originally target uncaptured routes must not imply that those
routes were reconstructed. They either remain on the homepage, target a local
homepage section, or expose a concise inline notice that the supplied archive
contains only the homepage. There are no synthetic search results, login,
registration, course, or checkout screens.

Cookie-preference controls only alter the local presentation. They do not load
trackers, send consent, or create durable account data.

## Asset and network policy

Eligible archived images and other presentation assets are extracted into the
new site's local static asset directory. Filenames are stable and descriptive;
source query strings and sensitive metadata are not retained. Third-party
analytics and advertising resources are omitted even if present in the WACZ.

At runtime, the page makes no requests to Coursera or any other remote origin.
All CSS, JavaScript, images, icons, and fonts are served locally. Missing
decorative resources are recreated locally from the archived visual evidence
rather than replaced with unrelated fallback glyphs or a remote URL.

## Backend capability decision

Persistent accounts, authentication, password recovery, transactional email,
checkout, payments, orders, and databases are all out of scope. No backend
capability pack or payment adapter is needed. The site has no credentials,
secrets, cookies containing identity, or persistent learner data.

## Verification strategy

Implementation follows test-driven development. Automated checks cover:

- the single supported homepage and its critical archived text and regions;
- the two-card promotional default state;
- explicit previous, next, indicator, and keyboard switching;
- absence of automatic switching over time;
- local cookie-preference disclosure without a network effect;
- accessible names, focus behavior, and responsive layout markers;
- complete local asset closure and absence of remote runtime URLs;
- browser rendering at the primary `1191 x 979` viewport;
- the archived illustrations on all three learning-pathway cards; and
- the archived blue pictograms and geometry on all four learner-purpose
  choices.

Repository WebsiteBench diagnostics are run for the new site after its
declarative scope is present. Their report is diagnostic evidence, not an
acceptance or release gate. Final acceptance is based on the implemented
scope, tests, captured evidence, and explicit review of known differences.

## Explicit non-goals

- Reconstructing any route other than the homepage.
- Replaying or preserving analytics, advertisements, tracking, or consent
  transmission.
- Reusing authenticated state or private data from the archive.
- Implementing Coursera search, enrollment, learning, account, or payment
  behavior.
- Deploying or publishing the reconstruction publicly.
- Changing the existing `materials/33` clone.
