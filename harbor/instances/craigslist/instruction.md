# Rebuild Craigslist (Toronto housing offline clone)

## Task

Starting from the provided reference URL, reproduce the **Craigslist
classifieds experience** as a complete, runnable full-stack application. The
reference is an offline instance of the site; you may explore it freely with
your browser tools, but you never see its source code.

The interface must be **pure English**. Stateful behaviour must be implemented
in a **real backend** (accounts, sessions, postings, favorites, saved
searches, replies). The frontend should reproduce the reference's look and
behaviour as closely as possible (target: 90%+ visual fidelity, judged by
runtime comparison).

## Scope: journeys that must work

1. Public entry page → primary navigation → housing section; the heading and
   canonical path are visible.
2. Post a sublet listing: one-bedroom near Toronto Annex, $2400/month,
   July–August, furnished. The published detail view must visibly match every
   condition in the task.
3. Browse/search classifieds by location and category.
4. Refine a search with price, neighborhood, posting date, and
   category-specific filters.
5. Open a listing: description, photos, price, location, reply/contact
   options.
6. Save a search / bookmark a listing.
7. Account/login flows needed to manage postings.
8. Create a new classified post in a chosen category and location.
9. Enter title, price, description, attributes, contact method, map/location.
10. Upload/reorder/remove photos.
11. Preview a post and reach the publish/confirmation step.
12. Edit, renew, repost, or delete an existing post.
13. Reply/contact flow for an existing listing.
14. Posting/account settings and reporting/flagging controls.
15. Search for `zzzz-no-match-websitebench` → no-results message + route back
    to housing.
16. Sign-in entry (verify fields only; never submit real credentials).
17. Registration entry (verify identity fields, terms links, verification
    guidance; do not create an account).
18. Password recovery entry (verify reset-address field, validation guidance,
    return-to-sign-in; do not send).
19. Account history for housing records: newest item exposes status, detail,
    edit/cancel options, route back.
20. Empty required fields or signed-out actions → inline validation or a
    permission prompt identifying what must be corrected.
21. Public help/support/contact guidance reachable; no private account data.
22. Non-existent deep link → branded not-found preserving navigation.
23. End-to-end: from the public entry, post the sublet from task 15 (after
    signing in with the seeded poster account) and confirm the detail view
    matches every condition.

## Reference facts (public)

- Seeded accounts: `poster@example.com` and `seeker@example.com`, password
  `Websitebench1!`.
- The canonical fixture listing id `1000001` ("1BR near Annex - furnished
  sublet Jul-Aug") is present in the reference data.
- Time-based rules (e.g. the five-minute per-email registration limit) use a
  controllable clock; do not implement hidden real-time waits.

## Output contract

- A complete repository under `/app` with `frontend/`, `backend/`, `README.md`,
  `Dockerfile`, `docker-compose.yml`, a deterministic seed/reset, and an
  environment-variable template.
- One command start; foreground process; honours `HOST`, `PORT`, `DATA_DIR`,
  `SEED`, `TZ`; answers `GET /__websitebench/health` with `{"status":"ok"}`.
- Fully offline at runtime: no remote images, fonts, scripts, maps, APIs, or
  telemetry; no iframes/proxies to the target; refresh and re-login keep
  state.
- Create an executable root `compile.sh` (no arguments) that produces a root
  `executable`; the executable stays in the foreground, binds `$HOST:$PORT`,
  writes runtime data only beneath `$DATA_DIR`, uses `$SEED` and `$TZ`, and
  handles SIGTERM. `GET /__websitebench/health` must return exact JSON
  `{"status":"ok"}` with HTTP 200. No compile-time or runtime dependency
  downloads, no public network access.

## Forbidden

- Accessing the reference source code, source maps, JS bundles, or browser
  caches.
- Copying reference assets wholesale into the workspace.
- Proxying or iframing the reference; runtime network access to it.
- Client-only fake state (pages that lose data on refresh).
- Hard-coding evaluation fixtures or seeding secrets into client code.

When you believe the rebuild is complete, run the candidate contract's
compile and start steps and confirm `/__websitebench/health` before finishing.
