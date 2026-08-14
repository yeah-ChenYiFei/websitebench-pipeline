# Reconstruct the offline pet-insurance website

Rebuild, in `/app/repo`, a fully offline clone of a pet-insurance marketing
and quote site. Inspect the browser-only reference website that the harness
exposes to you; your reconstruction is scored by a deterministic verifier —
hidden exact-state browser/API tasks, region-level RGB SSIM visual
checkpoints, and trusted CI/CD platform checks. Only task completion
contributes to reward; visual and CI/CD scores are report-only.

## Scope to reconstruct

- **Marketing pages** (server-rendered, frozen content): home `/`,
  `/pet-insurance-plan/`, `/cat-insurance/`, `/dog-insurance/`, `/why-us/`,
  `/research-and-compare/`, `/about-us/`, `/about-us/contact-us/`. Unmatched
  paths return a 404 page.
- **Quote funnel** at `/quote/` — a hash-routed single-page app. A visitor
  enters pet details (species, name, age, gender, breed, zip, email), submits,
  and receives tiered plan rates for the pet by name. Plans can be customized
  by annual-limit / deductible / reimbursement options with the displayed
  monthly price updating from a deterministic rate table. Client-side
  validation renders a captured error-summary state for missing or invalid
  fields (note: the email pattern caps the TLD at 4 characters). The journey
  continues through plan selection into a checkout page that collects contact
  and billing-frequency details only — **the site contains no payment step
  and must reject payment-card-like fields**.
- **Quote JSON API** backing the funnel under `/api/quotes` — create, fetch,
  rate re-quotes, add additional pets, search/resume by email+zip, and enroll
  (idempotent; issues sequential policy numbers). Validation errors are
  structured JSON with per-field messages; unknown resources are JSON 404s.
- **Member portal** at `/portal/` — hash-routed SPA with login, login
  validation, forgot-password and register views. Anonymous validation
  surfaces work; member account access is unavailable in this offline clone
  and the portal API answers with explicit refusal messages.
- `GET /healthz` — JSON readiness probe naming the site id.
- Security headers on every response (CSP `default-src 'self'`, nosniff,
  frame deny, no-referrer) and a same-origin static asset mirror under
  `/static/`.

## Rules

- Follow the runtime contract in `README.md` (`deploy.sh`, `$PORT`,
  `$WEBSITEBENCH_DATA_DIR`, `/healthz`, foreground, SIGTERM, restart
  persistence).
- Everything must be same-origin and offline; do not fetch from the real
  site, CDNs, fonts or analytics at runtime.
- Deterministic output only: frozen clock `2026-08-13T12:00:00Z`, stable
  ids, no randomness in rendered content.
- Match the reference visually at desktop (1440x900), tablet (1024x768) and
  mobile (390x844) widths; animations are disabled during checks.
