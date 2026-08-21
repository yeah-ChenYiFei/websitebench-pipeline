# Site 33 — known differences and evidence limits

## Evidence boundary

- Current English public and authenticated-unenrolled evidence is retained under `source-evidence/2026-08-20-learner-expansion/`. Enrolled `Neural Networks and Deep Learning` evidence, including the ten observed Week 1 assignment questions, is retained under `source-evidence/2026-08-20-enrolled-learning/`. Both use the `1692 × 979` viewport; screenshots and JSON reports are sanitized and contain no credentials, cookies, storage state, personal identifiers, or entered payment values.
- The current source `/login` and `/signup` both resolve to the same email-first “Log in or create account” surface. The clone now preserves that same-page background and keeps local registration as a hidden backend seam for existing offline lifecycle tests.
- The authenticated source account, learner dashboard empty tabs, purchases recommendations, settings tabs, Updates empty state, and empty checkout display were directly observed. The enrolled Deep Learning program card, course module home, Welcome lesson shell, Grades, Notes, Messages, Resources, Course Info, assignment entry, and all ten in-progress assignment questions were also directly observed. Source submission/result feedback, completed course/certificate, rating/review submission, cancellation, and populated message states remain deferred.
- Current source `/account-recovery` and `/reset-password` are branded 404 pages. The true password-recovery route is behind the post-email login step and was not submitted or inferred.
- Source login completion, enrollment completion, recovery submit, and checkout submit were not directly verified and must not be inferred from the clone's working local flows.
- An authenticated checkout display was observed only far enough to record public-facing facts: Deep Learning / DeepLearning.AI, a 7-day trial, `CN¥196/mo` after trial, and `CN¥0` due today. No source trial, payment, order, or enrollment submission occurred.

## Intentional offline reconstruction

- Accounts, registration verification, inbox, pre-enrollment settings, progress fixtures, bookmarks, reviews, quiz results, history, cancellation, checkout, lesson notes, assignment drafts, scoring, and result feedback are clone-local simulations backed by the generated WebsiteBench runtime. They are not claims about source-side persistence or behavior.
- The assignment question wording, option order, diagrams, timer rules, and controls come from direct source evidence. The source assignment was never answered or manually submitted, so the private answer key and explanations are explicitly clone-local course-knowledge rules and are not claimed to be source-verified.
- The clone records the observed CNY trial facts through its generated `local-sandbox` ledger: a zero-value CNY activation today, seven trial days, and CNY ¥196/month renewal metadata. It never receives card data, charges a payment method, or contacts a payment provider.
- The source's anonymous login was captured as an email-first modal overlay over the invoking page. The clone keeps the invoking page as the background and no external identity provider is contacted.
- The Deep Learning AI overview and the `zzzz-no-match-websitebench` no-match recommendation/recovery behavior are deterministic clone-local search behavior. The public capture establishes search context and filters, but does not verify source AI output or an impossible-query response.
- Help evidence is limited to the public article and recovery guidance in the anonymous capture. The clone's account-aware help and recovery actions do not submit to a source service.
- The Welcome player reproduces the observed lesson shell but does not stream the source video. Messages remains a read-only observed empty state; the clone does not invent message sending.

## Visual differences

- Source frames include dynamic state that the clone intentionally does not recreate: cookie-consent banners, chat side panels, restored scroll positions, and source-served promotional photography. The clone uses local CSS illustrations and deterministic content instead.
- The source 404 frame is a simplified English recovery view. The clone keeps its shared navigation and explicit browse/search recovery links to satisfy the human trace, so this checkpoint is structurally rather than pixel-identical.
- Public screenshots are evidence aids only. They do not establish redistribution rights, legal authorization, or a visual acceptance gate.

## Owner-authorized real stylesheets

- The human owner directly authorized (2026-08-21) using real Coursera stylesheets **inside the offline evaluation clone only** — never external redistribution. The authorization is recorded in `scope/real-css-authorization.json`.
- Real CSS for the home, browse, search, course/specialization, and authentication surfaces is captured under `source-assets/coursera-css/`, fully localized (fonts and images rewritten to local `assets/`, embedded base64 fonts kept inline), with **zero remote runtime references** and registered in `source-assets/manifest.json` (76 assets, static diagnostics clean).
- The clone runtime ships the layer at `clone/static/coursera/`. Clone pages keep their local deterministic structure and content; the real CSS provides the source design-system layer (fonts, colors, components) that page markup increasingly adopts.
- A pinned CDS variable layer (`cds-variables.css`, values measured from the live page such as `--cds-color-blue-600: #227af9`) makes the real component rules (e.g. `.link-button.primary`) effective. Home and browse CTAs use the real button classes; the clone's primary blue now references the real CDS variable instead of the local `#0056d2`.
- Current automated visual baseline (2026-08-21, 1692x979, SSIM vs live source; run with `capture_source_visuals.py` + `capture_desktop_visuals.py` + `compare-visual`): home 0.62–0.86, browse 0.67–0.80, search header 0.76 / filters 0.43 / results 0.52, specialization 0.54–0.76, course 0.78–0.79, login 0.57–0.73. The blue alignment moved search results across the 0.5 region threshold.
- Search/browse result cards are client-rendered CDS components on the live site (`cds-ProductCard-*`), while the captured search-v2 bundle carries the older `rc-ProductCard` rules; the clone therefore keeps its own deterministic card markup rather than adopting the stale legacy card classes. Adapting to the current CDS card component would require capturing the client-rendered component stylesheet. The live authentication modal likewise renders from a component bundle that the captured `authentication.css` does not contain, so the clone keeps its local deterministic auth surface.
- Visual similarity diagnostics remain diagnostic-only and never become a rights, license, or redistribution gate.

## Frontend specification and consistency

- The shared `frontend-spec-extract` tool (`websitebench-offline-clone tools frontend-spec`) extracts a sanitized page specification — headings, semantic regions, controls, forms, data points, and style references — from any approved-origin page. It is how the real page, the interaction logic, and the backend data contract stay aligned.
- Source and clone specifications for the key routes are archived under `scope/frontend-specs/` (`*.source.json` / `*.clone.json`).
- `tests/test_content_backend_consistency.py` enforces that rendered copy (prices, order status, progress, course content) equals the backend state, and that no legacy Chinese copy leaks into any public route. Legacy unreferenced Chinese helpers were removed from `app.py`.


## Frontend reconstruction (2026-08-21)

- Screenshot-built UI removed: the My Learning empty state and greeting used
  an authenticated evidence screenshot cropped by CSS; both are now local SVG
  illustrations, and no page references screenshot rasters as UI.
- The home promotion switcher is a real sliding carousel: a flex slide track
  translates by 100% per panel with a 480ms ease transition, five-second
  autoplay, manual previous/next controls, and aria-hidden for the inactive
  panels. Backend behavior is unchanged.

## Diagnostics

- Static WebsiteBench diagnostics are complete with 76/76 verified assets, zero remote runtime references, and zero detected secrets.
- Live diagnostics were not completed because the Harbor candidate sandbox returned `[Errno 95]` for its sandbox runtime. This is an environment limitation, not a page-test failure; local Playwright/browser suites remain the applicable verification evidence.
- One historical home footer geometry assertion remains 17px outside its 16px tolerance (`source-browse-footer-secondary`); it predates this learner expansion and is reported rather than changed opportunistically.
