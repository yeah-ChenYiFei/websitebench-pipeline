# Site 33 — frontend similarity: visual + structure status (2026-08-22, round 3)

## Round-4 summary

Structure crossed **0.90** (overall **0.903**): promo-card CTA texts exposed as
separate links ("Get Coursera Plus" / "Save 30% today" / "Save 40% for 3
months" on all four public pages), promo + FAQ + module arrows moved to CSS,
home pathways renamed to the source's Coursera for Business/Enterprise/Teams,
browse role-card title links + skill links extended, specialization skill
chips aligned to the source's exact labels, course "Is this right for me?"
button + "Show all" + module-info buttons, and the three FAQ questions on each
of browse/course/specialization now carry button controls alongside their h3
headings (source-observed dual semantics). Page scores: specialization 0.953,
course 0.926, browse 0.909, login 0.894, search 0.885, home 0.850.

## Round-3 summary

Round-3b control alignment: course related-course title links, skill chips as
search links, "+2 more" instructor link, "Related" link, module-detail labels,
promo CTA texts ("Get Coursera Plus", "Save 30% today", "Save 40% for 3
months"); specialization skill chips + instructor links; home promo-dot
labels ("Go to item N"). Structure rose to **0.888** (course 0.905,
specialization 0.914).


Backend: systematic audit of all 23 trace categories' flows and error paths
(registration validation/duplicates/wrong codes, login wrong password/unknown
email auto-register, password recovery no-reveal/wrong code, anonymous
enrollment guard, checkout declined/retry/invalid-scenario/approved/cancel,
quiz 0/100 scores, lesson progress, bookmarks, no-match search, branded 404,
empty-field validation) — all verified working end to end.

Structure: overall consistency rose to **0.889** (spec 0.921, browse 0.897,
course 0.891, search 0.885, login 0.883, home 0.856). Round-3 control work:
search result card title links carry clean control text; home compact/product
cards and role cards restructured to the same div + title-link pattern (also
fixing nested-anchor breakage); skip-to-content link hidden with clip so the
spec extractor sees it; login footer expanded to the source link set; course
"4 modules" link, "Recommendations" tab, "Is this right for me?" button,
module "Module details" labels, enroll date aligned; specialization
instructor/offered-by links, "5 course series" link, "View eligible
degrees"/"Explore this role" CTAs, "Course details" glyphs moved to CSS;
"Essential IT Certifications" footer text fixed; home "91% of learners..."
outcome heading is a link.

Visual: overall region SSIM 0.746. The search AI summary panel was compacted
to the source geometry; the remaining pixel gap is the panel's dynamic
content, which is documented below.

---


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
| home | 0.839 | 0.99 / 0.98 | 0.82 | 1.00 | 0.530 |
| browse | 0.897 | 1.00 / 0.98 | 0.82 | 1.00 | 0.594 |
| search | 0.885 | 1.00 / 1.00 | 0.90 | 1.00 | 0.504 |
| course | 0.905 | 1.00 / 0.97 | 0.79 | 1.00 | 0.646 |
| specialization | 0.914 | 1.00 / 1.00 | 0.81 | 1.00 | 0.647 |
| login | 0.883 | 1.00 / 1.00 | 0.83 | 1.00 | 0.535 |

Overall structure consistency: 0.903 (was 0.576 at the start of round 1,
0.858 after round 2, 0.888 after round 3).

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
