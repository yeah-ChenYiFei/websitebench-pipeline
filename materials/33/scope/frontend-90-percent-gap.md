# Site 33 — frontend 90% similarity gap analysis (2026-08-21)

Goal: >= 90% visual similarity (SSIM) to the live Coursera site at the
1692x979 acceptance viewport, pure-English UI. Current automated baseline:

| region | SSIM | gap driver |
|---|---|---|
| home promotion rail | 0.858 | content (raster banners vs live campaigns) |
| home header | 0.796 | minor chrome |
| course hero / browse header | 0.78-0.80 | minor |
| home primary content | 0.622 | cards: content + layout |
| browse primary | 0.673 | cards: content + layout |
| search header | 0.758 | minor |
| search filters | 0.430 | panel structure + labels |
| search results | 0.518 | **content mismatch + card layout** |
| specialization header | 0.544 | live page layout differs |
| login auth surface | 0.571 | modal structure + copy |

## Root cause: content mismatch, not styling

The live site is client-rendered and algorithm-personalized. Searching
"deep learning" returns Google AI / Google Data Analytics certificate
cards (duplicated per card type), while the clone shows its keyword-matched
catalog. Home recommendations, promo campaigns, and course data are all
dynamic. SSIM compares pixels, so identical styling with different content
still scores low.

## Path to 90%+

1. **Content freeze**: capture each target page's rendered DOM (titles,
   providers, ratings, image URLs) at the same moment as the source
   screenshot; download and localize images; render the clone from the
   frozen data. This removes the dominant pixel difference.
2. **Layout alignment**: real search cards are ~255-335px wide starting at
   x=158 with a multi-column grid; align clone grid/column/gap/font metrics
   per region.
3. **Per-region loop**: capture -> compare -> fix -> measure, using the
   automated baseline scripts (capture_source_visuals.py +
   capture_desktop_visuals.py + compare-visual).

## Constraints

- Source screenshots go stale as the live site changes; freeze the data
  and the screenshot from the same capture run and keep them as the
  reference pair.
- Client-rendered components (cds-ProductCard, auth modal) have no
  capturable stylesheet; rebuild their visual contract locally.
- Visual similarity is diagnostic-only and never a rights/merge gate.
