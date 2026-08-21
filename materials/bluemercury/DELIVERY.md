# Bluemercury offline clone delivery — r33

## Identity and safety boundary

- Assignment `20`; assignee `薛皓文`; same-id site/instance `bluemercury`.
- Formal trace preserved verbatim: `[781] On the Bluemercury website, purchase a skincare product, add to cart, and proceed to checkout`.
- Source access was anonymous/read-only. No source login, cart mutation, checkout, order, payment, email, credential/profile reuse, push, PR, or deployment occurred.
- Candidate checkout accepts only a frozen synthetic identity/address and `local-sandbox`; it cannot accept card, CVV, bank, wallet, real email, shipment, or live-payment data.
- `LOCAL CLONE` is absent as requested. Local checkout retains an explicit synthetic/no-real-payment safety notice.
- Rights/redistribution status is `unknown`; this local evaluation package conveys no publication or redistribution authorization.

## Functional priority coverage

- P0: home; three working Hero campaigns; primary navigation; source-derived collection/category routes; search success/zero states; all local PDPs; five-image C E Ferulic gallery; variants; quantity; add to bag; empty/populated cart; synthetic checkout; approved confirmation; declined/retryable sandbox outcomes.
- P1: local registration/login/logout/account, `@example.test` identity boundary, salted `scrypt-v1` hashes, wishlist, filters/sort, mobile navigation, carousel controls, local store/info pages, restart/reset, and owner isolation.
- Catalog: `387` unique searchable/openable local products; `382` have localized primary images. Captured campaign collections are complete: Fall `34/34`, M-61 `12/12`, all `46/46` with local images; Chantecaille is `108/108`. Skincare reports its `127` local records separately from Source's visible `(1707)` reference count.
- Catalog and Harbor are distinct: candidate catalog has 387 products; Harbor v2 has exactly 200 evaluation cases.
- Unavailable by design: source account/authenticated states, source cart/checkout/order/payment, real email, live payment, and public deployment.

## Visual, state, role, and viewport coverage

- Final frozen pairs: current home, Chantecaille collection, and C E Ferulic PDP at desktop `1440×900` and mobile `390×844`.
- Final independent unlabeled review: `6/6 Pass` — all three routes at both viewports passed ordinary human comparison.
- Roles: anonymous Source/candidate; local synthetic account is candidate-only.
- Exercised candidate states include Hero navigation, brand carousel scroll, collection grid, PDP gallery, variant/quantity, wishlist, empty/populated cart, local auth success/failure, filters/sort, mobile menu, local checkout, and approved/declined/retry outcomes.
- This supports delivery for the six frozen route/state/viewport pairs; it is not a claim of pixel identity for every route or dynamic Source state.

## Source and candidate trails

- Anonymous Source evidence: `artifacts/browser/source-live-r3/`; collection JSON: `source-assets/2026-08-20.playwright-r3/fall-beauty-products.json` and `m61-perfect-products.json`.
- Final candidate screenshots/DOM/reports: `artifacts/browser/candidate-current-r33/`.
- Final journey: `artifacts/browser/current-interactions-r33/report.json`; home → M-61 → Fall → Chantecaille → Bestsellers scroll → PDP → add to bag → cart → local checkout.
- Formal ledger: `artifacts/trajectory/interaction-ledger.json`. Source establishes anonymous visible pages/product facts only; mutations are explicitly candidate-only.
- r33 authoring occurred on 2026-08-21 Asia/Shanghai (2026-08-20 UTC); capture directory names are batch identifiers, not precise local wall-clock timestamps.

## Asset closure

- Manifest `source-assets/manifest.json`: `412/412` assets verified; `28,991,554` bytes.
- Missing Source/runtime copies `0`; Source/runtime/manifest SHA-256, byte, or MIME mismatches `0`.
- Runtime remote references `0`; secret findings `0`.
- Localized media includes Source fonts, desktop/mobile Heroes, Chantecaille brand/catalog, base catalog, Fall/M-61 campaign images, and five C E Ferulic gallery images.
- Provenance is first-party Bluemercury/Shopify CDN. Evidence capture does not establish redistribution rights.

## Backend runtime and isolation identity

- Contract `backend/runtime.json`; schema `websitebench.site-backend-runtime.v1`; site ID `bluemercury`.
- Database: per-site `DATA_DIR/bluemercury.sqlite3`; served from `materials/bluemercury/artifacts/runtime/served-data/bluemercury.sqlite3`.
- Sessions are Host-only, Secure, HttpOnly, SameSite=Lax and bind auth/cart/order to the local identity.
- Mail is local outbox with `@example.test` policy. Payment is USD `local-sandbox`; `stripe_test=null`; no payment credential fields retained.
- Semantics pass: owner order 200, foreign owner 404, restart persistence 200, reset 200, unauthorized/wrong-token/cross-origin reset 403, reset order 404, sensitive retention false.

## Harbor v2 status

- Same-id paths: `harbor/sites/bluemercury/` and `harbor/instances/bluemercury/`; r33 is synchronized to `harbor/instances/bluemercury/public/`.
- `compile.sh → executable`, exact health `{"status":"ok"}`, and 15/15 trusted runners pass.
- Cases: total `200`; `T1=20`, `T2=165`, `T3=15`; T2 `L1=35`, `L2=50`, `L3=80`; missing `0`.
- Still `status=draft`, `reference_observations=pending`, `scorable=false`. Candidate observations were not substituted for Reference.
- OpenCLI remains unavailable (`opencli` not on PATH); prior bag/catalog replay evidence remains `opencli-unavailable`, `0/6` per profile.

## Commands and exit codes

- `D:\annaconda\python.exe -m pytest -q tests/test_site.py`: `25 passed`, exit `0`.
- Six strict r33 Playwright route captures: each HTTP 200; external/failed/console findings `0`; marker false; each exit `0`.
- r33 Playwright journey: status `pass`, eight meaningful steps; external/console/bad response/hard failure `0`; marker false; exit `0`. Raw `failed_requests` has four local lazy-image `net::ERR_ABORTED` cancellations during immediate navigation; the independent collection capture loads them and has zero failures.
- `python materials/bluemercury/tools/finalize_assets.py`: assets `412`, missing Source `0`, exit `0`.
- `websitebench-offline-clone verify ... --section static`: `diagnostic_status=clean`, assets `412/412`, remote references `0`, secrets `0`, exit `0`.
- `verify_runtime_semantics.py`: all isolation/sandbox checks passed, exit `0`.
- Native Windows Harbor seed attempt: exit `1`, WinError 193 because `compile.sh` is not Win32; rerun through WSL passed.
- WSL `verify_harbor_seed.py`: compile/health and 15/15 runners pass, exit `0`.
- `websitebench-harbor validate ...`: valid draft, exactly 200 cases, exit `0`.
- Historical full in-place D: verify: exit `1`, `diagnostic_status=incomplete` because WSL Landlock/DrvFS could stat but not open sibling `backend/runtime.json`; isolation was not weakened. Historical exact ext4-copy full verify was clean with 11 checkpoints, exit `0`; this is not represented as in-place clean.

## Changed paths

- `materials/bluemercury/clone/app.py`, `static/site.css`, `static/site.js`, `tests/test_site.py`
- `materials/bluemercury/clone/static/*-products.json`, `*-image-map.json`, `collection-memberships.json`, and `static/assets/`
- `materials/bluemercury/tools/import_chantecaille_catalog.py`, `build_collection_memberships.py`, `finalize_assets.py`, `capture_local_route.py`, `verify_current_interactions.py`
- `materials/bluemercury/source-assets/2026-08-20.playwright-r3/`, `source-assets/manifest.json`
- `materials/bluemercury/artifacts/browser/source-live-r3/`, `candidate-current-r33/`, `current-interactions-r33/`
- `harbor/instances/bluemercury/public/`; `materials/bluemercury/DELIVERY.md`

## Known differences and unavailable evidence

- Chantecaille breadcrumb is `Makeup` in frozen Source and semantically `Chantecaille` in candidate; mobile Bestsellers is about 15 px lower.
- Desktop PDP financing is about 9 px higher and the final rating star differs slightly. Mobile PDP badge is about 8 px displaced; fourth/fifth thumbnail subjects differ locally although all controls/images work.
- Source's overlapping announcement, empty personalization grid, and broken/empty desktop thumbnails were transient failure states and were not copied.
- Below-fold PDP editorial/review/clinical content and some non-core footer pages are local functional summaries, not full visual copies. Not every footer route has an independent Source checkpoint.
- Source authenticated/cart/checkout/payment/order evidence is unavailable because mutations were prohibited. Harbor independent Reference observations/visual fixtures are also unavailable.
- Finalizer automatically repairs managed extras/root assets; other catalog corruption is detected by verify but not auto-repaired. Current 412 assets are clean.

## Blockers and delivery judgment

- No technical blocker remains for the implemented local P0/P1 journey. Tests, strict Playwright checks, 6/6 blind review, runtime semantics, asset closure, Harbor compile/health, and independent code review pass.
- Harbor completion is blocked by missing maintainer-approved Reference observations; it remains draft/non-scorable.
- Public release is blocked because rights are unknown and publication is unauthorized.
- Recommendation: submit r33 as the **final local functional candidate plus visual-review package**. Six frozen visual pairs pass; Harbor/reference, rights, source-mutation, and broader-route differences remain outside that claim.

## Package

- Archive: `deliverables/bluemercury-assignment-20-r33-final-local-candidate.zip`.
- Excludes runtime SQLite, caches, browser profiles, credentials, bytecode, and temporary process data. Size/SHA-256 are reported after packaging.
