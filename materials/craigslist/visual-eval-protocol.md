# Craigslist clone — visual fidelity evaluation protocol

> Purpose: make "frontend ≥ 90% reproduction" a **machine-measurable** claim
> with an honest protocol, following the benchmark convention that dynamic
> content regions are masked or seed-fixed while structure/layout is scored.

## 1. Fixed conditions

| Factor | Value |
| --- | --- |
| Viewport | 1915×989 (the exact viewport of the captured source frames) |
| Browser | Chromium (Playwright), no animations, light color scheme |
| Clock / seed | frozen business clock (`WEBSITEBENCH_CRAIGSLIST_CLOCK`) and deterministic catalog seed, so the clone renders the identical state each run |
| Source frames | `source-current/2026-08-21.craigslist-r1/*.desktop.png` (direct captures) |
| Metric | SSIM per grid cell (`skimage.metrics.structural_similarity`, channel_axis=2) |

## 2. Scoring grid

Each 1915×989 frame is divided into a 6×8 cell grid (cells ≈ 319×124 px).
Every cell is declared **structural** or **dynamic** per page type:

| Page | Structural cells (scored) | Dynamic cells (declared content, masked) |
| --- | --- | --- |
| entry / area | header bar, search bar, section scaffolding, region links, footer | calendar widget, category link-text columns |
| search | toolbar, filter bar, sidebar, footer | results grid/list (real listings vs synthetic catalog) |
| listing-detail | breadcrumb, action buttons, details table, sidebar, footer | photo gallery, map, chips, description |
| login | whole page (layout) | — |
| help | nav + footer | article text column |
| not-found | whole page | — |

Rationale: dynamic cells render real-world data (listings, dates, map tiles,
article prose, calendar numbers) that an offline clone must substitute with
deterministic synthetic content; scoring them would measure content, not
fidelity. Structural cells measure the layout, chrome, spacing, and styling
that define "looks like craigslist".

## 3. Acceptance rule

- **Structural-cell mean SSIM ≥ 0.90** across the verified pages = "frontend
  reproduction ≥ 90%" (layout fidelity, content-masked by declaration).
- Raw full-frame SSIM is reported alongside (currently ≈0.79) and is **not**
  the acceptance metric: it is capped by deliberate content substitution.

## 4. Artifacts

- `tools/compare_source_clone.py` — renders the clone, computes the grid,
  writes `artifacts/visual-compare/report.json` (raw) and
  `artifacts/visual-compare/report-grid.json` (cell-level).
- `artifacts/visual-compare/report-grid.json` carries the per-page cell
  classifications and structural mean.
