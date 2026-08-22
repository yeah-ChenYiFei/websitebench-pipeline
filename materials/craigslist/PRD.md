# Craigslist — Public PRD (product description for the reproduction task)

> Public product description: states the product scope and the behaviours that
> MUST be implemented. It deliberately does not describe internal technology.
> Every hidden evaluation requirement is derivable from this document, the
> task contract, or normal browser observation.

## 1. Product

Craigslist is a classified-advertisements platform organized by **region** and
**category**. Users browse, search, and filter community postings; open detail
pages to inspect description, photos, price, location, and reply options;
create and manage their own postings; and manage them later through an
account.

This task reproduces the **Craigslist experience for housing** with a focus on
the Toronto region, plus the account, search, posting, and support surfaces
that complete the journey.

## 2. Required behaviours

### 2.1 Entry and navigation

- A public entry page with the craigslist wordmark, a global search box, a
  region index, and a category index (housing, for sale, …).
- A region page per curated region; the Toronto region is fully populated.
- A housing section listing subcategories (apartments / housing for rent,
  sublets & temporary, rooms & shares, housing wanted, office & commercial,
  parking / storage, real estate for sale, vacation rentals) with counts.
- Primary navigation from the entry page reaches the housing section, whose
  heading and canonical path are visible.

### 2.2 Search and discovery

- Search by free text across titles, descriptions, and neighborhoods.
- Browse by location (region) and category (housing subcategories).
- Refine a search with: price (min/max), neighborhood / postal code, posting
  date (posted today), and category-specific filters (bedrooms, housing
  type), plus posted-by owner/dealer, has-image, sort (newest, price), and
  list/grid views.
- Deterministic results: the same query returns the same results.
- A search with no matches (for example `zzzz-no-match-websitebench`) shows a
  clear **no-results message** and a route back to available housing.

### 2.3 Listing detail and contact

- A listing detail page shows: title, price, neighborhood, posted date,
  description, photos (gallery with previous/next and thumbnails), attributes
  (bedrooms, baths, square feet, housing type, furnished, laundry, parking,
  air conditioning, available date), post id, posted-by owner/dealer, and a
  map/location area.
- Reply/contact flow: name, email, optional phone, message; inline
  validation; anonymous relay so the responder's address is never shown to
  the poster; the message reaches the poster's mailbox.
- Save/bookmark a listing (requires sign-in) and save a search (requires
  sign-in); both persist for the account.
- Report/flag a listing with a reason and optional note.

### 2.4 Accounts

- Registration: email, password, confirm password, terms links, and email
  verification guidance; the same email may register at most once per
  five-minute window; an existing email cannot register twice.
- Sign-in: email + password; wrong credentials show an error; sign-out
  invalidates the session.
- Password recovery: enter the account email; a reset code is delivered to
  that email; single-use expiring codes; the flow never reveals whether an
  email exists.
- Sessions persist across refresh; a logged-out user returns to the
  sign-in/permission prompt for account-only actions.

### 2.5 Posting

A multi-step create-a-posting wizard: choose category and location
(region + neighborhood), enter title, price, postal code, housing attributes,
description, contact method (email/phone), upload/reorder/remove photos
(optional), preview exactly as the detail page will look, then publish with a
confirmation naming the post id.

- Required fields validate inline (title, price, description, postal code,
  contact).
- A published posting is immediately visible in its category listing and in
  matching search results.
- An account may edit, renew, repost (new post id), or delete its own
  postings from account history; deleted postings leave search results and
  their detail page shows a removed notice.
- Only the owner may manage a posting; others receive a permission prompt.

### 2.6 Support and recovery

- Public help/support/contact entries reachable from the footer: posting
  help, account help, avoid-scams & fraud guidance, and a contact form —
  none of which expose private account data.
- A non-existent deep link renders a branded not-found view that preserves
  primary navigation and offers a route back to housing.

## 3. Test data

Seeded offline data includes a deterministic Toronto housing catalog
(sublets, apartments, rooms, real estate, a vacation rental, and a small
for-sale set) and two seeded accounts:

- `poster@example.com` / `Websitebench1!` — account that owns seeded postings
- `seeker@example.com` / `Websitebench1!` — a second isolated account

The catalog includes the canonical fixture posting id 1000001: "1BR near
Annex - furnished sublet Jul-Aug", $2400/month, The Annex, available
July 1 – August 31, furnished.

## 4. Out of scope

- Live external integration: no real email, no real payments, no external
  maps, no third-party network calls. All effects are local and simulated
  truthfully.
- Full multi-region corpus: other regions render the region shell; only
  Toronto carries a populated catalog.
- Discussion forums, jobs/services verticals: category shells only.
