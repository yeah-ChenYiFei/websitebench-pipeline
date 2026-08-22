# Coursera Live Homepage and Inline Login Design

## Authority and scope

This repair replaces the rejected first-version homepage in `materials/33` with the current public Coursera homepage observed on 2026-08-19 at the sole acceptance viewport `1692 × 979`. The new read-only Playwright evidence under `materials/33/source-evidence/2026-08-19-accessible-fullscreen/source-home-login-current-state-v2/` overrides the older WACZ homepage state for this route. Other already-reconstructed route families remain unchanged.

The source homepage uses a main content shell approximately `1344px` wide with a left edge near `174px`. It does not use the clone's current shared `1151px` homepage cap. The header, carousel rail, content sections, purpose panel, testimonials, FAQ, and footer retain independent source geometry where measured.

## Homepage structure

The homepage is rebuilt in the current source order:

1. Two-tier public header.
2. Wide horizontal promotional rail with explicit user controls.
3. `New and popular` discovery groups.
4. Job-ready career collection.
5. Current promotional pair.
6. Leading partner chips.
7. Career, business, and degree pathways.
8. Category chips.
9. Google Career Certificate collection.
10. Trending searches.
11. AI skills collection.
12. `What brings you to Coursera today?` panel with four compact controls rather than four equal-width stretched columns.
13. Career roles, learner outcome, testimonials, FAQ, legal note, and complete source footer.

Cards, providers, labels, images, links, and section copy come only from the current source walk or retained decisive source evidence. Lazy-loaded areas are acquired by a single controlled PageDown walk before implementation. Unresolved cards remain absent or in an honestly observed loading state; they are never invented.

## Inline login behavior

The public header's `Log In` control opens an accessible same-document dialog without changing the current URL or replacing the current page. The current page remains visible beneath a non-animated dimmed backdrop. `Join for Free` may continue to expose the separately required registration surface, but must not change the login behavior.

The login dialog matches the observed first step:

- approximately `424px` wide and centered near the top third of the `1692 × 979` viewport;
- heading `Log in or create account`;
- source subtitle, Email field, blue Continue button, separator, and Google/Facebook/Apple choices;
- organization sign-up, terms/privacy, learner-help, and reCAPTCHA guidance;
- no Password field in the initial DOM state;
- close returns to the unchanged page and URL.

After a valid synthetic local email is continued, the local clone may reveal a second password step in the same dialog and submit through the existing generated backend integration. No source credential, external identity flow, or remote request is introduced. Direct `GET /login` remains HTTP 200 and renders the homepage with the same dialog already open, preserving journey 16 without restoring a standalone login page.

## Implementation boundaries

- Keep `materials/33/backend/runtime.json` and the generated `websitebench.site_backend` seam unchanged.
- Use local HTML, CSS, JavaScript, images, and fonts only.
- Add no animation not observed in the source.
- Do not alter historical journey identity or captured artifacts.
- Do not commit, push, or merge.
- Preserve all unrelated dirty work.
- Use TDD for the width, section identity, inline-dialog, URL-preservation, staged-password, close, and direct-entry contracts.

## Verification

The source and clone run the same `1692 × 979` Playwright scenario. Structured checks cover current route, dialog role, visible email field, absent initial password field, provider choices, and local network closure. Geometry tests assert the `1344px` homepage shell and measured dialog bounds. The full site-33 tests, visual tests, sensitive-data scans, and WebsiteBench diagnostics run after focused tests pass.
