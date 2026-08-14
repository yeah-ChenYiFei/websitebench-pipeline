# Stage 7 implementation contract (durable working notes)

Site: aspca-pet-insurance. Capture: 2026-08-13.aspca-pet-insurance-r1.
All DOM/copy/pixels come only from `source-current/<capture-id>/<state>/<viewport>/page.html`
and mirrored assets under `clone/static/assets/<capture-id>/...` (manifest:
`source-assets/manifest.json`, `runtime_path` maps to `/static/...`). Never fetch
the live site. Zero remote URLs in any shipped file (mirror the tripit audit
regex in `materials/tripit/tools/build_frontend_pages.py`).

## File layout (owners)

- `clone/app.py` — FastAPI composition root (MAIN AGENT ONLY).
- `clone/frontend/pages/*.html` + `clone/frontend/rewrite-report.json` — worker A
  via `tools/build_clone_pages.py`.
- `clone/frontend/quote/{index.html,views/*.html,views-report.json}`,
  `clone/frontend/portal/{index.html,views/*.html}`,
  `clone/static/site/{quote-app.js,portal-app.js}` — worker B via
  `tools/build_funnel_views.py`.
- `clone/backend/{model.json,rating.py,quotes_db.py,schema.py}`, `clone/tests/*`
  — MAIN AGENT ONLY.
- Do not touch `scope/agent-handoff.md`, `prompts/`, site-level
  `backend/runtime.json`.

## Server routes (app.py serves; workers rely on these)

- Frozen pages at source paths: `/`→home, `/pet-insurance-plan/`, `/cat-insurance/`,
  `/dog-insurance/`, `/why-us/`, `/research-and-compare/`, `/about-us/`,
  `/support/` (confirm exact support path from capture meta), 404→not-found page.
- `GET /quote/` → quote shell; hash routes `#/start` (default), `#/plans`,
  `#/checkout`, `#/quote-search`, `#/add-a-pet`; `GET /quote/views/{name}` →
  fragment files from `clone/frontend/quote/views/`.
- `GET /portal/` → portal shell; `#/login` (+forgot/register views);
  `GET /portal/views/{name}` likewise.
- `/static` → clone/static (assets mirror + `site/` tree for new JS).
- `GET /healthz` → `{"ok": true, "site_id": "aspca-pet-insurance"}`.
- `/external/{slug}` — external-link boundary page (tripit pattern).

## JSON API contract (backend implements; worker B's JS calls)

- `POST /api/quotes` {species,name,zip,age,gender,breed,email} → 201
  {quote_id, eligible, pet, rates} | 422 {errors:{field:message}}.
- `GET /api/quotes/{quote_id}` → quote + pets + selections.
- `POST /api/quotes/{quote_id}/rate` {limit,deductible,reimbursement,
  preventive:null|"basic"|"prime"} → {monthly, preventive_monthly, provenance}.
- `POST /api/quotes/{quote_id}/pets` (add-a-pet, same pet fields) → 201.
- `POST /api/quotes/{quote_id}/enroll` {contact fields, frequency:
  "Monthly"|"Annually", agree_terms:bool, paperless:bool} → 201
  {policy_number}. ZERO payment fields; server rejects any card/cc/cvv/etc key.
- `GET /api/quotes/search?email=&zip=` → resume match | 404 (worker B: confirm
  the exact resume-form fields from the quote-resume capture and record them in
  views-report.json; the API accepts those fields as query params).
- `POST /portal/api/login|forgot-password|register` → observed validation
  outcomes only; member area always unavailable (anonymous-only clone).

## Rating model (from source-current/<capture-id>/rating-claims.json)

Anchor cells (provenance directly-observed, cumulative walk):
tiers at deductible $500 / 80% reimb: 2500→$8.48, 5000→$16.74, 10000→$23.19 /mo;
custom base 5000/500/80 = $16.74; deductible 250 → $23.65; then reimb 90 →
$30.83; annual-limit re-select 5000 → no delta; preventive Basic $9.95, Prime
$24.95 per month, billed separately (never folded into the plan price).
Model: monthly = round_half_up(base[limit] * ded_factor * reimb_factor, 2),
ded_factor(250)=23.65/16.74, reimb_factor(90)=30.83/23.65. Factors for any
additional UI options (worker B reports the full radio inventories) are
marked `derived` in clone/backend/model.json, never claimed observed.

## Behavior evidence sources

- Start-form validation msgs: `quote-start-validation/desktop` (empty-submit).
- Ineligible trigger: `quote-ineligible/desktop/meta.json` interaction block.
- Email pattern: ng-pattern attr in quote-start capture (TLD<=4 rule).
- Customize radios: control names annualDeductiblel2 / reimbursementPercentl2 /
  annualLimitl2 (values like Deductible250, Copay10, Limit5000).
- Checkout: 15 contact fields, Monthly/Annually, agreeTerms, paperless; no
  payment inputs (source stops before payment; do not invent any).
- Portal: portal-login, portal-login-validation, portal-forgot-password,
  portal-register captures.

## Known-difference policy for this phase

Marketing pages ship as post-render frozen DOM with all script blocks dropped
(third-party trackers excluded from runtime; first-party widget JS not
re-executed to keep the frozen visual state deterministic). Record widget
motion (carousel auto-advance etc.) as a known difference; the frozen visual
contract binds home.{desktop,tablet,mobile} full-region at threshold 0.995.
