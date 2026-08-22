# Scope expansion recon (2026-08-20) — full-site experience

Human decision: extend from home-only to full-site experience, local
reproducible delivery only (no public deployment).

## Recon findings (read-only browser + captured HTML)

- `/` home — implemented and static-verified clean.
- `/menu` — anonymous route answers the branded 404 view ("Oh no!"); the
  weekly menu surface lives on the home page. Clone reproduces the 404 for
  /menu, or renders the menu surface from frozen weekly data; maintainer
  choice, recorded here as: reproduce 404 to stay faithful to anonymous
  source behavior (data-driven decision, not a code shortcut).
- `/profiles/<slug>` — Next.js SSR shell; full product payload is frozen in
  `__NEXT_DATA__.props.pageProps.structuredData` (name, description,
  nutrition, allergens, rating, image). Deterministic seed: capture each
  weekly + classic flavor profile and freeze its structuredData.
- `/stores` — SSR renders full store list (1092 active stores, 48 metro
  areas) plus search; clone uses a small fixed deterministic store set
  with address/hours (data reduction of entity count only, per
  references/05-implement.md).
- `/order` — landing with Delivery/Pickup/Digital gift cards choices.
- `/order/pickup`, `/order/delivery` — Next.js shells whose order SPA is
  client-rendered; pageProps carry `allActiveStores` (1092) + `metroAreas`
  (48) + `stripePublishableKey` (NEVER persist). Clone implements a local
  deterministic ordering flow: select store -> pick box size -> pick
  flavors -> cart -> contact/pickup details -> review -> simulated payment
  (websitebench local-sandbox) -> confirmation. Zero remote runtime calls.
- `/login`, `/account` — anonymous auth shells, structural-only.
- Cookie consent: source shows a consent dialog; clone omits it and
  documents the omission as a known difference (no consent storage).

## Frozen scope additions (to be written into routes/journeys/checkpoints)

P0: menu browse (home weekly+classic sections), flavor profile detail,
store locator + store detail, pickup order build, delivery order checkout
(simulated), 404.
P1: marketing pages (our-story, catering, giftcards, rewards, allergens,
dirty-sodas), auth shells (login/register/recovery, fail-closed).
P2/omit: franchising careers, press kit, ca/mx/es alternate locales,
merch storefront (external link), videos (byte-mirror or omission).

## Seed data plan

- Weekly flavors: the 6 flavors frozen from home capture (Aug 16-22 week).
- Classic flavors: Pink Sugar, Chocolate Chip (from home capture).
- Flavor profiles: structuredData payload per flavor (nutrition/allergens/
  rating/images) captured from /profiles/<slug>.
- Stores: small fixed deterministic set (e.g. 4-6 stores across metro
  areas) with address/hours from allActiveStores; one dedicated test store
  for the isolation actor.
- Orders: pickup/delivery states with deterministic totals; local-sandbox
  payment with approved/declined/retryable outcomes; local outbox mail.
