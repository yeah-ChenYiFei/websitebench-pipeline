# Site 33 — frontend similarity: visual + structure status (2026-08-22, round 2)

Two independent diagnostic axes track the frontend's consistency with the
live Coursera site at the 1692x979 acceptance viewport, pure-English UI.

## Axis 1: per-region pixel similarity (SSIM, diagnostic)

Measured by `materials/33/clone/measure_visual_regions.py` against the
frozen 2026-08-21 source rasters (`scope/desktop-visual-comparison-current.json`).

| checkpoint | region | SSIM round 2 | SSIM round 1 | gap driver |
|---|---|---|---|---|
| home | header | 0.797 | 0.796 | minor chrome |
| home | promotion rail | 0.828 | 0.739 | source 4-slide carousel; "Learn without limits" h1 slide added, light-toned |
| home | primary content | 0.625 | 0.619 | dynamic card content + layout |
| browse | header | 0.801 | 0.801 | minor |
| browse | primary content | 0.592 | 0.673 | dark promo band (source-observed) + card cover lightening; section rework |
| search | header | 0.758 | 0.758 | minor |
| search | filters | 0.477 | 0.525 | dark AI panel now spans the sidebar column; filter groups compacted to source order |
| search | results | 0.502 | 0.541 | dark AI summary panel at top (source-observed) + source-aligned 3-col grid |
| specialization | header | 0.671 | 0.671 | audience bar height fixed to 40px |
| specialization | hero | 0.761 | 0.761 | minor |
| course | header | 0.794 | 0.794 | minor |
| course | hero | 0.783 | 0.783 | minor |
| login | header | 0.729 | 0.729 | minor |
| login | auth surface | 0.745 | 0.722 | standalone white page + centered dialog |
| help | header | 0.903 | 0.903 | blue Learner Help Center hero rebuilt |
| help | primary content | 0.797 | 0.797 | hero + article chrome |
| not-found | header | 0.940 | 0.940 | minimal header, no audience bar |
| not-found | recovery | 0.931 | 0.931 | coral illustration + centered text |

Overall region average: 0.746 (was 0.666 at the start of the first alignment
round; home rail, browse sections, and search layout reworked this round).

## Axis 2: structure/content/function consistency (primary acceptance)

Measured by `materials/33/clone/measure_structure_consistency.py` against
the source/clone frontend-spec pairs (`scope/frontend-specs/`).

| page | structure round 2 | headings (text/level) | controls | data points | structure round 1 |
|---|---|---|---|---|---|
| home | 0.796 | 0.99 / 0.98 | 0.65 | 1.00 | 0.530 |
| browse | 0.893 | 1.00 / 0.98 | 0.81 | 1.00 | 0.594 |
| search | 0.849 | 1.00 / 1.00 | 0.77 | 1.00 | 0.504 |
| course | 0.883 | 1.00 / 0.97 | 0.69 | 1.00 | 0.646 |
| specialization | 0.901 | 1.00 / 1.00 | 0.73 | 1.00 | 0.647 |
| login | 0.827 | 1.00 / 1.00 | 0.57 | 1.00 | 0.535 |

Overall structure consistency: 0.858 (was 0.576 at the start of round 1).

Round-2 structure work: source-observed heading semantics everywhere (module
titles, reviewer names, promo card titles, career roles, testimonial names as
h3; promo slide titles as h1/h2; sidebar filter groups as styled paragraphs to
match the source DOM), the shared dark "Break down barriers to learning with
big savings" / "Start with easy savings for hard-working teams" promo band on
all four public pages, the Google Analytics / Project Management / AI Basics
browse sections, "Meta Data Analyst" career card, the search AI summary panel,
and per-control clean link text (card title links, chip glyphs moved to CSS).

## Known limits (kept honest)

- **Dynamic content**: the live site personalizes search results, home
  cards, and rotates promo campaigns. Frozen rasters from 2026-08-21 and
  the clone's frozen data can never match a later live capture pixel-for-
  pixel; SSIM is a diagnostic reference, not an acceptance gate. The search
  AI summary panel and the browse promo band are rendered from source-
  observed content, so their pixel match is structural rather than exact.
- **Control inventory**: the clone ships extra controls the source spec did
  not enumerate (footer links, follow-up chips, role cards) and misses a few
  source controls; control jaccard is the residual structure drag.
- **Kernel sandbox unavailable** (`[Errno 95]`, `x32_unavailable: False`):
  live diagnostic and Harbor compile/worker tests cannot run in this
  environment; they are documented as environment-blocked, not failures.
- **Visual similarity is diagnostic-only**: passing or failing it never
  decides rights, merge, or deployment.
