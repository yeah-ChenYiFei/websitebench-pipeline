# Craigslist Benchmark Task Contract (task_contract.md)

> Web2Code2Web task protocol for the **Craigslist** task. This contract freezes
> what the agent receives, what it must produce, and what is forbidden. It is
> the benchmark-level companion to `PRD.md` (public product description) and
> `candidate-contract.md` (build/runtime contract).

## 1. Agent inputs

| Input | Value |
| --- | --- |
| `target_url` | The reference site URL provided by the benchmark runner (an offline instance of this clone's reference build; do not depend on the public `https://craigslist.org`). |
| `public_prd` | `PRD.md` in this directory. |
| Test accounts | Seeded accounts are created by the reference fixture: `poster@example.com` and `seeker@example.com`, password `Websitebench1!`. New registrations work through the local mail outbox. |
| Browser tools | A controlled browser-use gateway (accessibility tree + page semantics; no source maps, JS bundles, or browser-cache access). |
| Budgets | Declared per task in the site manifest (`agent_budget`). |
| Output protocol | See section 3. |

## 2. Task statement

Reproduce the **Craigslist classifieds experience** as a runnable full-stack
application. The following journeys must work end to end (this list is the
task's frozen acceptance scope; the hidden verifier only tests behaviours that
are observable from this list, the PRD, or normal browsing):

1. Open the public entry page and use the primary navigation to reach the
   housing section; verify the destination heading and canonical path are
   visible.
2. Post a sublet listing: one-bedroom near Toronto Annex, $2400/month,
   July–August, furnished. Confirm the resulting list/detail view visibly
   matches every condition in the task.
3. Browse/search classifieds by location and category.
4. Refine a search using price, neighborhood, posting date, and
   category-specific filters.
5. Open a listing and inspect description, photos, price, location, and
   reply/contact options.
6. Save a search / bookmark a listing.
7. Use account/login flows needed to manage postings.
8. Create a new classified post in a chosen category and location.
9. Enter title, price, description, attributes, contact method, and
   map/location.
10. Upload/reorder/remove photos in a post.
11. Preview a post and reach the publish/confirmation step.
12. Open an existing post and edit, renew, repost, or delete it.
13. Use the reply/contact flow for an existing listing.
14. Review/manage posting/account settings or reporting/flagging controls.
15. Search for `zzzz-no-match-websitebench`, or apply an impossible public
    filter, and verify a no-results message plus a route back to available
    housing records and actions.
16. Open the sign-in entry; verify the email field and available password
    choices; return without submitting credentials.
17. Open the registration entry; verify the visible identity fields, terms
    links, and verification guidance; do not create an account.
18. From the sign-in surface open password recovery; verify the reset-address
    field, validation guidance, and return-to-sign-in link; do not send a
    reset message.
19. With seeded offline data present, open account history for housing
    records; verify the newest item exposes its status, detail, edit or
    cancellation options, and a route back to the relevant collection.
20. Open an action with required fields empty or while signed out; verify
    inline validation or a permission prompt identifies what must be
    corrected.
21. Open the public help/support/contact entry; verify a user can reach
    guidance for housing records, account access, and failed actions without
    exposing private account data.
22. Open a non-existent deep link; verify a branded not-found or recovery view
    preserves primary navigation and provides a safe route back to housing
    records and actions.
23. Starting at the public entry, complete task 15 (post the sublet listing)
    and confirm the detail view matches every condition.

## 3. Output protocol

The candidate must be a complete, self-contained repository:

```text
/app
  frontend/       # UI sources
  backend/        # server sources (real business logic, not static pages)
  README.md       # run instructions
  Dockerfile
  docker-compose.yml
  seed/           # deterministic data seed / reset script
  .env.example    # environment variable template
```

Requirements:

- installs and compiles automatically from a clean environment;
- starts with one command and stays in the foreground;
- exposes `HOST`, `PORT`, `DATA_DIR`, `SEED`, and `TZ` configuration and
  answers `GET /__websitebench/health` with exact JSON `{"status":"ok"}`;
- does not depend on the target site or any external network at runtime;
- state can be initialized and reset deterministically (`seed` and reset);
- test accounts and test data are reproducible.

## 4. Judgement rules

- Correctness is judged by **runtime product behaviour** — the same initial
  state plus the same user actions must produce the same pages, feedback,
  state changes, and final business results. Code similarity is not scored.
- Stateful journeys must be backed by a real backend: registration, login,
  post CRUD, favorites, saved searches, reply relay, and persistence across
  refresh and re-login.
- The reference site is offline during evaluation; iframes, reverse proxies,
  remote screenshots, or runtime access to the target site are hard failures.
- Compile/startup failure is a hard failure; a missing core journey scores
  zero for that journey.
- The five-minute-per-email registration limit and any time-based rules use
  the same controllable clock configuration in reference and candidate.

## 5. Forbidden / anti-cheat

- Reading reference source code, source maps, JS bundles, or browser caches.
- Copying reference front-end assets wholesale; exporting target resources
  into the code workspace.
- Proxying, iframing, or fetching the target site from the candidate.
- Static-page-only front ends that lose state on refresh.
- Hard-coding evaluation fixtures, account passwords into client code, or
  randomizing inputs that the PRD declares deterministic.

## 6. Time mechanism

All time-based rules (registration window, posted-today, renewal timestamps)
use a **controllable clock**: the reference and the candidate expose the same
environment override (`WEBSITEBENCH_CRAIGSLIST_CLOCK`, ISO-8601) and the same
registration-window override
(`WEBSITEBENCH_CRAIGSLIST_REGISTRATION_WINDOW_SECONDS`), so tests never wait
real minutes.
