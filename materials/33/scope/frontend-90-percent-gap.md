# Site 33 — frontend similarity: visual + structure status (2026-08-22)

Two independent diagnostic axes track the frontend's consistency with the
live Coursera site at the 1692x979 acceptance viewport, pure-English UI.

## Axis 1: per-region pixel similarity (SSIM, diagnostic)

Measured by `materials/33/clone/measure_visual_regions.py` against the
frozen 2026-08-21 source rasters (`scope/desktop-visual-comparison-current.json`).

| checkpoint | region | SSIM now | SSIM before | gap driver |
|---|---|---|---|---|
| home | header | 0.796 | 0.796 | minor chrome |
| home | promotion rail | 0.739 | 0.858 / 0.62 | campaign art rotates on live site |
| home | primary content | 0.619 | 0.622 | dynamic card content + layout |
| browse | header | 0.801 | 0.801 | minor |
| browse | primary content | 0.673 | 0.673 | dynamic card content |
| search | header | 0.758 | 0.758 | minor |
| search | filters | 0.524 | 0.403 | now aligned: persistent left sidebar + chips |
| search | results | 0.482 | 0.518 | card-level content of frozen results |
| specialization | header | 0.671 | 0.544 | audience bar height fixed to 40px |
| specialization | hero | 0.761 | 0.760 | minor |
| course | header | 0.794 | 0.794 | minor |
| course | hero | 0.783 | 0.783 | minor |
| login | header | 0.729 | 0.726 | minor |
| login | auth surface | 0.722 | 0.571 | standalone white page + centered dialog |
| help | header | 0.903 | 0.456 | blue Learner Help Center hero rebuilt |
| help | primary content | 0.797 | 0.673 | hero + article chrome |
| not-found | header | 0.940 | 0.540 | minimal header, no audience bar |
| not-found | recovery | 0.931 | 0.925 | coral illustration + centered text |

Overall region average: 0.746 (was 0.666 at the start of the alignment round).

## Axis 2: structure/content/function consistency (primary acceptance)

Measured by `materials/33/clone/measure_structure_consistency.py` against
the source/clone frontend-spec pairs (`scope/frontend-specs/`).

| page | structure score | headings (text/level) | controls | data points |
|---|---|---|---|---|
| home | 0.530 | 0.39 / 0.96 | 0.64 | 1.00 |
| browse | 0.594 | 0.56 / 0.96 | 0.70 | 1.00 |
| search | 0.504 | 0.43 / 0.89 | 0.75 | 1.00 |
| course | 0.646 | 0.54 / 0.95 | 0.68 | 1.00 |
| specialization | 0.647 | 0.50 / 0.94 | 0.71 | 1.00 |
| login | 0.535 | 0.80 / 0.00* | 0.79 | 1.00 |

Overall structure consistency: 0.576.

*login heading levels differ (h1 vs h2) for identical text; text presence
matches at 0.80. Level drift is a markup choice, not missing content.

## Known limits (kept honest)

- **Dynamic content**: the live site personalizes search results, home
  cards, and rotates promo campaigns. Frozen rasters from 2026-08-21 and
  the clone's frozen data can never match a later live capture pixel-for-
  pixel; SSIM is a diagnostic reference, not an acceptance gate.
- **Heading text drift**: home card titles rotate; the clone's static card
  set differs from any single live moment. Structure (levels, section
  identity, control inventory) is what the clone targets.
- **Kernel sandbox unavailable** (`[Errno 95]`, `x32_unavailable: False`):
  live diagnostic and Harbor compile/worker tests cannot run in this
  environment; they are documented as environment-blocked, not failures.
- **Visual similarity is diagnostic-only**: passing or failing it never
  decides rights, merge, or deployment.
