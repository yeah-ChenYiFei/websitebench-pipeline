# Coursera Data Science Card Identity Design

## Authority

The user screenshot `屏幕截图 2026-08-18 194359.png` is authoritative for
the selected `1264 x 1312` Data Science experiment. Current anonymous
Coursera sessions expose a different A/B state, so they may supply exact
metadata and canonical paths but must not replace the screenshot-visible
card order or artwork.

## Correction

- Replace `Trending now` with these four cards in this order:
  `Introduction to AI`, `Generative AI for Business Consultants`,
  `Discover the Art of Prompting`, and `Generative AI Fundamentals`.
- Preserve the exact screenshot-visible providers, ratings, review counts,
  levels, product types, durations, and `Free Trial` badges.
- Replace `Online degrees` with Northeastern University, University of
  Colorado Boulder, University of Pittsburgh, and University of Leeds in
  that order. The source-verified titles are `Master of Science in Data
  Analytics Engineering`, `Master of Science in Data Science`, `Master of
  Data Science`, and `Master of Science in Data Science (Statistics)`.
- Use lossless, presentation-only crops from the supplied public screenshot
  for covers that are absent from the retained source assets. Record crop
  geometry and source provenance without retaining the full screenshot.
- Use existing local Google, IBM and Northeastern marks where they match.
  Use small sanitized screenshot crops for provider marks not otherwise
  present locally.
- Use source-verified internal paths. No card may fall back to a generated
  search URL when its canonical source destination is known.

## Code Boundary

`data_science_page.py` remains the single source of card facts. The existing
Jinja macro gains an optional `provider_logo` field so only evidence-backed
logos render as images; unrelated cards retain their current fallback mark.
No layout redesign or animation is part of this correction.

## Verification

- A source-identity HTTP test must fail against the current wrong cards before
  production changes.
- The test must assert exact order, providers, ratings, metadata, internal
  links, local cover paths, `Free Trial` count, degree order and provider-logo
  paths.
- Fresh Playwright captures at `1191 x 979` and `1264 x 1312` must show four
  cards in each corrected collection, no missing images, no remote runtime
  presentation resources and no clone console failures.
- No commit is authorized.
